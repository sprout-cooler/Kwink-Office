<script setup lang="ts">
// 导出历史：跨周报批次的全部导出记录，支持搜索 / 下载 / 重命名 / 删除。
//
// 每条记录都带着「用了哪个模板版本」，这是它被单独做成一个列表的原因 ——
// 三个月后回查「这份周报当时用的哪版模板」，没有版本号就只能靠猜。
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { weeklyApi, artifactUrl, type ExportHistoryItem } from "@/api/weekly-report";
import { OOEmptyState, OOIcon, OOToolbar } from "@/components/ui";

const items = ref<ExportHistoryItem[]>([]);
const loading = ref(false);
const keyword = ref("");
const keywordInput = ref("");

const list = computed(() => items.value);

async function refresh() {
  loading.value = true;
  try {
    items.value = await weeklyApi.exportHistory({ q: keywordInput.value.trim() });
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

function doSearch() {
  keyword.value = keywordInput.value;
  void refresh();
}

function clearSearch() {
  keywordInput.value = "";
  keyword.value = "";
  void refresh();
}

async function rename(row: ExportHistoryItem) {
  try {
    const { value } = await ElMessageBox.prompt(
      "重命名会同时改共享目录里的文件名与目录名，记录与文件始终保持一致。",
      "重命名导出记录",
      { inputValue: row.name, inputPlaceholder: "导出记录名称", confirmButtonText: "保存", cancelButtonText: "取消" },
    );
    const name = String(value ?? "").trim();
    if (!name) {
      ElMessage.warning("名称不能为空");
      return;
    }
    const r = await weeklyApi.renameArtifact(row.id, name);
    ElMessage.success(r.filesRenamed ? "已重命名记录与文件" : "记录已重命名，但共享目录里的文件未能同步改名");
    await refresh();
  } catch (e) {
    // ElMessageBox 取消会 reject，用 message 区分真实错误
    const msg = e instanceof Error ? e.message : String(e);
    if (msg && msg !== "cancel") ElMessage.error(msg);
  }
}

async function remove(row: ExportHistoryItem) {
  try {
    await ElMessageBox.confirm(
      `将删除记录「${row.name}」以及它在共享目录里的 xlsx 与截图，删除后不可恢复。`,
      "删除导出记录",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await weeklyApi.deleteArtifact(row.id);
    ElMessage.success("已删除");
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

function fmtSize(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
}

function fmtTime(s: string | null | undefined): string {
  return s ? s.slice(0, 16).replace("T", " ") : "—";
}

const STATUS_TAG: Record<string, { type: "success" | "warning" | "danger"; label: string }> = {
  ok: { type: "success", label: "完整" },
  partial: { type: "warning", label: "部分" },
  failed: { type: "danger", label: "失败" },
};

onMounted(refresh);
defineExpose({ refresh });
</script>

<template>
  <div v-loading="loading" class="hist">
    <OOToolbar dense>
      <template #left>
        <el-input
          v-model="keywordInput"
          clearable
          placeholder="按文件名搜索（如 周报_张三_2026-10-13）"
          class="hist-search"
          @keyup.enter="doSearch"
          @clear="clearSearch"
        >
          <template #prefix>
            <OOIcon name="search" :size="15" />
          </template>
        </el-input>
        <el-button type="primary" @click="doSearch">搜索</el-button>
        <span class="hist-count">共 <span class="oo-num">{{ list.length }}</span> 条</span>
      </template>
      <template #right>
        <el-button @click="refresh">
          <span class="oo-btn-icon"><OOIcon name="refresh" :size="15" /></span>
          刷新
        </el-button>
      </template>
    </OOToolbar>

    <OOEmptyState
      v-if="!list.length"
      variant="inbox"
      title="还没有导出记录"
      description="完成一次导出后，这里会保留文件名、导出时间与所用的模板版本"
    />
    <el-table v-else :data="list" size="small" stripe max-height="520" class="hist-tbl">
      <el-table-column label="文件名" min-width="210" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="cell-name oo-truncate">{{ row.name }}</div>
          <div class="cell-sub oo-truncate">{{ row.periodStart || "—" }} 起那一周</div>
        </template>
      </el-table-column>
      <el-table-column label="导出时间" width="150">
        <template #default="{ row }">
          <span class="oo-num">{{ fmtTime(row.createdAt) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="所用模板" width="150">
        <template #default="{ row }">
          <el-tag v-if="row.templateVersion" size="small" effect="plain">
            v{{ row.templateVersion }}
          </el-tag>
          <span v-else class="cell-dim">模板已删除</span>
          <div v-if="row.templateFilename" class="cell-sub oo-truncate" :title="row.templateFilename">
            {{ row.templateFilename }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="范围" width="110">
        <template #default="{ row }">
          <span class="oo-num">
            {{ row.scope === "content" ? "口径一" : "口径二" }} · {{ row.taskCount }} 条
          </span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_TAG[row.status].type" effect="plain">
            {{ STATUS_TAG[row.status].label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="100">
        <template #default="{ row }">
          <span v-if="row.xlsxExists" class="oo-num">{{ fmtSize(row.xlsxSize) }}</span>
          <span v-else class="cell-dim">文件已清理</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button v-if="row.xlsxExists" link type="primary" size="small">
            <a :href="artifactUrl(row.id, 'xlsx')" class="link" target="_blank">下载 xlsx</a>
          </el-button>
          <el-button v-if="row.pngCount > 0" link type="primary" size="small">
            <a :href="artifactUrl(row.id, 'png', 0)" class="link" target="_blank">截图</a>
          </el-button>
          <el-button link type="primary" size="small" @click="rename(row)">重命名</el-button>
          <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <p class="hist-foot">
      文件同时落在 NAS 共享目录「omnioffice/exports」，重命名与删除会同步到该目录。
    </p>
  </div>
</template>

<style scoped>
.hist-search {
  width: 320px;
  max-width: 100%;
}

.oo-btn-icon {
  display: inline-flex;
  align-items: center;
  margin-right: var(--oo-space-1);
}

.hist-count {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.hist-tbl {
  width: 100%;
}

.cell-name {
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
}

.cell-sub {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  max-width: 220px;
}

.cell-dim {
  color: var(--oo-text-placeholder);
  font-size: var(--oo-text-xs);
}

.link {
  color: var(--oo-text-brand);
  text-decoration: none;
}

.link:hover {
  text-decoration: underline;
}

.hist-foot {
  margin: var(--oo-space-3) 0 0;
  padding: var(--oo-space-3) var(--oo-space-5) var(--oo-space-4);
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

@media (max-width: 768px) {
  .hist-search {
    width: 100%;
  }
}
</style>
