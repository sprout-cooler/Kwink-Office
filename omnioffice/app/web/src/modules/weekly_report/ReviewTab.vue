<script setup lang="ts">
// 识别校对 Tab（V10 3.8）：分区分组表格、置信度三级样式、原图局部放大对照、
// 行内编辑标题/时间、下拉改归属星期、跨分区移动、删除与手工新增。
//
// 设计要点：
// - 置信度 <0.8 才高亮，避免满屏红色淹没真正要处理的问题；
// - 时间字段编辑用「原文输入」（用户照着原图敲「周四 10:00」），服务端统一归一化；
// - 每次保存后用服务端返回的 DTO 覆盖本地行，确保「归一化后的结果」与后端一致，
//   避免前端自己猜日期格式导致两套口径。
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  weeklyApi,
  screenshotRawUrl,
  ASSIGNABLE_CATEGORIES,
  STAT_CATEGORY_LABELS,
  isTimeRequired,
  type PartitionId,
  type TaskItemDto,
} from "@/api/weekly-report";
import TaskTimeField from "./TaskTimeField.vue";

const loading = ref(false);
const saving = ref<number | null>(null);
const items = ref<TaskItemDto[]>([]);
const filterPartition = ref<PartitionId | "">("");
const filterIssue = ref(false);

/** 本周报周期起始日（YYYY-MM-DD），供时间字段做越界提示；取不到就不判定 */
const periodStart = ref("");

/** 行内时间草稿：id → { start, end }。
 *  提交任一时刻都必须把**两个字段**一起送服务端（_renormalize 收成对的原文），
 *  所以草稿挂在父组件，行内输入框与日历面板共用同一份，互不覆盖。 */
const timeDraft = reactive<Record<number, { start: string; end: string }>>({});

// 原图对照抽屉
const compareTask = ref<TaskItemDto | null>(null);

// 手工新增
const creating = ref(false);
const draft = ref({ title: "", partition: "offline_done" as PartitionId, startTime: "", endTime: "" });

const PARTITIONS: { id: PartitionId; label: string }[] = [
  { id: "offline_done", label: "本周线下工作" },
  { id: "online_done", label: "线上售后" },
  { id: "plan", label: "下周工作计划" },
];
const WEEKDAYS = ["未归组", "周一", "周二", "周三", "周四", "周五", "周六", "周日"];

const CONF_LABEL: Record<string, string> = {
  normal: "已识别",
  warning: "待确认",
  danger: "必填",
};

/** 需要人工关注的：低置信度未确认 / 时间解析失败。
 *  越界任务不计入此处 —— 它只提示不阻断（用户可能确实要报跨周任务），
 *  在「标记」列已用橙色tag 单独提示。
 *  时间相关只对「时间必填」分区生效：线上售后是会话量汇总、下周计划尚未发生，
 *  截图上本就没有逐条时刻，标红「必填」等于逼用户编一个。 */
function needsAttention(t: TaskItemDto): boolean {
  if (t.reviewed) return false;
  if (t.confidenceLevel !== "normal") return true;
  return isTimeRequired(t.partition) && t.warnings.includes("DATE_PARSE_FAILED");
}

/** 该分区是否要求时间（用于表单提示与行内标注） */
function timeRequiredFor(t: { partition: string }): boolean {
  return isTimeRequired(t.partition);
}

/** 无时间的非必填分区条目：说明它的去向，避免用户以为导出丢了 */
const timeOptionalNote = "按周汇总 / 尚未发生，无需时间；将计入汇总数量，不进星期块明细";

/** 手工新增弹窗里，当前分区是否要求时间 */
const draftTimeRequired = computed(() => isTimeRequired(draft.value.partition));

const visible = computed(() =>
  items.value.filter((t) => {
    if (filterPartition.value && t.partition !== filterPartition.value) return false;
    if (filterIssue.value && !needsAttention(t)) return false;
    return true;
  }),
);

const grouped = computed(() =>
  PARTITIONS.map((p) => ({
    ...p,
    tasks: visible.value.filter((t) => t.partition === p.id),
  })).filter((g) => g.tasks.length > 0),
);

const issueCount = computed(() => items.value.filter(needsAttention).length);
const totalCount = computed(() => items.value.length);

async function refresh() {
  loading.value = true;
  try {
    const [r, st] = await Promise.all([weeklyApi.tasks(), weeklyApi.state()]);
    items.value = r;
    periodStart.value = st.periodStart || "";
    // 每次刷新都重置草稿：以服务端归一化后的结果为准
    for (const t of r) {
      timeDraft[t.id] = { start: toEditable(t.startAt), end: toEditable(t.endAt) };
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
defineExpose({ refresh });

/** 保存单个任务：服务端返回归一化后的 DTO，直接覆盖本地行 */
async function save(task: TaskItemDto, patch: Record<string, unknown>, okMsg?: string) {
  saving.value = task.id;
  try {
    const updated = await weeklyApi.patchTask(task.id, patch as never);
    const idx = items.value.findIndex((t) => t.id === task.id);
    if (idx >= 0) items.value[idx] = updated;
    // 时间字段保存后同步草稿，避免与服务端归一化结果不一致（如 DATE_ONLY 补 00:00）
    if ("startTime" in patch || "endTime" in patch) {
      timeDraft[updated.id] = { start: toEditable(updated.startAt), end: toEditable(updated.endAt) };
    }
    if (okMsg) ElMessage.success(okMsg);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
    // 保存失败：草稿回退到服务端值，避免界面停留在没保存上的文本
    timeDraft[task.id] = { start: toEditable(task.startAt), end: toEditable(task.endAt) };
  } finally {
    saving.value = null;
  }
}

async function onTitleBlur(t: TaskItemDto, val: string) {
  const title = val.trim();
  if (!title || title === t.title) return;
  await save(t, { title }, "标题已更新");
}

/** 时间编辑：把 ISO 回显成人类可读的原图写法，便于用户照原图改 */
function toEditable(iso: string): string {
  if (!iso) return "";
  // 2026-10-09T15:30 → 2026-10-09 15:30
  return iso.replace("T", " ").slice(0, 16);
}

/** 某行的时间草稿（未初始化时按服务端值兜底） */
function draftOf(t: TaskItemDto): { start: string; end: string } {
  if (!timeDraft[t.id]) {
    timeDraft[t.id] = { start: toEditable(t.startAt), end: toEditable(t.endAt) };
  }
  return timeDraft[t.id];
}

/** 时间提交（行内输入与日历面板共用）：成对送 start/end，服务端统一归一化。
 *  与原时间完全一致时组件已短路，这里再兜一层，避免无谓请求。 */
async function commitTime(t: TaskItemDto) {
  const d = draftOf(t);
  if (d.start === toEditable(t.startAt) && d.end === toEditable(t.endAt)) return;
  await save(t, { startTime: d.start, endTime: d.end }, "时间已更新并归一化");
}

async function onWeekdayChange(t: TaskItemDto, wd: number) {
  await save(t, { weekday: wd }, "归属星期已更新");
}

async function onPartitionChange(t: TaskItemDto, p: PartitionId) {
  await save(t, { partition: p }, `已移到「${PARTITIONS.find((x) => x.id === p)?.label}」`);
}

async function onCategoryChange(t: TaskItemDto, cat: string) {
  await save(t, { statCategory: cat }, `已归类为「${STAT_CATEGORY_LABELS[cat] ?? cat}」，统计已更新`);
}

async function markReviewed(t: TaskItemDto) {
  await save(t, { reviewed: true }, "已标记为人工确认");
}

async function removeTask(t: TaskItemDto) {
  try {
    await ElMessageBox.confirm(`确定删除任务「${t.title}」？此操作不可撤销。`, "删除任务", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await weeklyApi.removeTask(t.id);
    items.value = items.value.filter((x) => x.id !== t.id);
    delete timeDraft[t.id];
    ElMessage.success("已删除");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

async function submitCreate() {
  if (!draft.value.title.trim()) {
    ElMessage.warning("请填写任务标题");
    return;
  }
  try {
    const t = await weeklyApi.createTask({
      title: draft.value.title.trim(),
      partition: draft.value.partition,
      startTime: draft.value.startTime.trim(),
      endTime: draft.value.endTime.trim(),
    });
    items.value.push(t);
    timeDraft[t.id] = { start: toEditable(t.startAt), end: toEditable(t.endAt) };
    draft.value = { title: "", partition: "offline_done", startTime: "", endTime: "" };
    creating.value = false;
    ElMessage.success("已手工新增");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

/** 低置信度批量确认（点过原图对照后逐条确认） */
async function confirmAllVisible() {
  const targets = visible.value.filter(needsAttention);
  if (targets.length === 0) return;
  try {
    await ElMessageBox.confirm(
      `将把当前视图的 ${targets.length} 条任务标记为「已人工确认」。请确认你已逐条核对过原图。`,
      "批量确认",
      { type: "warning", confirmButtonText: "确认", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  let ok = 0;
  for (const t of targets) {
    try {
      const updated = await weeklyApi.patchTask(t.id, { reviewed: true });
      const idx = items.value.findIndex((x) => x.id === t.id);
      if (idx >= 0) items.value[idx] = updated;
      ok += 1;
    } catch {
      /* 单条失败不中断批次 */
    }
  }
  ElMessage.success(`已确认 ${ok} 条`);
}
</script>

<template>
  <div v-loading="loading" class="review-tab">
    <div class="review-bar">
      <span class="period">共 {{ totalCount }} 条任务</span>
      <el-tag v-if="issueCount > 0" type="warning" effect="light">
        {{ issueCount }} 条待人工确认
      </el-tag>
      <el-tag v-else-if="totalCount > 0" type="success" effect="light">全部已确认</el-tag>

      <el-select v-model="filterPartition" placeholder="全部分区" clearable size="small" class="w-160">
        <el-option v-for="p in PARTITIONS" :key="p.id" :label="p.label" :value="p.id" />
      </el-select>
      <el-checkbox v-model="filterIssue" label="只看待确认" />
      <span class="spacer" />
      <el-button v-if="issueCount > 0" size="small" @click="confirmAllVisible">
        批量确认（当前视图）
      </el-button>
      <el-button size="small" type="primary" plain @click="creating = true">手工新增</el-button>
    </div>

    <!-- 原图对照抽屉：低置信度时对照抄录 -->
    <el-drawer
      :model-value="!!compareTask"
      title="原图对照"
      size="56%"
      direction="rtl"
      @update:model-value="(v: boolean) => { if (!v) compareTask = null; }"
    >
      <div v-if="compareTask" class="cmp">
        <div class="cmp-img">
          <img v-if="compareTask.screenshotId" :src="screenshotRawUrl(compareTask.screenshotId)" alt="原图" />
          <el-empty v-else description="手工新增任务，无原图" :image-size="80" />
        </div>
        <div class="cmp-info">
          <h4>{{ compareTask.title }}</h4>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="AI 抄录的开始">
              {{ compareTask.rawStart || "（空）" }}
            </el-descriptions-item>
            <el-descriptions-item label="归一化结果">
              {{ toEditable(compareTask.startAt) || "解析失败" }}
            </el-descriptions-item>
            <el-descriptions-item label="AI 抄录的结束">
              {{ compareTask.rawEnd || "（空）" }}
            </el-descriptions-item>
            <el-descriptions-item label="归一化结果">
              {{ toEditable(compareTask.endAt) || "—" }}
            </el-descriptions-item>
            <el-descriptions-item label="置信度">
              {{ (compareTask.confidence * 100).toFixed(0) }}%
            </el-descriptions-item>
            <el-descriptions-item label="原始状态">
              {{ compareTask.rawStatus || "—" }}
            </el-descriptions-item>
          </el-descriptions>
          <p v-if="compareTask.parseError" class="cmp-err">
            时间解析失败：{{ compareTask.parseError }}
          </p>
          <div class="cmp-actions">
            <el-button type="primary" @click="markReviewed(compareTask)">
              核对无误，标记已确认
            </el-button>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 手工新增 -->
    <el-dialog v-model="creating" title="手工新增任务" width="480px">
      <el-form label-width="80px" label-position="left">
        <el-form-item label="标题">
          <el-input v-model="draft.title" placeholder="如：协助处理线上工单" />
        </el-form-item>
        <el-form-item label="分区">
          <el-select v-model="draft.partition">
            <el-option v-for="p in PARTITIONS" :key="p.id" :label="p.label" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始时间" :required="draftTimeRequired">
          <!-- 新增弹窗只取文本（v-model），不接 @commit：最终以「新增」按钮统一提交 -->
          <TaskTimeField
            v-model:text="draft.startTime"
            :iso="draft.startTime"
            :period-start="periodStart"
            :allow-future="!draftTimeRequired"
            :placeholder="draftTimeRequired ? '如：10月9日 15:30 / 周四 10:00' : '非必填，可留空'"
          />
        </el-form-item>
        <el-form-item label="结束时间">
          <TaskTimeField
            v-model:text="draft.endTime"
            :iso="draft.endTime"
            :period-start="periodStart"
            allow-future
            placeholder="可留空"
          />
        </el-form-item>
      </el-form>
      <p class="tip">
        <template v-if="draftTimeRequired">
          时间支持 2026-10-09、10月9日、周四、261012 等多种写法，系统会自动归一化。
        </template>
        <template v-else>{{ timeOptionalNote }}。</template>
      </p>
      <template #footer>
        <el-button @click="creating = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">新增</el-button>
      </template>
    </el-dialog>

    <el-empty v-if="!loading && totalCount === 0" description="还没有识别结果 —— 请先到「任务上传」上传截图并识别" />
    <el-empty v-else-if="!loading && visible.length === 0" description="当前筛选条件下没有任务" />

    <section v-for="g in grouped" :key="g.id" class="group">
      <header class="group-head">
        <h3>{{ g.label }}</h3>
        <el-tag size="small" effect="plain">{{ g.tasks.length }} 条</el-tag>
      </header>

      <el-table :data="g.tasks" size="small" border class="tbl">
        <el-table-column label="任务标题" min-width="220">
          <template #default="{ row }: { row: TaskItemDto }">
            <el-input
              :model-value="row.title"
              size="small"
              placeholder="任务标题"
              @blur="(v: string) => onTitleBlur(row, v)"
            />
          </template>
        </el-table-column>

        <el-table-column label="开始时间" width="210">
          <template #default="{ row }: { row: TaskItemDto }">
            <TaskTimeField
              :text="draftOf(row).start"
              :iso="row.startAt"
              :period-start="periodStart"
              :allow-future="!timeRequiredFor(row)"
              :placeholder="timeRequiredFor(row) ? '如 周四 10:00' : '非必填，可留空'"
              :invalid="timeRequiredFor(row) && row.warnings.includes('DATE_PARSE_FAILED')"
              @update:text="(v: string) => (draftOf(row).start = v)"
              @commit="commitTime(row)"
            />
          </template>
        </el-table-column>

        <el-table-column label="结束时间" width="210">
          <template #default="{ row }: { row: TaskItemDto }">
            <TaskTimeField
              :text="draftOf(row).end"
              :iso="row.endAt"
              :period-start="periodStart"
              :allow-future="true"
              placeholder="可留空"
              @update:text="(v: string) => (draftOf(row).end = v)"
              @commit="commitTime(row)"
            />
          </template>
        </el-table-column>

        <el-table-column label="星期" width="100">
          <template #default="{ row }: { row: TaskItemDto }">
            <el-select
              :model-value="row.weekday"
              size="small"
              @change="(v: number) => onWeekdayChange(row, v)"
            >
              <el-option v-for="(w, i) in WEEKDAYS" :key="i" :label="w" :value="i" />
            </el-select>
          </template>
        </el-table-column>

        <el-table-column label="识别质量" width="130">
          <template #default="{ row }: { row: TaskItemDto }">
            <div class="conf-cell">
              <el-tag
                size="small"
                :type="row.confidenceLevel === 'normal' ? 'success' : row.confidenceLevel === 'warning' ? 'warning' : 'danger'"
                effect="plain"
              >
                {{ (row.confidence * 100).toFixed(0) }}%
              </el-tag>
              <el-button
                v-if="row.confidenceLevel !== 'normal'"
                link
                size="small"
                @click="compareTask = row"
              >
                对照
              </el-button>
              <el-tag v-if="row.reviewed" size="small" type="success" effect="dark">已确认</el-tag>
              <el-tag v-else-if="row.confidenceLevel !== 'normal'" size="small" type="warning" effect="dark">
                {{ CONF_LABEL[row.confidenceLevel] }}
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="标记" width="130">
          <template #default="{ row }: { row: TaskItemDto }">
            <el-tag v-if="row.outOfPeriod" size="small" type="warning" title="任务时间落在本周报周期之外">
              越界
            </el-tag>
            <el-tag
              v-if="!timeRequiredFor(row) && !(row.startAt || '').trim()"
              size="small"
              type="info"
              effect="plain"
              :title="timeOptionalNote"
            >
              仅计量
            </el-tag>
            <el-tag v-if="row.manual" size="small" type="info" effect="plain">手工</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="统计分类" width="130">
          <template #default="{ row }: { row: TaskItemDto }">
            <el-select
              :model-value="row.statCategory"
              size="small"
              placeholder="未分类"
              @change="(v: string) => onCategoryChange(row, v)"
            >
              <el-option
                v-for="c in ASSIGNABLE_CATEGORIES"
                :key="c"
                :label="STAT_CATEGORY_LABELS[c]"
                :value="c"
              />
            </el-select>
          </template>
        </el-table-column>

        <el-table-column label="归属分区" width="140">
          <template #default="{ row }: { row: TaskItemDto }">
            <el-select
              :model-value="row.partition"
              size="small"
              @change="(v: PartitionId) => onPartitionChange(row, v)"
            >
              <el-option v-for="p in PARTITIONS" :key="p.id" :label="p.label" :value="p.id" />
            </el-select>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }: { row: TaskItemDto }">
            <el-button
              v-if="!row.reviewed && row.confidenceLevel !== 'normal'"
              link
              type="primary"
              size="small"
              @click="markReviewed(row)"
            >
              确认
            </el-button>
            <el-button link type="danger" size="small" @click="removeTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.review-tab {
  padding-bottom: 24px;
}
.review-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.review-bar .spacer {
  flex: 1;
}
.review-bar .w-160 {
  width: 160px;
}
.period {
  font-weight: 600;
}
.group {
  margin-bottom: 20px;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.group-head h3 {
  margin: 0;
  font-size: 15px;
}
.tbl {
  width: 100%;
}
.conf-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 0;
}
/* 原图对照 */
.cmp {
  display: flex;
  gap: 16px;
}
.cmp-img {
  flex: 1;
  min-width: 0;
}
.cmp-img img {
  width: 100%;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
}
.cmp-info {
  width: 300px;
  flex-shrink: 0;
}
.cmp-info h4 {
  margin: 0 0 10px;
  font-size: 15px;
}
.cmp-err {
  color: var(--el-color-danger);
  font-size: 12px;
  margin: 10px 0;
}
.cmp-actions {
  margin-top: 14px;
}
</style>
