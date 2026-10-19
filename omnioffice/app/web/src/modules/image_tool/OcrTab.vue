<script setup lang="ts">
/** 图片 OCR Tab：提取整图文字 + 每块文字的位置，点击文字块在图上高亮。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, type OcrBlock, type OcrResult } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";

const ids = ref<number[]>([]);
const busy = ref(false);
const result = ref<OcrResult | null>(null);
const active = ref<number>(-1);

const picker = ref<InstanceType<typeof ImagePicker> | null>(null);

/** 预览尺寸：与 img 渲染宽度一致才能让 box 百分比定位准确 */
const previewW = ref(0);
const previewEl = ref<HTMLImageElement | null>(null);

const blocks = computed<OcrBlock[]>(() => result.value?.blocks ?? []);

function boxStyle(b: OcrBlock): Record<string, string> {
  const [l, t, r, d] = b.box;
  return {
    left: `${l / 10}%`,
    top: `${t / 10}%`,
    width: `${(r - l) / 10}%`,
    height: `${Math.max((d - t) / 10, 1.6)}%`,
  };
}

async function run() {
  if (!ids.value.length) return ElMessage.warning("请先选择图片");
  busy.value = true;
  active.value = -1;
  try {
    result.value = await imageApi.ocr(ids.value[0]);
    if (!result.value.blocks.length) ElMessage.info("未识别到文字");
    else ElMessage.success(`识别到 ${result.value.blocks.length} 块文字`);
    await picker.value?.refresh();
  } catch (e) {
    // AI 未配置是最常见的情况，给明确引导而不是只弹错误
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("AI Key") || msg.includes("大模型")) {
      ElMessage.warning(msg);
    } else {
      ElMessage.error(msg);
    }
  } finally {
    busy.value = false;
  }
}

async function copyText() {
  const text = result.value?.text ?? "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制全部文字");
  } catch {
    // 非安全上下文（HTTP + 局域网）禁用 clipboard API（平台约束），退回提示
    ElMessage.warning("当前环境不支持一键复制，请手动选中文本复制");
  }
}

function onImgLoad(e: Event) {
  previewW.value = (e.target as HTMLImageElement).clientWidth;
}

onMounted(() => {
  previewEl.value = null;
});
</script>

<template>
  <div class="tab">
    <el-alert type="info" :closable="false" class="hint">
      文字识别复用本应用已配置的 AI 模型。可在「设置 → AI 模型 → 图片处理」中为本模块单独指定
      <strong>qwen3.5-ocr</strong>（文字提取专项）。位置坐标为模型按千分比给出的近似框，用于点选高亮，
      非像素级精确。
    </el-alert>

    <ImagePicker ref="picker" v-model="ids" tips="选择一张含文字的图片" />

    <el-form class="form">
      <el-form-item>
        <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">开始识别</el-button>
        <el-button v-if="result?.text" @click="copyText">复制全文</el-button>
      </el-form-item>
    </el-form>

    <div v-if="result" class="result">
      <div class="preview">
        <img
          ref="previewEl"
          :src="assetFileUrl(ids[0])"
          alt="待识别图片"
          @load="onImgLoad"
        />
        <div
          v-for="(b, i) in blocks"
          :key="i"
          class="box"
          :class="{ active: active === i }"
          :style="boxStyle(b)"
          @click="active = i"
        />
      </div>
      <div class="text-side">
        <div class="text-head">
          <span>识别结果（{{ blocks.length }} 块 / {{ result.text.length }} 字）</span>
        </div>
        <el-input
          :model-value="result.text"
          type="textarea"
          :rows="14"
          readonly
          resize="none"
        />
        <div v-if="active >= 0" class="block-detail">
          <div class="block-meta">
            置信度 {{ (blocks[active].confidence * 100).toFixed(0) }}% ·
            位置 [{{ blocks[active].box.join(", ") }}]
          </div>
          <p class="block-text">{{ blocks[active].text }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tab {
  max-width: 960px;
}
.hint {
  margin-bottom: 14px;
}
.form {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-tertiary, #ebeef5);
}
.result {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  margin-top: 16px;
}
@media (max-width: 900px) {
  .result {
    grid-template-columns: 1fr;
  }
}
.preview {
  position: relative;
  display: inline-block;
  max-width: 100%;
  border: 1px solid var(--color-border-tertiary, #ebeef5);
  border-radius: 8px;
  overflow: hidden;
  background: #f5f7fa;
}
.preview img {
  display: block;
  max-width: 100%;
  height: auto;
}
.box {
  position: absolute;
  border: 1.5px solid rgba(64, 158, 255, 0.55);
  background: rgba(64, 158, 255, 0.1);
  border-radius: 2px;
  cursor: pointer;
}
.box.active {
  border-color: #e6a23c;
  background: rgba(230, 162, 60, 0.18);
}
.text-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.text-head {
  font-size: 13px;
  color: #606266;
}
.block-detail {
  padding: 10px;
  border: 1px solid var(--color-border-tertiary, #ebeef5);
  border-radius: 6px;
  background: var(--color-background-secondary, #fafafa);
}
.block-meta {
  font-size: 12px;
  color: #909399;
}
.block-text {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
}
</style>
