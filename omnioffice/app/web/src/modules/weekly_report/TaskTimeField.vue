<script setup lang="ts">
// 行内时间字段：可点击编辑 + 原位弹出日期时间选择器（V10 M3 识别校对）。
//
// 设计要点：
// - 提交口径不变 —— 组件只产出「原始文本」，父组件原样送 patchTask(startTime/endTime)，
//   服务端仍走 dateparse.normalize_task 归一化。日历选出的 `YYYY-MM-DD HH:mm`
//   与手敲的「周四 10:00」「261012」共用同一条解析规则，不出现两套口径；
// - 两种方式可切换 —— 点击输入框在原位弹出面板，面板内「日历选择 / 手动输入」两个页签，
//   输入框本身也始终可直接敲字、回车或失焦提交，兼容原有手工录入习惯；
// - 校验分两层：本地只拦「未来时间」这类必错项（已完成类分区），越界/解析失败一律放行
//   交给服务端 dateparse 判定，界面已有 cell-err 标红与「越界」标记兜底。
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { OOIcon } from "@/components/ui";

const props = withDefaults(
  defineProps<{
    /** 草稿文本（父组件持有，兄弟字段提交时要带上对方的草稿） */
    text: string;
    /** 归一化后的 ISO 原值，用于「与原时间相同则不提交」 */
    iso: string;
    placeholder?: string;
    /** 解析失败标红（父组件按 warnings.DATE_PARSE_FAILED 传） */
    invalid?: boolean;
    /** 周报周期起始日 YYYY-MM-DD；为空时不做越界判定 */
    periodStart?: string;
    /** 允许未来时间：「下周工作计划」尚未发生，本就该落在未来 */
    allowFuture?: boolean;
  }>(),
  { placeholder: "", invalid: false, periodStart: "", allowFuture: false },
);

const emit = defineEmits<{
  (e: "update:text", v: string): void;
  (e: "commit", v: string): void;
}>();

const panelOpen = ref(false);
const mode = ref<"calendar" | "manual">("calendar");
const manualText = ref("");

/** ISO → 与服务端 toEditable 一致的可读文本；空值统一回空串 */
function isoText(iso: string): string {
  if (!iso) return "";
  return iso.replace("T", " ").slice(0, 16);
}

/** 只解析「标准可读格式」；手敲的自由写法解析不了就返回 null，交给服务端判 */
function parseStandard(t: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(t.trim());
  if (!m) return null;
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  return Number.isNaN(d.getTime()) ? null : d;
}

const periodStartDate = computed(() =>
  props.periodStart ? parseStandard(`${props.periodStart} 00:00`) : null,
);
const periodEndDate = computed(() => {
  const s = periodStartDate.value;
  if (!s) return null;
  const e = new Date(s.getTime());
  e.setDate(e.getDate() + 6);
  return e;
});

/** 日历回填值：仅标准格式可回填，自由写法（如「周四 10:00」）显示为空待用户重选 */
const calendarValue = computed<string>({
  get: () => {
    const t = props.text.trim();
    return parseStandard(t) ? t : "";
  },
  set: (v: string) => emit("update:text", v ?? ""),
});

/** 已完成类分区在日历里直接禁掉未来日期，从源头少踩一次坑 */
function disabledDate(d: Date): boolean {
  if (props.allowFuture) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return d.getTime() < today.getTime();
}

function fmtDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 面板提示：把周报周期说清楚，避免用户选了日期却不知道为什么被标越界 */
const hint = computed(() => {
  const bits: string[] = ["选中后立即回填并保存"];
  const ps = periodStartDate.value;
  const pe = periodEndDate.value;
  if (ps && pe) {
    bits.push(`本周期 ${fmtDate(ps)} ~ ${fmtDate(pe)}，超出仍可保存但会标记越界`);
  }
  if (!props.allowFuture) bits.push("不接受晚于今天的日期");
  return bits.join("；");
});

watch(panelOpen, (open) => {
  if (open) {
    mode.value = "calendar";
    manualText.value = props.text;
  }
});

/** 提交前的本地校验，通过则 emit commit，由父组件走既有保存逻辑 */
function commit(v: string) {
  const value = v.trim();
  // 边界一：与原时间相同 —— 不发请求，直接收起面板
  if (value === isoText(props.iso)) {
    panelOpen.value = false;
    return;
  }
  const d = parseStandard(value);
  // 边界二：未来时间（计划分区 allowFuture=true 直接放行）
  if (d && !props.allowFuture && d.getTime() > Date.now()) {
    ElMessage.warning("不能选择晚于当前时刻的时间");
    return;
  }
  // 边界三：越界 —— 与服务端一致只提示不阻断（跨周任务确实存在）
  if (
    d &&
    periodStartDate.value &&
    periodEndDate.value &&
    (d.getTime() < periodStartDate.value.getTime() || d.getTime() > periodEndDate.value.getTime())
  ) {
    ElMessage.warning("该时间不在本周期内，已保存并标记「越界」");
  }
  emit("commit", value);
  panelOpen.value = false;
}

/** 输入框失焦：仅在面板未打开时提交，避免与面板内的「确定」重复提交 */
function onInputBlur() {
  if (panelOpen.value) return;
  commit(props.text);
}

function onCalendarChange(v: string | null) {
  if (!v) return;
  emit("update:text", v);
  commit(v);
}

function applyManual() {
  const v = manualText.value.trim();
  emit("update:text", v);
  commit(v);
}

function clearField() {
  emit("update:text", "");
  commit("");
}
</script>

<template>
  <el-popover
    v-model:visible="panelOpen"
    trigger="click"
    placement="bottom-start"
    popper-class="tf-popper"
  >
    <template #reference>
      <div class="tf-ref">
        <el-input
          :model-value="text"
          size="small"
          :placeholder="placeholder"
          :class="{ 'cell-err': invalid }"
          @update:model-value="(v: string) => emit('update:text', v)"
          @blur="onInputBlur"
          @keyup.enter="commit(text)"
        >
          <template #suffix>
            <span class="tf-cal" :class="{ 'is-open': panelOpen }" title="日历选择">
              <OOIcon name="calendar" :size="14" />
            </span>
          </template>
        </el-input>
      </div>
    </template>

    <div class="tf-panel" @click.stop @mousedown.stop @pointerdown.stop>
      <div class="tf-modes" role="tablist">
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'calendar'"
          :class="{ on: mode === 'calendar' }"
          @click="mode = 'calendar'"
        >
          日历选择
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'manual'"
          :class="{ on: mode === 'manual' }"
          @click="mode = 'manual'"
        >
          手动输入
        </button>
      </div>

      <div v-if="mode === 'calendar'" class="tf-body">
        <el-date-picker
          v-model="calendarValue"
          type="datetime"
          format="YYYY-MM-DD HH:mm"
          value-format="YYYY-MM-DD HH:mm"
          :clearable="false"
          :disabled-date="disabledDate"
          :teleported="false"
          :placeholder="text || '选择日期与时间'"
          @change="onCalendarChange"
        />
        <el-button link type="primary" size="small" class="tf-clear" @click="clearField">
          清空该时间
        </el-button>
      </div>

      <div v-else class="tf-body">
        <el-input
          v-model="manualText"
          size="small"
          placeholder="如：周四 10:00 / 10月9日 15:30 / 261012"
          @keyup.enter="applyManual"
        />
        <div class="tf-acts">
          <el-button size="small" @click="panelOpen = false">取消</el-button>
          <el-button size="small" type="primary" @click="applyManual">确定</el-button>
        </div>
      </div>

      <p class="tf-hint">{{ hint }}</p>
    </div>
  </el-popover>
</template>

<style scoped>
.tf-ref {
  width: 100%;
}

.tf-cal {
  display: inline-flex;
  align-items: center;
  color: var(--oo-text-placeholder);
  cursor: pointer;
  transition: color var(--oo-dur-base) var(--oo-ease-out);
}

.tf-cal:hover,
.tf-cal.is-open {
  color: var(--oo-text-brand);
}

.tf-panel {
  width: 296px;
  max-width: calc(100vw - 48px);
  padding: var(--oo-space-1);
}

/* —— 模式切换 —— */
.tf-modes {
  display: flex;
  gap: var(--oo-space-1);
  margin-bottom: var(--oo-space-2);
  padding: 3px;
  border-radius: var(--oo-radius-sm);
  background: var(--oo-bg-surface-2);
}

.tf-modes button {
  flex: 1;
  padding: var(--oo-space-1) 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-secondary);
  background: none;
  border: none;
  border-radius: var(--oo-radius-xs);
  cursor: pointer;
  transition:
    background var(--oo-dur-base) var(--oo-ease-out),
    color var(--oo-dur-base) var(--oo-ease-out);
}

.tf-modes button:hover:not(.on) {
  background: var(--oo-bg-hover);
  color: var(--oo-text-primary);
}

.tf-modes button.on {
  color: var(--oo-brand-on);
  background: var(--oo-gradient-brand);
  box-shadow: var(--oo-shadow-brand);
}

.tf-body {
  display: flex;
  flex-direction: column;
  gap: var(--oo-space-2);
  align-items: flex-start;
}

.tf-body :deep(.el-date-editor) {
  width: 100%;
}

.tf-clear {
  align-self: flex-start;
  padding: 0;
  height: auto;
}

.tf-acts {
  display: flex;
  justify-content: flex-end;
  gap: var(--oo-space-2);
  width: 100%;
}

.tf-hint {
  margin: var(--oo-space-2) 0 0;
  font-size: var(--oo-text-xs);
  line-height: var(--oo-line-relaxed);
  color: var(--oo-text-tertiary);
}

/* 解析失败标红：与原行内输入框的 cell-err 视觉保持一致 */
.cell-err :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--oo-danger) inset;
}
</style>
