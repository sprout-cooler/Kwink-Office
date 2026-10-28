<script setup lang="ts">
/** 财务一级模块面板（v1.0.35）。
 *
 * 从「数据大屏」的一个 Tab 升为独立模块，4 个子页各自按需加载数据：
 * 流水明细（录入与筛选）/ 账单导入 / 趋势分析 / 分类与映射。
 *
 * 异步加载：图表较重，首屏不必等全部 chunk。
 */
import { computed, defineAsyncComponent } from "vue";

const props = defineProps<{ tab: string }>();

const FlowTab = defineAsyncComponent(() => import("./FlowTab.vue"));
const ImportTab = defineAsyncComponent(() => import("./ImportTab.vue"));
const AnalysisTab = defineAsyncComponent(() => import("./AnalysisTab.vue"));
const CategoryTab = defineAsyncComponent(() => import("./CategoryTab.vue"));

const panels: Record<string, unknown> = {
  flows: FlowTab,
  import: ImportTab,
  analysis: AnalysisTab,
  category: CategoryTab,
};

const activePanel = computed(() => panels[props.tab] ?? FlowTab);
</script>

<template>
  <div class="fin-panel">
    <component :is="activePanel" />
  </div>
</template>

<style scoped>
.fin-panel {
  height: 100%;
  overflow: auto;
}
</style>
