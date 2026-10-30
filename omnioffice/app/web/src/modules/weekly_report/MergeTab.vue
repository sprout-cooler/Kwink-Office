<script setup lang="ts">
/** 周报 · 合并周报（v1.0.35）：待处理文件上传与管理 + 一键合并。
 *
 * 流程：① 上传待处理文件（可随时替换）→ ② 文件持久保存在共享目录
 *      → ③ 点击「合并并导出」→ 执行导出生成 xlsx → 把它复制成
 *         待处理文件里的**一个新工作表** → 就地替换原文件。
 *
 * 两个刻意的设计：
 * - **只留一份待处理文件**：上传即替换，避免多版本让人分不清哪个是最新的。
 * - **合并前自动备份**：合并是就地覆盖，一旦中途失败原文件会被截断且不可逆；
 *   所以先备份、失败自动回滚，并把备份名展示给用户。
 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  weeklyApi,
  type MergeRecord,
  type PendingFileMeta,
} from "@/api/weekly-report";
import {
  OOCard,
  OOEmptyState,
  OOIcon,
  OOPageHeader,
  OOSectionTitle,
  OOToolbar,
} from "@/components/ui";

const meta = ref<PendingFileMeta | null>(null);
const history = ref<MergeRecord[]>([]);
const loading = ref(false);
const uploading = ref(false);
const merging = ref(false);
const error = ref("");

const scope = ref<"content" | "full">("content");
const dpi = ref(192);
const renderPng = ref(true);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [m, h] = await Promise.all([weeklyApi.pendingFile(), weeklyApi.mergeHistory()]);
    meta.value = m.item ?? null;
    history.value = h.items ?? [];
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function onPick(uploadFile: { raw?: File }) {
  const raw = uploadFile?.raw;
  if (!raw) return;
  uploading.value = true;
  error.value = "";
  try {
    await weeklyApi.uploadPendingFile(raw);
    ElMessage.success(`待处理文件「${raw.name}」已上传${meta.value ? "（已替换原文件）" : ""}`);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    uploading.value = false;
  }
}

async function doMerge() {
  merging.value = true;
  error.value = "";
  try {
    const r = await weeklyApi.mergeIntoPending({
      scope: scope.value,
      dpi: dpi.value,
      renderPng: renderPng.value,
    });
    ElMessage.success(
      `已合并为工作表「${r.sheetName}」，共 ${r.sheetCountAfter} 个工作表（合并前 ${r.sheetCountBefore}）`
    );
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    merging.value = false;
  }
}

async function doDownload() {
  error.value = "";
  try {
    await weeklyApi.downloadPendingFile();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function doDelete() {
  error.value = "";
  try {
    await weeklyApi.deletePendingFile();
    ElMessage.success("待处理文件已删除");
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

const hasFile = computed(() => meta.value !== null);
const fmtSize = (n: number) =>
  n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
const fmtTime = (iso: string) => (iso ? new Date(iso).toLocaleString("zh-CN") : "—");
</script>

<template>
  <div v-loading="loading" class="merge-tab">
    <OOPageHeader
      title="合并周报"
      description="上传你的待处理台账文件，一键把本期周报作为新工作表合并进去，并自动替换原文件"
      badge="🔀"
    >
      <el-button @click="load">
        <span class="oo-btn-icon"><OOIcon name="refresh" :size="16" /></span>
        刷新
      </el-button>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="blk" />

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="blk"
      title="待处理文件只保留一份：重新上传即替换。每次合并前会自动备份原文件，合并失败自动还原。"
    />

    <!-- 1. 上传待处理文件 -->
    <OOCard
      class="blk"
      title="1. 待处理文件"
      subtitle="合并的目标台账，支持 .xlsx；重新上传将替换现有文件"
      flush
    >
      <div class="pad">
        <el-upload drag :auto-upload="false" :show-file-list="false" accept=".xlsx" :on-change="onPick">
          <div class="drop">
            <OOIcon name="upload" :size="26" />
            <p class="drop-main">把待处理文件拖到这里，或点击选择</p>
            <p class="drop-sub">支持 .xlsx，重新上传将替换现有文件</p>
          </div>
        </el-upload>

        <div v-if="hasFile" class="cur">
          <div class="cur-row">
            <span class="cur-label">当前文件</span>
            <span class="cur-value">{{ meta!.fileName || "待处理文件.xlsx" }}</span>
          </div>
          <div class="cur-row">
            <span class="cur-label">大小</span>
            <span class="oo-num">{{ fmtSize(meta!.sizeBytes) }}</span>
          </div>
          <div class="cur-row">
            <span class="cur-label">工作表数</span>
            <span class="oo-num">{{ meta!.sheetCount }}</span>
          </div>
          <div class="cur-row">
            <span class="cur-label">更新时间</span>
            <span class="oo-num oo-text-xs">{{ fmtTime(meta!.updatedAt) }}</span>
          </div>
          <div class="cur-actions">
            <el-button size="small" @click="doDownload">
              <span class="oo-btn-icon"><OOIcon name="download" :size="15" /></span>
              下载当前文件
            </el-button>
            <el-popconfirm title="删除待处理文件？合并时需要重新上传" @confirm="doDelete">
              <template #reference>
                <el-button size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
        <el-empty v-else description="还没有上传待处理文件" :image-size="72" />
      </div>
    </OOCard>

    <!-- 2. 合并并导出 -->
    <OOCard class="blk" title="2. 合并并导出" subtitle="执行导出后，把生成的表格追加为待处理文件的新工作表" flush>
      <div class="pad">
        <div class="opts">
          <span class="opt-label">口径</span>
          <el-radio-group v-model="scope" size="small">
            <el-radio-button value="content">连续内容区</el-radio-button>
            <el-radio-button value="full">完整表体</el-radio-button>
          </el-radio-group>
        </div>
        <div class="opts">
          <span class="opt-label">DPI</span>
          <el-input-number v-model="dpi" :min="72" :max="300" :step="24" size="small" />
          <span class="opt-hint">默认 192（≥192DPI 才够清晰）</span>
        </div>
        <div class="opts">
          <span class="opt-label">截图</span>
          <el-switch v-model="renderPng" />
          <span class="opt-hint">{{ renderPng ? "同时渲染区域截图" : "只产出 Excel" }}</span>
        </div>

        <div class="acts">
          <el-button type="primary" :loading="merging" :disabled="!hasFile" @click="doMerge">
            <span class="oo-btn-icon"><OOIcon name="merge" :size="16" /></span>
            {{ hasFile ? "合并并导出" : "请先上传待处理文件" }}
          </el-button>
          <span class="opt-hint">合并会用本期周报在工作簿里新增一个工作表，并覆盖保存原文件</span>
        </div>

        <p v-if="!hasFile" class="tip">
          上传后按钮才会启用 —— 合并需要一个目标工作簿。
        </p>
      </div>
    </OOCard>

    <!-- 3. 合并历史 -->
    <OOCard class="blk" title="3. 合并历史" :subtitle="`共 ${history.length} 次`" flush>
      <OOToolbar hint="每次合并留一条记录" dense />
      <el-table :data="history" size="small">
        <template #empty>
          <OOEmptyState variant="inbox" title="还没有合并记录" description="上传待处理文件后点击「合并并导出」" />
        </template>
        <el-table-column prop="sheetName" label="追加的工作表" min-width="160" />
        <el-table-column label="工作表数" width="120" align="center">
          <template #default="{ row }">
            <span class="oo-num">{{ row.sheetCountBefore }} → {{ row.sheetCountAfter }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="backupName" label="备份文件" min-width="200">
          <template #default="{ row }">
            <span class="oo-num oo-text-xs">{{ row.backupName || "—" }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="createdAt" label="时间" width="150">
          <template #default="{ row }">
            <span class="oo-num oo-text-xs oo-text-secondary">{{ fmtTime(row.createdAt) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </OOCard>
  </div>
</template>

<style scoped>
.merge-tab {
  padding-bottom: var(--oo-space-6);
}
.blk {
  margin-bottom: var(--oo-space-5);
}
.pad {
  padding: var(--oo-space-4);
}
/* 拖拽区默认不会撑满容器，左右会留一截空白 —— 显式撑满更整齐 */
.pad :deep(.el-upload),
.pad :deep(.el-upload-dragger) {
  width: 100%;
}
.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--oo-space-2);
  padding: var(--oo-space-4);
  color: var(--oo-text-secondary);
}
.drop-main {
  margin: 0;
  font-size: var(--oo-text-base);
  color: var(--oo-text-primary);
  font-weight: var(--oo-weight-medium);
}
.drop-sub {
  margin: 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}
.cur {
  margin-top: var(--oo-space-4);
  padding: var(--oo-space-3);
  border-radius: var(--oo-radius-md);
  background: var(--oo-bg-surface-2);
}
.cur-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--oo-space-3);
  font-size: var(--oo-text-sm);
  padding: 2px 0;
}
.cur-label {
  color: var(--oo-text-secondary);
}
.cur-value {
  color: var(--oo-text-primary);
}
.cur-actions {
  display: flex;
  gap: var(--oo-space-2);
  margin-top: var(--oo-space-3);
}
.opts {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-3);
  flex-wrap: wrap;
}
.opt-label {
  width: 56px;
  font-size: var(--oo-text-sm);
  color: var(--oo-text-secondary);
}
.opt-hint {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}
.acts {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  margin-top: var(--oo-space-2);
  flex-wrap: wrap;
}
.tip {
  margin: var(--oo-space-2) 0 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}
@media (max-width: 560px) {
  .opt-label {
    width: 100%;
  }
}
</style>
