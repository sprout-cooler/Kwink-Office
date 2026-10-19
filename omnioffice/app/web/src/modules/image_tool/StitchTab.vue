<script setup lang="ts">
/** 图片拼接 Tab：水平 / 垂直 / 网格，支持间距、背景色、列数、统一尺寸。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";

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
    <el-alert type="info" :closable="false" class="hint">
      拼接按上方「拼接顺序」从左到右（垂直模式下为从上到下）依次排布。尺寸不一致时默认会等比缩放到统一大小，
      避免拼出来参差不齐；取消勾选则各图保持原尺寸、按长边居中对齐。动图暂不支持拼接。
    </el-alert>

    <ImagePicker ref="picker" v-model="ids" multiple label="选择图片（可多选）" />

    <el-form label-width="96px" class="form">
      <el-form-item label="拼接方式">
        <el-radio-group v-model="mode">
          <el-radio-button
            v-for="m in caps?.stitchModes ?? []"
            :key="m.id"
            :value="m.id"
          >
            {{ m.label }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="isGrid" label="列数">
        <el-input-number
          v-model="columns"
          :min="1"
          :max="caps?.limits.gridMax ?? 20"
          style="width: 140px"
        />
      </el-form-item>
      <el-form-item label="间距">
        <el-slider v-model="gap" :min="0" :max="200" style="max-width: 280px" />
        <span class="num">{{ gap }} px</span>
      </el-form-item>
      <el-form-item label="背景色">
        <el-color-picker v-model="background" />
        <span class="num">{{ background }}</span>
      </el-form-item>
      <el-form-item label="输出格式">
        <el-select v-model="targetFormat" style="width: 140px">
          <el-option v-for="f in caps?.outputFormats ?? []" :key="f.id" :label="f.label" :value="f.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="尺寸对齐">
        <el-checkbox v-model="uniform">等比缩放到统一尺寸</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="busy" :disabled="ids.length < 2" @click="run">
          开始拼接
        </el-button>
        <span class="num">已选 {{ ids.length }} 张</span>
      </el-form-item>
    </el-form>

    <div v-if="result" class="result">
      <img :src="assetFileUrl(result.id)" :alt="result.filename" />
      <div class="result-info">
        <div><strong>{{ result.filename }}</strong></div>
        <div>{{ result.width }}×{{ result.height }} · {{ humanSize(result.size) }}</div>
        <div class="meta">{{ result.meta.columns }} 列 × {{ result.meta.rows }} 行 · 间距 {{ result.meta.gap }}px</div>
        <el-button size="small" type="primary" plain @click="downloadAsset(result)">下载</el-button>
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
.num {
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
  max-width: 320px;
  max-height: 220px;
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
.meta {
  font-size: 12px;
  color: #909399;
}
</style>
