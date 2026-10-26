<script setup lang="ts">
/** 格式转换 Tab：PNG/JPEG/WEBP/GIF/BMP/TIFF 互转，支持质量与透明度说明。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOSectionTitle, OOToolbar } from "@/components/ui";

const caps = ref<Capabilities | null>(null);
const ids = ref<number[]>([]);
const targetFormat = ref("WEBP");
const quality = ref(85);
const dropExif = ref(true);
const busy = ref(false);
const result = ref<ImageAssetDto | null>(null);
const picker = ref<InstanceType<typeof ImagePicker> | null>(null);

const source = computed(() => caps.value?.inputFormats.length ? caps.value : null);

/** 目标格式是否支持透明度：JPEG/BMP 不支持，转过去透明区会被合成到白底 */
const targetSupportsAlpha = computed(
  () => caps.value?.outputFormats.find((f) => f.id === targetFormat.value)?.alpha ?? false,
);

async function run() {
  if (!ids.value.length) return ElMessage.warning("请先选择图片");
  busy.value = true;
  try {
    result.value = await imageApi.convert(ids.value[0], {
      targetFormat: targetFormat.value,
      quality: quality.value,
      dropExif: dropExif.value,
    });
    ElMessage.success("转换完成");
    await picker.value?.refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

/** 触发浏览器下载：用 <a download> 而非 window.open（后者会被网关当页面导航） */
function download(a: ImageAssetDto) {
  downloadAsset(a);
}

onMounted(async () => {
  try {
    caps.value = await imageApi.capabilities();
    targetFormat.value = "WEBP";
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
});
</script>

<template>
  <div class="tab">
    <OOPageHeader
      title="格式转换"
      description="在 PNG / JPEG / WEBP / GIF / BMP / TIFF 之间互转，可控质量并顺手清理隐私信息"
      badge="🖼"
    />

    <el-alert type="info" :closable="false" class="oo-mb-4">
      转换会生成<strong>新图片</strong>并保留原图。手机照片的横竖方向会自动摆正；勾选「剥离 EXIF」可移除 GPS
      坐标、机型、拍摄时间等隐私信息（外发图片建议保持勾选）。
    </el-alert>

    <OOCard flush class="oo-mb-4">
      <ImagePicker ref="picker" v-model="ids" tips="上传或从图库中挑一张要转换的原图" />
    </OOCard>

    <OOCard flush class="oo-mb-4">
      <OOToolbar>
        <template #left>
          <span class="bar-title">目标格式</span>
          <el-radio-group v-model="targetFormat" size="small">
            <el-radio-button v-for="f in caps?.outputFormats ?? []" :key="f.id" :value="f.id">
              {{ f.label }}
            </el-radio-button>
          </el-radio-group>
        </template>
        <template #right>
          <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">
            开始转换
          </el-button>
        </template>
      </OOToolbar>

      <div class="card-pad" v-loading="busy">
        <el-form label-width="96px">
          <el-form-item v-if="!targetSupportsAlpha" label="透明区域">
            <el-tag type="warning" size="small">
              {{ targetFormat }} 不支持透明通道，透明处会填充为白色
            </el-tag>
          </el-form-item>
          <el-form-item label="质量">
            <div class="ctl">
              <el-slider
                v-model="quality"
                :min="caps?.quality.min ?? 1"
                :max="caps?.quality.max ?? 100"
                class="ctl-slider"
              />
              <span class="num oo-num">{{ quality }}</span>
            </div>
            <p class="hint-text">数值越高画质越好、文件越大；仅对 JPEG / WEBP 等有损格式生效。</p>
          </el-form-item>
          <el-form-item label="隐私">
            <el-checkbox v-model="dropExif">剥离 EXIF 信息（含 GPS 定位）</el-checkbox>
          </el-form-item>
        </el-form>
      </div>
    </OOCard>

    <OOCard
      title="转换结果"
      :subtitle="result ? `${result.width}×${result.height} · ${humanSize(result.size)}` : undefined"
    >
      <template #actions>
        <el-button
          v-if="result"
          size="small"
          type="primary"
          plain
          @click="download(result)"
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
          <OOSectionTitle title="输出文件" description="转换后的新图片已同时保存到「我的图库」" />
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
              <dt class="meta-key">格式</dt>
              <dd class="meta-val oo-num">{{ targetFormat }}</dd>
            </div>
          </dl>
        </div>
      </div>

      <OOEmptyState
        v-else
        variant="inbox"
        title="还没有转换结果"
        description="选好图片与目标格式后点击「开始转换」，结果会显示在这里"
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
  text-align: right;
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-medium);
  color: var(--oo-text-primary);
}

.hint-text {
  margin-top: 2px;
  font-size: var(--oo-text-xs);
  line-height: var(--oo-line-relaxed);
  color: var(--oo-text-tertiary);
}

/* —— 结果 —— */
.result {
  display: grid;
  grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
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
  max-height: 240px;
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
  .num {
    text-align: left;
  }
}
</style>
