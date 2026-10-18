<script setup lang="ts">
// 预览与导出 Tab（V10 3.11 / 4.5）：模板管理 + 卡点检查 + 双产物导出。
//
// 流程：上传模板 → 绑定本批次 → 校对通过（export-readiness）→ 选口径导出 → 拿 xlsx + 截图。
// 关键：卡点不通过时**禁用导出按钮**并把每个未处理项列出来，而不是让用户点了才报错。
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  weeklyApi,
  type ArtifactItem,
  type ExportReadiness,
  type TemplateItem,
} from "@/api/weekly-report";
import TemplateVersionDialog from "./TemplateVersionDialog.vue";
import ExportHistoryPanel from "./ExportHistoryPanel.vue";

const versionDialog = ref(false);
const historyRef = ref<InstanceType<typeof ExportHistoryPanel> | null>(null);

const loading = ref(false);
const exporting = ref(false);
const uploadingTpl = ref(false);

const templates = ref<TemplateItem[]>([]);
const boundId = ref<number | null>(null);
const readiness = ref<ExportReadiness | null>(null);
const artifacts = ref<ArtifactItem[]>([]);

// 导出参数
const scope = ref<"content" | "full">("content");
const renderPng = ref(true);

const bound = computed(() => templates.value.find((t) => t.id === boundId.value) ?? null);
const hasTemplate = computed(() => !!boundId.value);
const canExport = computed(() => hasTemplate.value && (readiness.value?.ready ?? false) && !exporting.value);

async function refreshAll() {
  loading.value = true;
  try {
    const [tpls, ready, arts] = await Promise.all([
      weeklyApi.templates(),
      weeklyApi.exportReadiness(),
      weeklyApi.artifacts(),
    ]);
    templates.value = tpls;
    readiness.value = ready;
    artifacts.value = arts;
    // 下拉值必须以**服务端当前批次绑定**为准（修复刷新后回显错误版本的问题）：
    // 已绑定 → 回显绑定版；未绑定 → 与导出回落规则一致，预选最新版（仅预选，不落库）。
    const serverBound = tpls.find((t) => t.bound)?.id ?? null;
    boundId.value = serverBound ?? tpls[0]?.id ?? null;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

onMounted(refreshAll);
defineExpose({ refresh: refreshAll });

/** 上传模板 */
function pickTemplate() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".xlsx";
  input.onchange = () => {
    const f = input.files?.[0];
    if (f) void doUpload(f);
  };
  input.click();
}

async function doUpload(f: File) {
  uploadingTpl.value = true;
  try {
    const r = await weeklyApi.uploadTemplate(f);
    if (r.duplicated) {
      ElMessage.info("该模板内容此前已上传过，文件已确认就位并为你选中");
    } else {
      ElMessage.success(`模板「${f.name}」已上传（v${r.template.version}）`);
    }
    boundId.value = r.template.id;
    // 先绑定再刷新，避免刷新把下拉值改回旧绑定后绑错版本
    await bind();
    await refreshAll();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    uploadingTpl.value = false;
  }
}

async function bind() {
  if (!boundId.value) return;
  try {
    await weeklyApi.bindTemplate(boundId.value);
    ElMessage.success(`已绑定模板 v${bound.value?.version}，本批次导出将使用该版本`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

async function removeTemplate(t: TemplateItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除模板「${t.filename}」（v${t.version}）？模板文件会一并删除；`
        + `若已有周报批次或导出历史引用它，会自动解除绑定`
        + `（导出历史与已生成的文件保留，下次导出改用最新版模板）。`,
      "删除模板",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await weeklyApi.removeTemplate(t.id);
    if (boundId.value === t.id) boundId.value = null;
    ElMessage.success("已删除（记录与模板文件已一并清理）");
    await refreshAll();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

async function doExport() {
  exporting.value = true;
  try {
    const r = await weeklyApi.runExport({ scope: scope.value, dpi: 192, renderPng: renderPng.value });
    if (r.status === "ok") {
      ElMessage.success(`导出完成：${r.xlsx}${r.pngs.length ? ` + ${r.pngs.length} 张截图` : ""}`);
    } else {
      ElMessage.warning(`xlsx 已导出，但截图未生成：${r.error || "渲染链不可用"}`);
    }
    await refreshAll();
    await historyRef.value?.refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
    // 卡点类错误可能带来新的阻断项，刷新一次
    await refreshAll();
  } finally {
    exporting.value = false;
  }
}

function fmtSize(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
}

/** 版本回滚后要同时刷新这里的模板列表与下方导出历史 */
async function onVersionChanged() {
  await refreshAll();
  await historyRef.value?.refresh();
}
</script>

<template>
  <div v-loading="loading" class="export-tab">
    <!-- 1. 模板管理 -->
    <el-card shadow="never" class="blk">
      <template #header>
        <div class="card-head">
          <b>1. 周报模板</b>
          <span class="card-sub">模板决定导出表格的样式与结构；可随时切换版本，导出仅使用当前选中版本；未选择时默认最新版</span>
        </div>
      </template>

      <div class="tpl-bar">
        <el-button type="primary" :loading="uploadingTpl" @click="pickTemplate">
          上传模板文件（.xlsx）
        </el-button>
        <el-select
          v-model="boundId"
          placeholder="选择本批次使用的模板"
          class="tpl-select"
          @change="bind"
        >
          <el-option
            v-for="t in templates"
            :key="t.id"
            :label="`v${t.version} · ${t.filename}（${fmtSize(t.size)}）`"
            :value="t.id"
          />
        </el-select>
        <el-tag v-if="bound" type="success" effect="plain">当前绑定 v{{ bound.version }}</el-tag>
        <el-button size="small" @click="versionDialog = true">版本管理 / 对比 / 回滚</el-button>
      </div>

      <el-table v-if="templates.length" :data="templates" size="small" border class="tpl-tbl">
        <el-table-column label="版本" width="70">
          <template #default="{ row }">
            <el-tag size="small" :type="row.id === boundId ? 'success' : 'info'" effect="plain">
              v{{ row.version }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="文件名" prop="filename" min-width="200" />
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ fmtSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="结构校验" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.anchorOk ? 'success' : 'danger'" effect="plain">
              {{ row.anchorOk ? "通过" : "不通过" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="removeTemplate(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="尚未上传模板 —— 导出需要先上传周报模板文件" :image-size="70" />
    </el-card>

    <TemplateVersionDialog v-model="versionDialog" :templates="templates" @changed="onVersionChanged" />

    <!-- 2. 导出前检查 -->
    <el-card shadow="never" class="blk">
      <template #header>
        <div class="card-head">
          <b>2. 导出前检查</b>
          <el-tag v-if="readiness?.ready" type="success" effect="plain">可以导出</el-tag>
          <el-tag v-else type="warning" effect="plain">有未处理项</el-tag>
        </div>
      </template>

      <div v-if="readiness" class="ready-box">
        <div class="ready-line">
          <span>本周任务：<b>{{ readiness.taskCount }}</b> 条</span>
          <span v-if="readiness.unclassified > 0">
            未分类 <b>{{ readiness.unclassified }}</b> 条（不阻断导出，可导出后留空）
          </span>
        </div>

        <template v-if="readiness.reasons.length === 0">
          <el-alert
            type="success"
            :closable="false"
            show-icon
            :title="(readiness.notices?.length ?? 0) > 0 ? '可以导出（有非阻断提示）' : '全部检查通过，可以导出'"
          />
        </template>
        <ul v-else class="reason-list">
          <li v-for="r in readiness.reasons" :key="r.code">
            <el-tag size="small" type="warning" effect="plain">{{ r.label }} ×{{ r.count }}</el-tag>
            <span class="reason-hint">{{ r.hint }}</span>
          </li>
        </ul>

        <!-- 非阻断提示：告知条目去向，不拦住导出 -->
        <ul v-if="(readiness.notices?.length ?? 0) > 0" class="notice-list">
          <li v-for="n in readiness.notices" :key="n.code">
            <el-tag size="small" type="info" effect="plain">{{ n.label }} ×{{ n.count }}</el-tag>
            <span class="reason-hint">{{ n.hint }}</span>
          </li>
        </ul>
      </div>
    </el-card>

    <!-- 3. 导出 -->
    <el-card shadow="never" class="blk">
      <template #header>
        <div class="card-head">
          <b>3. 导出双产物</b>
          <span class="card-sub">Excel 保真文件 + 区域截图，成对产出</span>
        </div>
      </template>

      <el-form label-width="100px" label-position="left" class="exp-form">
        <el-form-item label="截图口径">
          <el-radio-group v-model="scope">
            <el-radio-button value="content">口径一 · 连续内容区</el-radio-button>
            <el-radio-button value="full">口径二 · 完整表体</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="区域截图">
          <el-switch v-model="renderPng" />
          <span class="field-hint">
            关闭则只导出 Excel（更快）。截图需容器内 LibreOffice，192DPI 保��清晰度
          </span>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="exporting"
            :disabled="!canExport"
            @click="doExport"
          >
            导出
          </el-button>
          <span v-if="!hasTemplate" class="tip danger">请先上传并绑定模板</span>
          <span v-else-if="readiness && !readiness.ready" class="tip danger">
            请先处理上方未完成项
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 4. 导出历史（跨批次全量：文件名 / 导出时间 / 所用模板及版本 / 下载 · 重命名 · 删除） -->
    <el-card shadow="never" class="blk">
      <template #header>
        <div class="card-head">
          <b>4. 导出历史</b>
          <span class="card-sub">
            包含所有周报批次的导出记录；文件同时落在 NAS 共享目录「omnioffice/exports」
          </span>
        </div>
      </template>

      <ExportHistoryPanel ref="historyRef" />
    </el-card>
  </div>
</template>

<style scoped>
.export-tab {
  padding-bottom: 24px;
  max-width: 980px;
}
.blk {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.card-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: normal;
}
.tpl-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.tpl-select {
  width: 320px;
}
.tpl-tbl {
  width: 100%;
}
.ready-box {
  line-height: 1.8;
}
.ready-line {
  display: flex;
  gap: 20px;
  font-size: 13px;
  margin-bottom: 10px;
  color: var(--el-text-color-secondary);
}
.reason-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.notice-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 8px;
}
.notice-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.reason-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.reason-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.exp-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.field-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: 10px;
}
.tip {
  font-size: 12px;
  margin-left: 10px;
  color: var(--el-text-color-secondary);
}
.tip.danger {
  color: var(--el-color-danger);
}
/* 产物列表 */
.art-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.art {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px;
}
.art-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.art-name {
  font-weight: 600;
  font-size: 13px;
}
.art-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}
.art-files {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 13px;
}
.file-link {
  color: var(--el-color-primary);
  text-decoration: none;
}
.file-link:hover {
  text-decoration: underline;
}
.file-gone {
  color: var(--el-text-color-placeholder);
}
.art-err {
  margin-top: 8px;
}
.art-preview {
  margin-top: 10px;
  max-width: 420px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}
</style>
