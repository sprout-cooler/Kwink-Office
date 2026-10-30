<script setup lang="ts">
// 周报模块 D 层面板：按 C 层 Tab 渲染对应内容。
// M2：任务上传 ｜ M3：识别校对 / 工作汇总 / 手工补充 ｜ M4：预览与导出
import { computed } from "vue";
import { OOEmptyState } from "@/components/ui";
import UploadTab from "./UploadTab.vue";
import ReviewTab from "./ReviewTab.vue";
import SummaryTab from "./SummaryTab.vue";
import ManualTab from "./ManualTab.vue";
import ExportTab from "./ExportTab.vue";
import MergeTab from "./MergeTab.vue";

const props = defineProps<{ tab: string }>();

/** Tab id → 面板组件（与服务端模块注册表的 tab id 一致） */
const PANELS: Record<string, unknown> = {
  upload: UploadTab,
  review: ReviewTab,
  summary: SummaryTab,
  manual: ManualTab,
  export: ExportTab,
  merge: MergeTab,
};

const activePanel = computed(() => PANELS[props.tab] ?? null);
</script>

<template>
  <div class="weekly-panel">
    <component :is="activePanel" v-if="activePanel" />
    <OOEmptyState
      v-else
      variant="folder"
      title="该功能暂不可用"
      description="当前周报功能正在建设，请稍后再试或切换到其它功能页"
    />
  </div>
</template>

<style scoped>
.weekly-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  animation: oo-fade-up var(--oo-dur-slow) var(--oo-ease-out) both;
}
</style>
