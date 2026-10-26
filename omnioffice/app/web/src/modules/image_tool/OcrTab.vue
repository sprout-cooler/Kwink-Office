<script setup lang="ts">
/** 图片 OCR Tab：提取整图文字 + 每块文字的位置，点击文字块在图上高亮。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, type OcrBlock, type OcrResult } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { OOCard, OOEmptyState, OOPageHeader, OOSectionTitle } from "@/components/ui";

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
    <OOPageHeader
      title="文字识别"
      description="复用已配置的 AI 模型提取图片中的整段文字，并按位置分块高亮定位"
      badge="🔍"
    />

    <el-alert type="info" :closable="false" class="oo-mb-4">
      文字识别复用本应用已配置的 AI 模型。可在「设置 → AI 模型 → 图片处理」中为本模块单独指定
      <strong>qwen3.5-ocr</strong>（文字提取专项）。位置坐标为模型按千分比给出的近似框，用于点选高亮，
      非像素级精确。
    </el-alert>

    <OOCard flush class="oo-mb-4">
      <ImagePicker ref="picker" v-model="ids" tips="上传或从图库中挑一张含文字的图片" />
    </OOCard>

    <OOCard
      title="识别结果"
      :subtitle="result ? `${blocks.length} 块文字 / ${result.text.length} 字` : undefined"
      :loading="busy"
    >
      <template #actions>
        <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">
          开始识别
        </el-button>
        <el-button v-if="result?.text" @click="copyText">复制全文</el-button>
      </template>

      <div v-if="result" class="result">
        <div class="result-side">
          <OOSectionTitle title="原图与文字块" description="点击图片上的方框可查看对应的文字" />
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
        </div>

        <div class="result-divider" aria-hidden="true"></div>

        <div class="result-side">
          <OOSectionTitle title="识别文本" description="全文为模型输出，可在下方手动选中复制" />
          <el-input
            :model-value="result.text"
            type="textarea"
            :rows="14"
            readonly
            resize="none"
          />
          <div v-if="active >= 0" class="block-detail">
            <div class="block-meta oo-num">
              置信度 {{ (blocks[active].confidence * 100).toFixed(0) }}% ·
              位置 [{{ blocks[active].box.join(", ") }}]
            </div>
            <p class="block-text">{{ blocks[active].text }}</p>
          </div>
        </div>
      </div>

      <OOEmptyState
        v-else
        variant="search"
        title="还没有识别结果"
        description="选择一张含文字的图片后点击「开始识别」，文字会按块出现在这里"
      />
    </OOCard>
  </div>
</template>

<style scoped>
.tab {
  max-width: 1080px;
}

/* —— 结果双栏 —— */
.result {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr);
  gap: var(--oo-space-5);
  align-items: start;
}

.result-side {
  display: flex;
  flex-direction: column;
  gap: var(--oo-space-3);
  min-width: 0;
}

.result-divider {
  align-self: stretch;
  background: var(--oo-border-subtle);
}

/* —— 图片预览 —— */
.preview {
  position: relative;
  display: inline-block;
  max-width: 100%;
  border: 1px solid var(--oo-border-subtle);
  border-radius: var(--oo-radius-md);
  overflow: hidden;
  background: var(--oo-bg-surface-3);
}

.preview img {
  display: block;
  max-width: 100%;
  height: auto;
}

.box {
  position: absolute;
  border: 1.5px solid color-mix(in srgb, var(--oo-brand) 55%, transparent);
  background: color-mix(in srgb, var(--oo-brand) 10%, transparent);
  border-radius: var(--oo-radius-xs);
  cursor: pointer;
  transition: background var(--oo-dur-fast) var(--oo-ease-out),
    border-color var(--oo-dur-fast) var(--oo-ease-out);
}

.box:hover {
  border-color: var(--oo-brand);
  background: color-mix(in srgb, var(--oo-brand) 20%, transparent);
}

.box.active {
  border-color: var(--oo-warning);
  background: color-mix(in srgb, var(--oo-warning) 22%, transparent);
}

/* —— 文字块详情 —— */
.block-detail {
  padding: var(--oo-space-3);
  border: 1px solid var(--oo-border-subtle);
  border-radius: var(--oo-radius-md);
  background: var(--oo-bg-surface-2);
}

.block-meta {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.block-text {
  margin: var(--oo-space-2) 0 0;
  font-size: var(--oo-text-sm);
  line-height: var(--oo-line-relaxed);
  color: var(--oo-text-primary);
  white-space: pre-wrap;
}

/* —— 窄屏 —— */
@media (max-width: 900px) {
  .result {
    grid-template-columns: 1fr;
    gap: var(--oo-space-4);
  }
  .result-divider {
    height: 1px;
    width: 100%;
  }
}

@media (max-width: 560px) {
  .tab {
    max-width: 100%;
  }
}
</style>
