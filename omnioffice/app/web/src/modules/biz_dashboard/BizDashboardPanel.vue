<script setup lang="ts">
/** 经营大屏主面板：按模块注册表的 Tab 切换。 */
import { computed, defineAsyncComponent, ref } from "vue";

const props = defineProps<{ tab: string }>();

/** 各 Tab 异步加载：大屏图表较重，首屏不必等全部 chunk。 */
const OverviewTab = defineAsyncComponent(() => import("./OverviewTab.vue"));
const WorkloadTab = defineAsyncComponent(() => import("./WorkloadTab.vue"));
const CustomerTab = defineAsyncComponent(() => import("./CustomerTab.vue"));
const TripTab = defineAsyncComponent(() => import("./TripTab.vue"));
const FinanceTab = defineAsyncComponent(() => import("./FinanceTab.vue"));
const ShareTab = defineAsyncComponent(() => import("./ShareTab.vue"));

const panels: Record<string, unknown> = {
  overview: OverviewTab,
  workload: WorkloadTab,
  customer: CustomerTab,
  trip: TripTab,
  finance: FinanceTab,
  share: ShareTab,
};

const activePanel = computed(() => panels[props.tab] ?? OverviewTab);
</script>

<template>
  <div class="bz-panel">
    <component :is="activePanel" />
  </div>
</template>

<style scoped>
.bz-panel {
  height: 100%;
  overflow: auto;
}
</style>
