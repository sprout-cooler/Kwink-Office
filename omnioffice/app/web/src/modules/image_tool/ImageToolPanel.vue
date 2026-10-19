<script setup lang="ts">
// 图片处理模块 D 层面板：按 C 层 Tab 渲染。
// Tab 顺序与后端 modules/registry.py 的登记一致：转换 / 拼接 / 压缩 / 识别 / 编辑 / 图库。
import ConvertTab from "./ConvertTab.vue";
import StitchTab from "./StitchTab.vue";
import CompressTab from "./CompressTab.vue";
import OcrTab from "./OcrTab.vue";
import EditTab from "./EditTab.vue";
import GalleryTab from "./GalleryTab.vue";

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
    <el-empty v-else description="该功能开发中" />
  </div>
</template>

<style scoped>
.image-panel {
  padding: 16px 18px 32px;
  overflow-y: auto;
  height: 100%;
}
</style>
