<script setup lang="ts">
// 任务上传 Tab（V10 3.4.1 / 3.10）：三分区并列、拖拽上传、缩略图、进度、去重提示、
// 删除、跨分区调整归属（下拉 + 拖拽到另一分区卡片双通道）、识别触发与进度推送。
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  weeklyApi,
  screenshotRawUrl,
  recognizeEventsUrl,
  type PartitionId,
  type PartitionStat,
  type RecognizeStatus,
  type ScreenshotItem,
} from "@/api/weekly-report";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOStatTile } from "@/components/ui";

interface PartitionDef {
  id: PartitionId;
  label: string;
  hint: string;
}
const PARTITIONS: PartitionDef[] = [
  { id: "offline_done", label: "本周线下工作", hint: "已完成的线下任务（培训/售后/售前按标题区分）" },
  { id: "online_done", label: "线上售后", hint: "已完成的线上售后任务，直接计入线上售后数量" },
  { id: "plan", label: "下周工作计划", hint: "处理中的工单 / 下周计划类截图" },
];

const loading = ref(false);
const uploading = ref<Record<string, boolean>>({});
const progress = ref<Record<string, number>>({});
const stats = ref<PartitionStat[]>([]);
const periodStart = ref("");
const items = ref<ScreenshotItem[]>([]);
const dragId = ref<number | null>(null);
const dragOverPartition = ref<PartitionId | "">("");

// ---- 识别状态与进度推送
const recognize = ref<RecognizeStatus | null>(null);
const recognizing = ref(false);
let ws: WebSocket | null = null;
let wsRetryTimer: ReturnType<typeof setTimeout> | null = null;

const pendingCount = computed(() => recognize.value?.counts.pending ?? 0);
const failedCount = computed(() => recognize.value?.counts.failed ?? 0);
const busyCount = computed(() => (recognize.value?.counts.pending ?? 0) + (recognize.value?.counts.processing ?? 0));

const totalCount = computed(() => stats.value.reduce((n, p) => n + p.total, 0));
const missingCount = computed(() => items.value.filter((i) => i.fileMissing).length);

/** 已识别张数（顶部指标块展示用） */
const doneCount = computed(() => recognize.value?.counts.done ?? 0);

function itemsOf(pid: PartitionId): ScreenshotItem[] {
  return items.value.filter((i) => i.partition === pid);
}
function statOf(pid: PartitionId): PartitionStat | undefined {
  return stats.value.find((s) => s.id === pid);
}

async function refresh() {
  loading.value = true;
  try {
    const [state, list, rec] = await Promise.all([
      weeklyApi.state(),
      weeklyApi.list(),
      weeklyApi.recognizeStatus().catch(() => null),
    ]);
    stats.value = state.partitions;
    periodStart.value = state.periodStart;
    items.value = list;
    if (rec) recognize.value = rec;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

// ---- 识别触发与实时进度
async function startRecognize() {
  recognizing.value = true;
  try {
    const r = await weeklyApi.recognize();
    if (r.enqueued === 0) ElMessage.info("没有待识别的截图（processing/done 不会重复识别）");
    else ElMessage.success(`已入队 ${r.enqueued} 张，识别进行中…`);
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    recognizing.value = false;
  }
}

async function retryFailed() {
  recognizing.value = true;
  try {
    const r = await weeklyApi.recognizeRetryFailed();
    if (r.enqueued === 0) ElMessage.info("没有失败的截图");
    else ElMessage.success(`已重新入队 ${r.enqueued} 张`);
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    recognizing.value = false;
  }
}

function connectWs() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try {
    ws = new WebSocket(recognizeEventsUrl());
  } catch {
    return;
  }
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data?.type === "progress") {
        // 有状态变化就增量刷新（数据量小，全量刷新简单可靠）
        void refresh();
      }
    } catch {
      /* 心跳等忽略 */
    }
  };
  ws.onclose = () => {
    ws = null;
    // 断线自动重连（页面在后台被挂起等场景）
    wsRetryTimer = setTimeout(connectWs, 5000);
  };
}

onMounted(() => {
  void refresh();
  connectWs();
});
onBeforeUnmount(() => {
  if (wsRetryTimer) clearTimeout(wsRetryTimer);
  ws?.close();
});

function pickFiles(pid: PartitionId) {
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.accept = "image/jpeg,image/png,image/webp";
  input.onchange = () => {
    if (input.files && input.files.length > 0) void doUpload(pid, Array.from(input.files));
  };
  input.click();
}

async function doUpload(pid: PartitionId, files: File[]) {
  uploading.value[pid] = true;
  progress.value[pid] = 0;
  try {
    const r = await weeklyApi.upload(pid, files, (pct) => (progress.value[pid] = pct));
    if (r.accepted.length) ElMessage.success(`${pid}：已接收 ${r.accepted.length} 张`);
    if (r.duplicates.length) ElMessage.warning(`跳过 ${r.duplicates.length} 张重复图片`);
    for (const rej of r.rejected) ElMessage.error(`${rej.filename}：${rej.reason}`);
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    uploading.value[pid] = false;
    progress.value[pid] = 0;
  }
}

function onDrop(e: DragEvent, pid: PartitionId) {
  dragOverPartition.value = "";
  // 来自本页缩略图拖动 → 改归属；来自系统文件拖入 → 上传
  if (dragId.value !== null) {
    const id = dragId.value;
    dragId.value = null;
    void moveTo(id, pid);
    return;
  }
  const files = Array.from(e.dataTransfer?.files ?? []).filter((f) =>
    ["image/jpeg", "image/png", "image/webp"].includes(f.type),
  );
  if (files.length) void doUpload(pid, files);
}

async function moveTo(id: number, pid: PartitionId) {
  const target = items.value.find((i) => i.id === id);
  if (!target || target.partition === pid) return;
  try {
    await weeklyApi.move(id, pid);
    ElMessage.success(`已移动到「${PARTITIONS.find((p) => p.id === pid)?.label}」`);
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

async function remove(item: ScreenshotItem) {
  try {
    await ElMessageBox.confirm(`确定删除「${item.filename}」？原图与识别结果将一并移除。`, "删除截图", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await weeklyApi.remove(item.id);
    ElMessage.success("已删除");
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

async function purgeMissing() {
  try {
    await ElMessageBox.confirm(
      `检测到 ${missingCount.value} 张截图的原图文件已丢失（历史版本升级所致，无法恢复）。将清除这些失效记录及其识别结果，之后请重新上传截图。是否继续？`,
      "清理失效记录",
      { type: "warning", confirmButtonText: "清除并重传", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    const r = await weeklyApi.purgeMissing();
    ElMessage.success(`已清除 ${r.removed} 条失效记录`);
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

function fmtSize(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
}

const statusTag = { pending: "info", processing: "warning", done: "success", failed: "danger" } as const;
const statusLabel = { pending: "待识别", processing: "识别中", done: "已识别", failed: "识别失败" } as const;

defineExpose({ refresh });
</script>

<template>
  <div v-loading="loading" class="upload-tab">
    <OOPageHeader
      title="任务上传"
      description="按分区上传本周工作截图并触发大模型识别，识别结果将在「识别校对」逐条核对"
      badge="🖼️"
    >
      <el-button :loading="loading" @click="refresh">
        <span class="oo-btn-icon"><OOIcon name="refresh" :size="16" /></span>
        刷新
      </el-button>
    </OOPageHeader>

    <!-- 周期信息 -->
    <div class="upload-meta">
      <span class="upload-meta-item">
        <OOIcon name="calendar" :size="15" />
        本周周期：<b class="oo-num">{{ periodStart || "—" }}</b> 起
      </span>
      <span class="upload-meta-tip">
        先选分区再上传；误传可直接拖到另一分区，或用缩略图下方的下拉调整归属
      </span>
    </div>

    <!-- 失效原图警告（历史升级遗留）：一键清理后重传 -->
    <el-alert
      v-if="missingCount > 0"
      type="error"
      show-icon
      :closable="false"
      class="oo-mb-4"
    >
      <template #title>
        {{ missingCount }} 张截图的原图已丢失（旧版本升级时文件目录被清理，无法恢复）
        <el-button type="danger" size="small" plain class="alert-btn" @click="purgeMissing">
          清除失效记录
        </el-button>
      </template>
    </el-alert>

    <!-- 识别操作栏：配置状态 + 触发 + 进度摘要 -->
    <div class="upload-kpis oo-mb-4">
      <OOStatTile
        label="截图总数"
        icon="🖼️"
        tone="brand"
        :value="totalCount"
        hint="本周已上传"
      />
      <OOStatTile
        label="待识别"
        icon="⏳"
        tone="amber"
        :value="pendingCount"
        hint="等待识别"
      />
      <OOStatTile
        label="已识别"
        icon="✅"
        tone="green"
        :value="doneCount"
        hint="可进入校对"
      />
      <OOStatTile
        label="失效原图"
        icon="⚠️"
        tone="red"
        :value="missingCount"
        :hint="missingCount > 0 ? '需清理后重传' : '无失效记录'"
      />
    </div>

    <OOCard title="识别状态" subtitle="上传完成后可批量触发识别，识别进度实时回填" class="oo-mb-4">
      <el-alert
        v-if="recognize && !recognize.configured"
        type="warning"
        :closable="false"
        show-icon
      >
        尚未配置大模型 API Key——上传后可先存储，识别需要在「应用配置」中填写你的 Key（通义千问 / 豆包均可）。
      </el-alert>
      <div v-else class="recognize-bar">
        <el-button
          type="primary"
          :loading="recognizing"
          :disabled="pendingCount === 0"
          @click="startRecognize"
        >
          开始识别（{{ pendingCount }} 张待识别）
        </el-button>
        <el-button v-if="failedCount > 0" :loading="recognizing" type="warning" @click="retryFailed">
          重试失败（{{ failedCount }}）
        </el-button>
        <el-tag v-if="busyCount > 0" type="warning" effect="light">{{ busyCount }} 张识别中</el-tag>
        <el-tag v-else-if="recognize" type="success" effect="plain">
          已识别 {{ recognize.counts.done }} 张
        </el-tag>
      </div>
    </OOCard>

    <!-- 三个分区的上传区 -->
    <div class="partition-grid">
      <div
        v-for="p in PARTITIONS"
        :key="p.id"
        class="partition"
        :class="{ 'is-dragover': dragOverPartition === p.id }"
        @dragover.prevent="dragOverPartition = p.id"
        @dragleave="dragOverPartition = ''"
        @drop.prevent="onDrop($event, p.id)"
      >
        <OOCard :title="p.label" :subtitle="p.hint" class="partition-card">
          <template #actions>
            <el-tag size="small" type="info" effect="plain">
              <span class="oo-num">{{ statOf(p.id)?.total ?? 0 }}</span> 张
            </el-tag>
          </template>

          <div class="dropzone" @click="pickFiles(p.id)">
            <span class="dz-icon"><OOIcon name="upload" :size="22" /></span>
            <p class="dz-title">点击选择，或把图片拖到这里</p>
            <p class="dz-sub">jpg / png / webp，单张 ≤ 10MB</p>
          </div>

          <el-progress
            v-if="uploading[p.id]"
            :percentage="progress[p.id] ?? 0"
            :stroke-width="6"
            class="dz-progress"
          />

          <ul v-if="itemsOf(p.id).length" class="shot-list">
            <li
              v-for="s in itemsOf(p.id)"
              :key="s.id"
              class="shot-item"
              :class="{ 'is-missing': s.fileMissing }"
              draggable="true"
              @dragstart="dragId = s.id"
            >
              <img
                v-if="!s.fileMissing"
                :src="screenshotRawUrl(s.id)"
                :alt="s.filename"
                class="shot-thumb"
              />
              <div
                v-else
                class="shot-thumb shot-thumb-missing"
                title="原图文件已丢失（历史升级遗留），请删除后重新上传"
              >
                <OOIcon name="trash" :size="16" />
              </div>
              <div class="shot-meta">
                <div class="shot-name oo-truncate" :title="s.filename">{{ s.filename }}</div>
                <div class="shot-sub">
                  <span class="oo-num">{{ fmtSize(s.size) }}</span>
                  <el-tag
                    size="small"
                    :type="statusTag[s.recognizeStatus]"
                    :title="s.recognizeStatus === 'failed' ? s.recognizeError : undefined"
                  >
                    {{ statusLabel[s.recognizeStatus] }}{{ s.taskCount > 0 ? `（${s.taskCount} 条）` : "" }}
                  </el-tag>
                </div>
                <el-select
                  :model-value="s.partition"
                  size="small"
                  class="shot-move"
                  @change="(v: PartitionId) => moveTo(s.id, v)"
                >
                  <el-option v-for="pp in PARTITIONS" :key="pp.id" :label="pp.label" :value="pp.id" />
                </el-select>
              </div>
              <el-button link type="danger" size="small" @click="remove(s)">删除</el-button>
            </li>
          </ul>

          <OOEmptyState
            v-else
            class="part-empty"
            variant="inbox"
            title="暂无截图"
            description="把本周的截图拖进上方虚线框，或点击虚线框从电脑中选择文件"
          />
        </OOCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.upload-tab {
  padding-bottom: var(--oo-space-6);
}

.oo-btn-icon {
  display: inline-flex;
  align-items: center;
  margin-right: var(--oo-space-1);
}

/* —— 周期信息行 —— */
.upload-meta {
  display: flex;
  align-items: center;
  gap: var(--oo-space-4);
  flex-wrap: wrap;
  margin-bottom: var(--oo-space-4);
  font-size: var(--oo-text-sm);
  color: var(--oo-text-secondary);
}

.upload-meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--oo-space-2);
}

.upload-meta-item b {
  color: var(--oo-text-primary);
  font-weight: var(--oo-weight-semibold);
}

.upload-meta-tip {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.alert-btn {
  margin-left: var(--oo-space-3);
}

/* —— 识别操作栏 —— */
.upload-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr));
  gap: var(--oo-space-3);
}

.recognize-bar {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
}

/* —— 分区栅格 —— */
.partition-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(min(280px, 100%), 1fr));
  gap: var(--oo-space-4);
  align-items: start;
}

.partition {
  display: flex;
  min-width: 0;
  border-radius: var(--oo-radius-lg);
  transition: box-shadow var(--oo-dur-base) var(--oo-ease-out);
}

.partition.is-dragover {
  box-shadow: var(--oo-focus-ring);
}

.partition-card {
  flex: 1;
  min-width: 0;
}

/* —— 拖拽上传区 —— */
.dropzone {
  border: 1px dashed var(--oo-border-strong);
  border-radius: var(--oo-radius-md);
  padding: var(--oo-space-6) var(--oo-space-3);
  text-align: center;
  color: var(--oo-text-tertiary);
  cursor: pointer;
  background: var(--oo-bg-surface-2);
  transition:
    border-color var(--oo-dur-base) var(--oo-ease-out),
    background var(--oo-dur-base) var(--oo-ease-out),
    color var(--oo-dur-base) var(--oo-ease-out);
}

.dropzone:hover {
  border-color: var(--oo-border-brand);
  background: var(--oo-brand-soft);
  color: var(--oo-text-secondary);
}

.dz-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--oo-radius-md);
  background: var(--oo-bg-surface);
  border: 1px solid var(--oo-border-subtle);
  color: var(--oo-text-brand);
}

.dz-title {
  margin-top: var(--oo-space-2);
  font-size: var(--oo-text-sm);
  color: var(--oo-text-secondary);
}

.dz-sub {
  margin-top: var(--oo-space-1);
  font-size: var(--oo-text-2xs);
  color: var(--oo-text-tertiary);
}

.dz-progress {
  margin-top: var(--oo-space-3);
}

/* —— 缩略图列表 —— */
.shot-list {
  list-style: none;
  margin: var(--oo-space-3) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--oo-space-2);
}

.shot-item {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  border: 1px solid var(--oo-border-subtle);
  border-radius: var(--oo-radius-sm);
  padding: var(--oo-space-2);
  background: var(--oo-bg-surface-2);
  cursor: grab;
  transition:
    border-color var(--oo-dur-base) var(--oo-ease-out),
    background var(--oo-dur-base) var(--oo-ease-out);
}

.shot-item:hover {
  border-color: var(--oo-border-default);
  background: var(--oo-bg-surface);
}

.shot-item:active {
  cursor: grabbing;
}

.shot-item.is-missing {
  border-color: var(--oo-danger-soft);
  background: var(--oo-danger-soft);
}

.shot-thumb {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: var(--oo-radius-xs);
  background: var(--oo-bg-surface-3);
  flex-shrink: 0;
}

.shot-thumb-missing {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--oo-danger-text);
}

.shot-meta {
  flex: 1;
  min-width: 0;
}

.shot-name {
  font-size: var(--oo-text-sm);
  color: var(--oo-text-primary);
  font-weight: var(--oo-weight-medium);
}

.shot-sub {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
  color: var(--oo-text-tertiary);
  font-size: var(--oo-text-xs);
  margin-top: var(--oo-space-1);
}

.shot-move {
  width: 100%;
  margin-top: var(--oo-space-2);
}

/* 分区内的空态收紧：三分区并列时不必占用过多高度 */
.part-empty :deep(.oo-empty) {
  padding: var(--oo-space-4) var(--oo-space-2);
  gap: var(--oo-space-1);
}

.part-empty :deep(.oo-empty-art) {
  margin-bottom: 0;
}

.part-empty :deep(.oo-empty-art svg) {
  width: 40px;
  height: 40px;
}

@media (max-width: 1100px) {
  .partition-grid {
    grid-template-columns: repeat(2, minmax(min(280px, 100%), 1fr));
  }
}

@media (max-width: 768px) {
  .partition-grid {
    grid-template-columns: 1fr;
  }
}
</style>
