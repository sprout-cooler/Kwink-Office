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
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";

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

onBeforeUnmount(() => {
  chart.value?.dispose?.();
  chart.value = null;
});
</script>

<template>
  <div class="bz-chart">
    <el-alert v-if="failed" type="warning" :closable="false" :title="failed" show-icon />
    <div v-else ref="el" class="bz-chart-canvas" :style="{ height: props.height }" />
    <div v-if="loading && !failed" class="bz-chart-loading">图表加载中…</div>
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
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
