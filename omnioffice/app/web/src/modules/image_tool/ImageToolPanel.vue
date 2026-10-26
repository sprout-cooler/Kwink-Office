<script setup lang="ts">
// 图片处理模块 D 层面板：按 C 层 Tab 渲染。
// Tab 顺序与后端 modules/registry.py 的登记一致：转换 / 拼接 / 压缩 / 识别 / 编辑 / 图库。
import ConvertTab from "./ConvertTab.vue";
import StitchTab from "./StitchTab.vue";
import CompressTab from "./CompressTab.vue";
import OcrTab from "./OcrTab.vue";
import EditTab from "./EditTab.vue";
import GalleryTab from "./GalleryTab.vue";
import { OOEmptyState } from "@/components/ui";

defineProps<{ tab: string }>();
</script>

<template>
  <div class="image-panel">
    <ConvertTab v-if="tab === 'convert'" />
    <StitchTab v-else-if="tab === 'stitch'" />
    <CompressTab v-else-if="tab === 'compress'" />
    <OcrTab v-else-if="tab === 'ocr'" />
    <EditTab v-else-if="tab === 'edit'" />
    <GalleryTab v-else-if="tab === 'gallery'" />
    <OOEmptyState
      v-else
      variant="folder"
      title="该功能开发中"
      description="图片处理模块的这一项还在建设中，敬请期待"
    />
  </div>
</template>

<style scoped>
/* 外层留白与滚动统一交给壳层（.oo-panel），这里不再叠加内边距与二次滚动 */
.image-panel {
  display: flex;
  flex-direction: column;
}
</style>
