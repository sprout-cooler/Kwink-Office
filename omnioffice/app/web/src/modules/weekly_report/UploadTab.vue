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
    <div class="upload-header">
      <span class="period">本周周期：{{ periodStart }} 起</span>
      <el-tag type="info" effect="plain">共 {{ totalCount }} 张</el-tag>
      <span class="tip">先选分区再上传；误传可直接拖到另一分区或用右下角下拉调整</span>
    </div>

    <!-- 失效原图警告（历史升级遗留）：一键清理后重传 -->
    <el-alert
      v-if="missingCount > 0"
      type="error"
      show-icon
      :closable="false"
      class="missing-bar"
    >
      <template #title>
        {{ missingCount }} 张截图的原图已丢失（旧版本升级时文件目录被清理，无法恢复）
        <el-button type="danger" size="small" plain style="margin-left: 12px" @click="purgeMissing">
          清除失效记录
        </el-button>
      </template>
    </el-alert>

    <!-- 识别操作栏：配置状态 + 触发 + 进度摘要 -->
    <div class="recognize-bar">
      <template v-if="recognize && !recognize.configured">
        <el-alert type="warning" :closable="false" show-icon class="rec-alert">
          尚未配置大模型 API Key——上传后可先存储，识别需要在「应用配置」中填写你的 Key（通义千问 / 豆包均可）。
        </el-alert>
      </template>
      <template v-else>
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
        <span v-if="busyCount > 0" class="rec-progress">
          <el-tag type="warning" effect="light">{{ busyCount }} 张识别中</el-tag>
        </span>
        <span v-else-if="recognize" class="rec-done">
          <el-tag type="success" effect="plain">已识别 {{ recognize.counts.done }} 张</el-tag>
        </span>
      </template>
    </div>

    <div class="partition-grid">
      <section
        v-for="p in PARTITIONS"
        :key="p.id"
        class="partition-card"
        :class="{ dragover: dragOverPartition === p.id }"
        @dragover.prevent="dragOverPartition = p.id"
        @dragleave="dragOverPartition = ''"
        @drop.prevent="onDrop($event, p.id)"
      >
        <header class="partition-head">
          <h3>{{ p.label }}</h3>
          <el-tag size="small">{{ statOf(p.id)?.total ?? 0 }} 张</el-tag>
        </header>
        <p class="partition-hint">{{ p.hint }}</p>

        <div class="dropzone" @click="pickFiles(p.id)">
          <div class="dz-icon">＋</div>
          <p>点击选择，或把图片拖到这里</p>
          <p class="dz-sub">jpg / png / webp，单张 ≤ 10MB</p>
        </div>

        <el-progress
          v-if="uploading[p.id]"
          :percentage="progress[p.id] ?? 0"
          :stroke-width="6"
          class="dz-progress"
        />

        <ul class="shot-list">
          <li v-for="s in itemsOf(p.id)" :key="s.id" class="shot-item" :class="{ 'is-missing': s.fileMissing }" draggable="true" @dragstart="dragId = s.id">
            <img v-if="!s.fileMissing" :src="screenshotRawUrl(s.id)" :alt="s.filename" class="shot-thumb" />
            <div v-else class="shot-thumb shot-thumb-missing" title="原图文件已丢失（历史升级遗留），请删除后重新上传">
              <span>原图已丢失</span>
            </div>
            <div class="shot-meta">
              <div class="shot-name" :title="s.filename">{{ s.filename }}</div>
              <div class="shot-sub">
                {{ fmtSize(s.size) }}
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
          <li v-if="itemsOf(p.id).length === 0" class="empty-line">暂无截图</li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.upload-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.recognize-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.rec-alert {
  flex: 1;
  min-width: 300px;
}
.period {
  font-weight: 600;
}
.tip {
  color: #909399;
  font-size: 12px;
}
.partition-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(260px, 1fr));
  gap: 14px;
}
.partition-card {
  border: 1px solid var(--oo-border);
  border-radius: 8px;
  padding: 14px;
  background: #fff;
  display: flex;
  flex-direction: column;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.partition-card.dragover {
  border-color: var(--oo-accent);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}
.partition-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.partition-head h3 {
  margin: 0;
  font-size: 15px;
}
.partition-hint {
  margin: 6px 0 10px;
  color: #909399;
  font-size: 12px;
  min-height: 32px;
}
.dropzone {
  border: 1px dashed #c0c4cc;
  border-radius: 8px;
  padding: 22px 12px;
  text-align: center;
  color: #909399;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.dropzone:hover {
  border-color: var(--oo-accent);
  background: #f5f9ff;
}
.dz-icon {
  font-size: 28px;
  line-height: 1;
  color: #c0c4cc;
}
.dropzone p {
  margin: 6px 0 0;
  font-size: 13px;
}
.dz-sub {
  font-size: 11px !important;
}
.dz-progress {
  margin-top: 8px;
}
.shot-list {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 40px;
}
.shot-item {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px 8px;
  cursor: grab;
}
.shot-item:active {
  cursor: grabbing;
}
.shot-thumb {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  background: #f5f7fa;
  flex-shrink: 0;
}
.shot-meta {
  flex: 1;
  min-width: 0;
}
.shot-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.shot-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #909399;
  font-size: 12px;
  margin-top: 2px;
}
.shot-move {
  width: 100%;
  margin-top: 4px;
}
.empty-line {
  color: #c0c4cc;
  font-size: 12px;
  text-align: center;
  padding: 10px 0;
}
</style>
