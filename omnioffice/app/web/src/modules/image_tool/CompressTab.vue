<script setup lang="ts">
/** 图片压缩 Tab：质量因子模式与目标体积模式（含二分搜索是否达标的如实回报）。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";

const caps = ref<Capabilities | null>(null);
const ids = ref<number[]>([]);
const mode = ref<"quality" | "target">("quality");
const quality = ref(75);
const targetKib = ref(200);
const targetFormat = ref("");
const keepFormat = ref(true);
const busy = ref(false);
const result = ref<ImageAssetDto | null>(null);
const picker = ref<InstanceType<typeof ImagePicker> | null>(null);

const source = computed(() => pickerList.value.find((i) => i.id === ids.value[0]));
const pickerList = ref<ImageAssetDto[]>([]);

/** 压缩结果回报：达标与否、体积变化、是否反而变大 */
const verdict = computed(() => {
  const m = (result.value?.meta ?? {}) as Record<string, unknown>;
  const reached = m.reachedTarget as boolean | undefined;
  const larger = m.largerThanSource as boolean | undefined;
  const hint = m.hint as string | undefined;
  const original = (m.originalSize as number) ?? 0;
  const compressed = (m.compressedSize as number) ?? result.value?.size ?? 0;
  const ratio = (m.savedRatio as number) ?? 0;
  if (!result.value) return null;
  return { reached, larger, hint, original, compressed, ratio };
});

async function run() {
  if (!ids.value.length) return ElMessage.warning("请先选择图片");
  busy.value = true;
  try {
    result.value = await imageApi.compress(ids.value[0], {
      quality: mode.value === "quality" ? quality.value : undefined,
      targetBytes: mode.value === "target" ? targetKib.value * 1024 : undefined,
      targetFormat: targetFormat.value || undefined,
      keepFormat: targetFormat.value ? false : keepFormat.value,
    });
    const v = verdict.value;
    if (v?.larger) ElMessage.warning(v.hint ?? "压缩后体积未减小");
    else if (mode.value === "target" && v?.reached === false) ElMessage.warning(v?.hint ?? "未达到目标体积");
    else ElMessage.success("压缩完成");
    await picker.value?.refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

async function loadForCompare() {
  if (!ids.value.length) {
    pickerList.value = [];
    return;
  }
  try {
    const r = await imageApi.list();
    pickerList.value = r.items;
  } catch {
    pickerList.value = [];
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
      压缩会生成新图片并保留原图。<strong>目标体积模式</strong>会二分搜索质量因子，尽量贴近目标大小；
      若图片本身已高度压缩（如纯色截图），压不动时会如实告知，而不是给你一个更大的文件。
    </el-alert>

    <ImagePicker ref="picker" v-model="ids" @update:model-value="loadForCompare" tips="选择一张要压缩的图片" />

    <el-form label-width="96px" class="form">
      <el-form-item label="压缩方式">
        <el-radio-group v-model="mode">
          <el-radio-button value="quality">质量因子</el-radio-button>
          <el-radio-button value="target">目标体积</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="mode === 'quality'" label="质量因子">
        <el-slider
          v-model="quality"
          :min="caps?.quality.min ?? 1"
          :max="caps?.quality.max ?? 100"
          style="max-width: 300px"
        />
        <span class="num">{{ quality }}</span>
      </el-form-item>
      <el-form-item v-else label="目标体积">
        <el-input-number v-model="targetKib" :min="1" :max="102400" :step="10" style="width: 160px" />
        <span class="num">KB</span>
      </el-form-item>
      <el-form-item label="输出格式">
        <el-select v-model="targetFormat" clearable placeholder="保持原格式" style="width: 180px">
          <el-option v-for="f in caps?.outputFormats ?? []" :key="f.id" :label="f.label" :value="f.id" />
        </el-select>
        <span v-if="!targetFormat" class="num">
          保持原格式{{ keepFormat ? "（纯压缩，不换格式）" : "（回退 JPEG）" }}
        </span>
      </el-form-item>
      <el-form-item v-if="!targetFormat && mode === 'quality'">
        <el-checkbox v-model="keepFormat">保持原格式（取消则转为 JPEG，压缩率更高）</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">开始压缩</el-button>
        <span v-if="source" class="num">原图 {{ humanSize(source.size) }}</span>
      </el-form-item>
    </el-form>

    <div v-if="result && verdict" class="result">
      <img :src="assetFileUrl(result.id)" :alt="result.filename" />
      <div class="result-info">
        <div><strong>{{ result.filename }}</strong></div>
        <div>{{ result.width }}×{{ result.height }}</div>
        <div class="sizes">
          <span class="old">{{ humanSize(verdict.original) }}</span>
          <span class="arrow">→</span>
          <span class="new">{{ humanSize(verdict.compressed) }}</span>
          <el-tag
            v-if="verdict.ratio > 0"
            type="success"
            size="small"
          >体积减少 {{ verdict.ratio }}%</el-tag>
          <el-tag v-else-if="verdict.ratio < 0" type="warning" size="small">
            反而增大 {{ Math.abs(verdict.ratio) }}%
          </el-tag>
        </div>
        <el-tag v-if="mode === 'target' && verdict.reached === false" type="warning" size="small">
          未达到目标体积
        </el-tag>
        <p v-if="verdict.hint" class="hint-text">{{ verdict.hint }}</p>
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
.sizes {
  display: flex;
  align-items: center;
  gap: 8px;
}
.old {
  color: #909399;
  text-decoration: line-through;
}
.new {
  font-weight: 500;
  color: #303133;
}
.arrow {
  color: #c0c4cc;
}
.hint-text {
  margin: 0;
  max-width: 340px;
  font-size: 12px;
  line-height: 1.6;
  color: #e6a23c;
}
</style>
