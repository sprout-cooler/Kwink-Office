<script setup lang="ts">
/** 格式转换 Tab：PNG/JPEG/WEBP/GIF/BMP/TIFF 互转，支持质量与透明度说明。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";

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
    <el-alert type="info" :closable="false" class="hint">
      转换会生成<strong>新图片</strong>并保留原图。手机照片的横竖方向会自动摆正；勾选「剥离 EXIF」可移除 GPS
      坐标、机型、拍摄时间等隐私信息（外发图片建议保持勾选）。
    </el-alert>

    <ImagePicker ref="picker" v-model="ids" tips="选择一张要转换的图片" />

    <el-form label-width="96px" class="form">
      <el-form-item label="目标格式">
        <el-radio-group v-model="targetFormat">
          <el-radio-button v-for="f in caps?.outputFormats ?? []" :key="f.id" :value="f.id">
            {{ f.label }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="!targetSupportsAlpha" label="透明区域">
        <el-tag type="warning" size="small">
          {{ targetFormat }} 不支持透明通道，透明处会填充为白色
        </el-tag>
      </el-form-item>
      <el-form-item label="质量">
        <el-slider
          v-model="quality"
          :min="caps?.quality.min ?? 1"
          :max="caps?.quality.max ?? 100"
          style="max-width: 320px"
        />
        <span class="quality-num">{{ quality }}</span>
      </el-form-item>
      <el-form-item label="隐私">
        <el-checkbox v-model="dropExif">剥离 EXIF 信息（含 GPS 定位）</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">
          开始转换
        </el-button>
      </el-form-item>
    </el-form>

    <div v-if="result" class="result">
      <img :src="assetFileUrl(result.id)" :alt="result.filename" />
      <div class="result-info">
        <div><strong>{{ result.filename }}</strong></div>
        <div>{{ result.width }}×{{ result.height }} · {{ humanSize(result.size) }}</div>
        <el-button size="small" type="primary" plain @click="download(result)">下载</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tab {
  max-width: 860px;
}
.hint {
  margin-bottom: 14px;
}
.form {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-tertiary, #ebeef5);
}
.quality-num {
  margin-left: 12px;
  font-size: 13px;
  color: #909399;
}
.result {
  display: flex;
  gap: 16px;
  margin-top: 16px;
  padding: 12px;
  border: 1px solid var(--color-border-tertiary, #ebeef5);
  border-radius: 8px;
}
.result img {
  max-width: 220px;
  max-height: 160px;
  object-fit: contain;
  background: #f5f7fa;
  border-radius: 6px;
}
.result-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  font-size: 13px;
  color: #606266;
}
</style>
