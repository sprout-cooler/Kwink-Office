<script setup lang="ts">
// 周报模块 D 层面板：按 C 层 Tab 渲染对应内容。
// M2：任务上传 ｜ M3：识别校对 / 工作汇总 / 手工补充 ｜ M4：预览与导出
import UploadTab from "./UploadTab.vue";
import ReviewTab from "./ReviewTab.vue";
import SummaryTab from "./SummaryTab.vue";
import ManualTab from "./ManualTab.vue";
import ExportTab from "./ExportTab.vue";

defineProps<{ tab: string }>();
</script>

<template>
  <div class="weekly-panel">
    <UploadTab v-if="tab === 'upload'" />
    <ReviewTab v-else-if="tab === 'review'" />
    <SummaryTab v-else-if="tab === 'summary'" />
    <ManualTab v-else-if="tab === 'manual'" />
    <ExportTab v-else-if="tab === 'export'" />
  </div>
</template>
