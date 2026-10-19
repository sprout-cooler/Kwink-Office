<script setup lang="ts">
/** 图片编辑 Tab：缩放 / 旋转 / 裁剪 / 文字水印。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";

const caps = ref<Capabilities | null>(null);
const ids = ref<number[]>([]);
const op = ref("resize");
const width = ref(800);
const height = ref<number | undefined>(undefined);
const angle = ref(90);
const cropRatio = ref("1:1");
const text = ref("");
const position = ref("bottom-right");
const opacity = ref(50);
const fontSize = ref<number | undefined>(undefined);
const targetFormat = ref("");
const busy = ref(false);
const result = ref<ImageAssetDto | null>(null);
const picker = ref<InstanceType<typeof ImagePicker> | null>(null);

const positions = computed(
  () =>
    [
      { value: "top-left", label: "左上" }, { value: "top", label: "上中" },
      { value: "top-right", label: "右上" }, { value: "left", label: "左中" },
      { value: "center", label: "正中" }, { value: "right", label: "右中" },
      { value: "bottom-left", label: "左下" }, { value: "bottom", label: "下中" },
      { value: "bottom-right", label: "右下" },
    ] as { value: string; label: string }[],
);

async function run() {
  if (!ids.value.length) return ElMessage.warning("请先选择图片");
  if (op.value === "watermark" && !text.value.trim()) return ElMessage.warning("请输入水印文字");
  busy.value = true;
  try {
    const body: Record<string, unknown> = { op: op.value };
    if (targetFormat.value) body.targetFormat = targetFormat.value;
    if (op.value === "resize") {
      body.width = width.value;
      if (height.value) body.height = height.value;
    } else if (op.value === "rotate") {
      body.angle = angle.value;
    } else if (op.value === "crop") {
      body.cropRatio = cropRatio.value;
    } else {
      body.text = text.value;
      body.position = position.value;
      body.opacity = opacity.value;
      if (fontSize.value) body.fontSize = fontSize.value;
    }
    result.value = await imageApi.transform(ids.value[0], body);
    ElMessage.success("处理完成");
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
    <ImagePicker ref="picker" v-model="ids" tips="选择一张要处理的图片" />

    <el-form label-width="96px" class="form">
      <el-form-item label="操作">
        <el-radio-group v-model="op">
          <el-radio-button v-for="o in caps?.transformOps ?? []" :key="o.id" :value="o.id">
            {{ o.label }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>

      <template v-if="op === 'resize'">
        <el-form-item label="目标宽度">
          <el-input-number v-model="width" :min="1" :max="caps?.limits.maxOutputEdge ?? 20000" style="width: 150px" />
          <span class="num">px（留空高度则等比缩放）</span>
        </el-form-item>
        <el-form-item label="目标高度">
          <el-input-number v-model="height" :min="1" placeholder="可留空" style="width: 150px" />
          <span class="num">同时填宽高时按「填满并居中裁剪」处理</span>
        </el-form-item>
      </template>

      <el-form-item v-else-if="op === 'rotate'" label="旋转角度">
        <el-input-number v-model="angle" :min="-360" :max="360" :step="90" style="width: 150px" />
        <span class="num">非 90 倍数时自动扩展画布，不裁掉四角</span>
      </el-form-item>

      <el-form-item v-else-if="op === 'crop'" label="裁剪比例">
        <el-input v-model="cropRatio" placeholder="16:9" style="width: 150px" />
        <span class="num">居中裁剪，如 1:1 / 16:9 / 4:3</span>
      </el-form-item>

      <template v-else>
        <el-form-item label="水印文字">
          <el-input v-model="text" placeholder="如：内部资料 请勿外传" style="max-width: 320px" />
        </el-form-item>
        <el-form-item label="位置">
          <el-select v-model="position" style="width: 120px">
            <el-option v-for="p in positions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="不透明度">
          <el-slider v-model="opacity" :min="1" :max="100" style="max-width: 240px" />
          <span class="num">{{ opacity }}%</span>
        </el-form-item>
        <el-form-item label="字号">
          <el-input-number v-model="fontSize" :min="10" :max="200" placeholder="自动" style="width: 140px" />
        </el-form-item>
      </template>

      <el-form-item label="输出格式">
        <el-select v-model="targetFormat" clearable placeholder="保持原格式" style="width: 170px">
          <el-option v-for="f in caps?.outputFormats ?? []" :key="f.id" :label="f.label" :value="f.id" />
        </el-select>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">应用</el-button>
      </el-form-item>
    </el-form>

    <div v-if="result" class="result">
      <img :src="assetFileUrl(result.id)" :alt="result.filename" />
      <div class="result-info">
        <div><strong>{{ result.filename }}</strong></div>
        <div>{{ result.width }}×{{ result.height }} · {{ humanSize(result.size) }}</div>
        <el-button size="small" type="primary" plain @click="downloadAsset(result)">下载</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tab {
  max-width: 860px;
}
.form {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-tertiary, #ebeef5);
}
.num {
  margin-left: 12px;
  font-size: 12px;
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
  max-width: 240px;
  max-height: 180px;
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
