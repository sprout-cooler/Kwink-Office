<script setup lang="ts">
/** 图片拼接 Tab：水平 / 垂直 / 网格，支持间距、背景色、列数、统一尺寸。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOSectionTitle, OOToolbar } from "@/components/ui";

const caps = ref<Capabilities | null>(null);
const ids = ref<number[]>([]);
const mode = ref("horizontal");
const gap = ref(0);
const background = ref("#ffffff");
const columns = ref(2);
const uniform = ref(true);
const targetFormat = ref("PNG");
const busy = ref(false);
const result = ref<ImageAssetDto | null>(null);
const picker = ref<InstanceType<typeof ImagePicker> | null>(null);

const isGrid = computed(() => mode.value === "grid");

async function run() {
  if (ids.value.length < 2) return ElMessage.warning("拼接至少需要 2 张图片");
  busy.value = true;
  try {
    result.value = await imageApi.stitch({
      assetIds: ids.value,
      mode: mode.value,
      gap: gap.value,
      background: background.value,
      columns: isGrid.value ? columns.value : undefined,
      uniform: uniform.value,
      targetFormat: targetFormat.value,
    });
    ElMessage.success("拼接完成");
    await picker.value?.refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  try {
    caps.value = await imageApi.capabilities();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
});
</script>

<template>
  <div class="tab">
    <OOPageHeader
      title="图片拼接"
      description="把多张图片按顺序横向、纵向或网格拼成一张长图，间距与背景可自定义"
      badge="🧩"
    />

    <el-alert type="info" :closable="false" class="oo-mb-4">
      拼接按上方「拼接顺序」从左到右（垂直模式下为从上到下）依次排布。尺寸不一致时默认会等比缩放到统一大小，
      避免拼出来参差不齐；取消勾选则各图保持原尺寸、按长边居中对齐。动图暂不支持拼接。
    </el-alert>

    <OOCard flush class="oo-mb-4">
      <ImagePicker
        ref="picker"
        v-model="ids"
        multiple
        label="选择图片（可多选）"
        tips="上传或从图库中挑至少 2 张图片，可用标签上的 ↑ ↓ 调整拼接顺序"
      />
    </OOCard>

    <OOCard flush class="oo-mb-4">
      <OOToolbar>
        <template #left>
          <span class="bar-title">拼接方式</span>
          <el-radio-group v-model="mode" size="small">
            <el-radio-button
              v-for="m in caps?.stitchModes ?? []"
              :key="m.id"
              :value="m.id"
            >
              {{ m.label }}
            </el-radio-button>
          </el-radio-group>
        </template>
        <template #right>
          <span class="count oo-num">已选 {{ ids.length }} 张</span>
          <el-button type="primary" :loading="busy" :disabled="ids.length < 2" @click="run">
            开始拼接
          </el-button>
        </template>
      </OOToolbar>

      <div class="card-pad" v-loading="busy">
        <el-form label-width="96px">
          <el-form-item v-if="isGrid" label="列数">
            <el-input-number
              v-model="columns"
              :min="1"
              :max="caps?.limits.gridMax ?? 20"
              class="oo-field-w oo-field-w-md"
            />
            <span class="num oo-num">列</span>
          </el-form-item>
          <el-form-item label="间距">
            <div class="ctl">
              <el-slider v-model="gap" :min="0" :max="200" class="ctl-slider" />
              <span class="num oo-num">{{ gap }} px</span>
            </div>
          </el-form-item>
          <el-form-item label="背景色">
            <el-color-picker v-model="background" />
            <span class="num oo-num">{{ background }}</span>
          </el-form-item>
          <el-form-item label="输出格式">
            <el-select v-model="targetFormat" class="oo-field-w oo-field-w-md">
              <el-option v-for="f in caps?.outputFormats ?? []" :key="f.id" :label="f.label" :value="f.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="尺寸对齐">
            <el-checkbox v-model="uniform">等比缩放到统一尺寸</el-checkbox>
          </el-form-item>
        </el-form>
      </div>
    </OOCard>

    <OOCard
      title="拼接结果"
      :subtitle="result ? `${result.width}×${result.height} · ${humanSize(result.size)}` : undefined"
    >
      <template #actions>
        <el-button
          v-if="result"
          size="small"
          type="primary"
          plain
          @click="downloadAsset(result)"
        >
          <span class="oo-btn-icon"><OOIcon name="download" :size="14" /></span>
          下载
        </el-button>
      </template>

      <div v-if="result" class="result">
        <div class="result-preview">
          <img :src="assetFileUrl(result.id)" :alt="result.filename" />
        </div>
        <div class="result-info">
          <OOSectionTitle title="输出文件" description="拼接后的新图片已同时保存到「我的图库」" />
          <dl class="meta">
            <div class="meta-row">
              <dt class="meta-key">文件名</dt>
              <dd class="meta-val oo-truncate" :title="result.filename">{{ result.filename }}</dd>
            </div>
            <div class="meta-row">
              <dt class="meta-key">尺寸</dt>
              <dd class="meta-val oo-num">{{ result.width }}×{{ result.height }}</dd>
            </div>
            <div class="meta-row">
              <dt class="meta-key">体积</dt>
              <dd class="meta-val oo-num">{{ humanSize(result.size) }}</dd>
            </div>
            <div class="meta-row">
              <dt class="meta-key">排布</dt>
              <dd class="meta-val oo-num">{{ result.meta.columns }} 列 × {{ result.meta.rows }} 行</dd>
            </div>
            <div class="meta-row">
              <dt class="meta-key">间距</dt>
              <dd class="meta-val oo-num">{{ result.meta.gap }} px</dd>
            </div>
          </dl>
        </div>
      </div>

      <OOEmptyState
        v-else
        variant="inbox"
        title="还没有拼接结果"
        description="选好至少 2 张图片与拼接方式后点击「开始拼接」，结果会显示在这里"
      />
    </OOCard>
  </div>
</template>

<style scoped>
.tab {
  max-width: 960px;
}

.oo-btn-icon {
  display: inline-flex;
  align-items: center;
  vertical-align: -2px;
  margin-right: 4px;
}

/* —— 工具条 —— */
.bar-title {
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
}

.count {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.card-pad {
  padding: var(--oo-space-4) var(--oo-space-5) var(--oo-space-5);
}

/* —— 参数控件 —— */
.ctl {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  width: 100%;
  max-width: 420px;
}

.ctl-slider {
  flex: 1;
  min-width: 0;
}

.num {
  min-width: 40px;
  font-size: var(--oo-text-sm);
  color: var(--oo-text-secondary);
}

/* —— 结果 —— */
.result {
  display: grid;
  grid-template-columns: minmax(0, 380px) minmax(0, 1fr);
  gap: var(--oo-space-5);
  align-items: start;
}

.result-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--oo-space-3);
  border-radius: var(--oo-radius-md);
  border: 1px solid var(--oo-border-subtle);
  /* 透明棋盘格底 */
  background-color: var(--oo-bg-surface-3);
  background-image: linear-gradient(45deg, var(--oo-bg-surface-2) 25%, transparent 25%, transparent 75%, var(--oo-bg-surface-2) 75%),
    linear-gradient(45deg, var(--oo-bg-surface-2) 25%, transparent 25%, transparent 75%, var(--oo-bg-surface-2) 75%);
  background-size: 16px 16px;
  background-position: 0 0, 8px 8px;
}

.result-preview img {
  max-width: 100%;
  max-height: 300px;
  object-fit: contain;
  border-radius: var(--oo-radius-xs);
}

.result-info {
  display: flex;
  flex-direction: column;
  gap: var(--oo-space-3);
  min-width: 0;
}

.meta {
  margin: 0;
  display: flex;
  flex-direction: column;
}

.meta-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--oo-space-4);
  padding: var(--oo-space-2) 0;
  border-bottom: 1px solid var(--oo-border-subtle);
}

.meta-row:last-child {
  border-bottom: none;
}

.meta-key {
  font-size: var(--oo-text-sm);
  color: var(--oo-text-secondary);
  flex-shrink: 0;
}

.meta-val {
  margin: 0;
  font-size: var(--oo-text-sm);
  color: var(--oo-text-primary);
  text-align: right;
  min-width: 0;
}

/* —— 窄屏 —— */
@media (max-width: 768px) {
  .result {
    grid-template-columns: 1fr;
    gap: var(--oo-space-4);
  }
}

@media (max-width: 560px) {
  .tab {
    max-width: 100%;
  }
  .card-pad {
    padding: var(--oo-space-3) var(--oo-space-4) var(--oo-space-4);
  }
  .ctl {
    flex-wrap: wrap;
  }
  .ctl-slider {
    flex-basis: 100%;
  }
}
</style>
