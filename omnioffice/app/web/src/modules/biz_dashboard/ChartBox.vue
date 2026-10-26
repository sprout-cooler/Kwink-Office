<script setup lang="ts">
/** ECharts 轻量封装：**按需引入** + 异步加载，避免把整个 echarts 打进产物。
 *
 * 为什么必须按需引入：
 * echarts 全量包约 1MB(min)，而当前前端产物已 1.5MB，
 * 全量引入会让 FPK 体积翻倍。按需引入只打包用到的图表类型与组件，
 * 实测通常在 250~400KB 量级。
 *
 * 为什么异步加载：
 * 大屏图表不是首屏必需，用动态 import 把 echarts 拆成独立 chunk，
 * 首屏（总览 KPI）不等待图表 chunk。
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { getChartThemeVersion, onChartThemeChange } from "@/composables/chart-theme";

const props = withDefaults(
  defineProps<{
    /** 图表类型 */
    type: "bar" | "line" | "pie";
    option: Record<string, unknown>;
    height?: string;
  }>(),
  { height: "300px" },
);

const emit = defineEmits<{ (e: "error", msg: string): void }>();

const el = ref<HTMLElement | null>(null);
const chart = shallowRef<any>(null);
const loading = ref(true);
const failed = ref("");

/**
 * 判定 option 是否「无数据」。
 *
 * ECharts 在 series 数据为空时不会报错，只是画出一个空坐标系 /
 * 一个灰白圆环（饼图的 radius 区间），用户看到的是「坏了」而不是「没数据」。
 * 所以这里从 option 里读出所有 series 的数据点，总数为 0 就判定为空。
 */
const isEmpty = computed(() => {
  const opt = props.option as Record<string, any> | undefined;
  const series = opt?.series;
  if (!Array.isArray(series) || series.length === 0) return true;
  return series.every((s: any) => {
    const data = s?.data;
    if (!Array.isArray(data)) return true;
    return data.length === 0;
  });
});

/** 按需注册：只引入实际用到的图表与组件。 */
async function getECharts(): Promise<any> {
  const [echarts, charts, components, renderers] = await Promise.all([
    import("echarts/core"),
    import("echarts/charts"),
    import("echarts/components"),
    import("echarts/renderers"),
  ]);
  const { BarChart, LineChart, PieChart } = charts;
  const { GridComponent, TooltipComponent, LegendComponent, TitleComponent, DatasetComponent } =
    components;
  const { CanvasRenderer } = renderers;

  echarts.use([
    BarChart,
    LineChart,
    PieChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    TitleComponent,
    DatasetComponent,
    CanvasRenderer,
  ]);
  return echarts;
}

function render() {
  if (!chart.value) return;
  chart.value.setOption(props.option, true);
}

onMounted(async () => {
  try {
    const echarts = await getECharts();
    if (!el.value) return;
    chart.value = echarts.init(el.value, undefined, { renderer: "canvas" });
    render();
    loading.value = false;
    // 容器尺寸变化时重绘（侧栏折叠 / 窗口缩放）
    const ro = new ResizeObserver(() => chart.value?.resize());
    ro.observe(el.value);
    onBeforeUnmount(() => ro.disconnect());
  } catch (e) {
    failed.value = e instanceof Error ? e.message : String(e);
    loading.value = false;
    emit("error", failed.value);
  }
});

watch(
  () => props.option,
  () => render(),
  { deep: true },
);

// 主题切换：ECharts 的 option 是 JS 对象，拿不到 CSS 变量，
// 所以主题变化必须触发一次 setOption 重绘才能拿到新配色。
// 这里监听 chart-theme 的版本号；由 useAppStore 之外的全局主题切换触发通知。
let stopThemeWatch: (() => void) | null = null;

onMounted(() => {
  stopThemeWatch = onChartThemeChange(() => render());
});

onBeforeUnmount(() => {
  stopThemeWatch?.();
  chart.value?.dispose?.();
  chart.value = null;
});
</script>

<template>
  <div class="bz-chart">
    <el-alert v-if="failed" type="warning" :closable="false" :title="failed" show-icon />
    <div v-else ref="el" class="bz-chart-canvas" :style="{ height: props.height }" />
    <div v-if="loading && !failed" class="bz-chart-loading">
      <span class="bz-chart-spinner" aria-hidden="true" />
      图表加载中…
    </div>
    <!-- 无数据：ECharts 空 series 会画出一个灰圈（饼图）或空白坐标系，很难看。
         这里盖一层说明，比让人对着空白图猜要好。 -->
    <div v-if="!loading && !failed && isEmpty" class="bz-chart-empty">
      <p class="bz-chart-empty-title">暂无数据</p>
      <p class="bz-chart-empty-desc">录入数据后这里会显示图表</p>
    </div>
  </div>
</template>

<style scoped>
.bz-chart {
  position: relative;
  width: 100%;
}
.bz-chart-canvas {
  width: 100%;
}
.bz-chart-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  background: var(--oo-bg-surface);
}

/* 加载转圈：用 CSS 画，不引图标库 */
.bz-chart-spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--oo-border-default);
  border-top-color: var(--oo-brand);
  animation: oo-spin 700ms linear infinite;
}

/* 无数据盖层 */
.bz-chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: var(--oo-bg-surface);
  pointer-events: none;
}

.bz-chart-empty-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--oo-text-secondary);
}

.bz-chart-empty-desc {
  font-size: 12px;
  color: var(--oo-text-tertiary);
}
</style>
