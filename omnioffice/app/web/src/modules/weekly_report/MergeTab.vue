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
import { ElMessage, ElMessageBox } from "element-plus";
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
/** 上传进度 0~100 —— 没有它用户会以为没上传成功，反复点，白白浪费带宽与磁盘 */
const uploadPercent = ref(0);
const uploadFileName = ref("");
const fileInput = ref<HTMLInputElement | null>(null);
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

/** 打开系统文件选择器 */
function pickFile() {
  if (uploading.value) return;
  fileInput.value?.click();
}

/** 原生 input 的 change：这里拿到的一定是用户刚选的文件 */
function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement;
  const raw = input.files?.[0];
  // 立刻清空：否则重新选择**同一个文件**不会再触发 change（替换场景就失效了）
  input.value = "";
  if (raw) void onPick(raw);
}

/** 拖拽上传 */
function onDrop(e: DragEvent) {
  if (uploading.value) return;
  const raw = e.dataTransfer?.files?.[0];
  if (raw) void onPick(raw);
}

async function onPick(raw: File) {
  // 防重复：正在上传时忽略后续选择（用户可能连点或拖了多个文件）
  if (uploading.value) return;

  // 替换前先确认：待处理文件只保留一份，传错了就没了
  if (hasFile.value) {
    try {
      await ElMessageBox.confirm(
        `当前已有待处理文件「${meta.value?.fileName || "待处理文件"}」，上传「${raw.name}」会**替换**它。`,
        "确认替换？",
        { type: "warning", confirmButtonText: "替换", cancelButtonText: "取消" },
      );
    } catch {
      return; // 用户取消，不动现有文件
    }
  }

  uploading.value = true;
  uploadPercent.value = 0;
  uploadFileName.value = raw.name;
  error.value = "";
  const replacing = hasFile.value;
  try {
    const res = await weeklyApi.uploadPendingFile(raw, (p) => {
      uploadPercent.value = p;
    });
    uploadPercent.value = 100;
    if (res.unchanged) {
      // 服务端发现内容与当前文件完全一致，没重复写盘 —— 如实告诉用户，
      // 别让他以为上传没生效又去重传一次
      ElMessage.info("内容与当前待处理文件完全相同，未重复写入");
    } else {
      ElMessage.success(`待处理文件「${raw.name}」已上传${replacing ? "（已替换原文件）" : ""}`);
    }
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    ElMessage.error(`上传失败：${error.value}`);
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
        <!-- 上传区：自实现（不依赖 el-upload 的 on-change 事件）。
             原因：实测本场景下 el-upload 的 on-change 不触发（文件已进 input.files
             但回调没来），原生 input 的 change 最可靠；进度、禁用、防重复也更好控。 -->
        <div
          class="drop"
          :class="{ busy: uploading }"
          @click="pickFile"
          @dragover.prevent
          @drop.prevent="onDrop"
        >
          <OOIcon name="upload" :size="26" />
          <p class="drop-main">{{ uploading ? "正在上传…" : "把待处理文件拖到这里，或点击选择" }}</p>
          <p class="drop-sub">支持 .xlsx，重新上传将替换现有文件</p>
          <input
            ref="fileInput"
            type="file"
            accept=".xlsx"
            class="drop-input"
            @change="onFilePicked"
          />
        </div>

        <!-- 上传进度：让用户明确看到「传了多少、传完没有」。
             没有它，用户看不到反馈就会以为没上传成功、反复点，白白浪费带宽与磁盘。 -->
        <div v-if="uploading" class="up-prog">
          <div class="up-prog-head">
            <span class="up-prog-name">{{ uploadFileName }}</span>
            <span class="up-prog-num">{{ uploadPercent }}%</span>
          </div>
          <el-progress
            :percentage="uploadPercent"
            :stroke-width="8"
            :show-text="false"
            :status="uploadPercent >= 100 ? 'success' : undefined"
          />
          <p class="up-prog-tip">上传中，请勿重复操作或关闭窗口</p>
        </div>

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
          <span class="opt-hint">合并会在工作簿里新增一个以阶段时间命名的工作表（如 261026-261030），并覆盖保存原文件</span>
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
.pad .drop {
  width: 100%;
}
.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--oo-space-2);
  padding: var(--oo-space-4);
  color: var(--oo-text-secondary);
  border: 1px dashed var(--oo-border-default);
  border-radius: var(--oo-radius-md);
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}
.drop:hover {
  border-color: var(--oo-brand);
  background: var(--oo-brand-soft);
}
.drop.busy {
  cursor: progress;
  opacity: 0.65;
}
.drop-input {
  display: none;
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
.up-prog {
  margin-top: var(--oo-space-3);
  padding: var(--oo-space-3);
  border-radius: var(--oo-radius-md);
  background: var(--oo-bg-surface-2);
}
.up-prog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-2);
  font-size: var(--oo-text-sm);
}
.up-prog-name {
  color: var(--oo-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.up-prog-num {
  color: var(--oo-brand);
  font-weight: var(--oo-weight-semibold);
  font-variant-numeric: tabular-nums;
}
.up-prog-tip {
  margin: var(--oo-space-2) 0 0;
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
