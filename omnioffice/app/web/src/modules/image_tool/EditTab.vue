<script setup lang="ts">
/** 图片编辑 Tab：缩放 / 旋转 / 裁剪 / 文字水印。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOSectionTitle, OOToolbar } from "@/components/ui";

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
    <OOPageHeader
      title="图片编辑"
      description="缩放、旋转、裁剪或加上文字水印，处理后会生成一张新图片"
      badge="✂️"
    />

    <el-alert type="info" :closable="false" class="oo-mb-4">
      编辑会生成<strong>新图片</strong>并保留原图。缩放与裁剪按目标尺寸处理，旋转非 90 倍数时会自动扩展画布以免裁掉四角；
      水印位置与不透明度可调，大小留空则按图片尺寸自动推算。
    </el-alert>

    <OOCard flush class="oo-mb-4">
      <ImagePicker ref="picker" v-model="ids" tips="上传或从图库中挑一张要处理的原图" />
    </OOCard>

    <OOCard flush class="oo-mb-4">
      <OOToolbar>
        <template #left>
          <span class="bar-title">操作</span>
          <el-radio-group v-model="op" size="small">
            <el-radio-button v-for="o in caps?.transformOps ?? []" :key="o.id" :value="o.id">
              {{ o.label }}
            </el-radio-button>
          </el-radio-group>
        </template>
        <template #right>
          <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">
            应用
          </el-button>
        </template>
      </OOToolbar>

      <div class="card-pad" v-loading="busy">
        <el-form label-width="96px">
          <template v-if="op === 'resize'">
            <el-form-item label="目标宽度">
              <el-input-number v-model="width" :min="1" :max="caps?.limits.maxOutputEdge ?? 20000" class="oo-field-w oo-field-w-md" />
              <span class="num">px（留空高度则等比缩放）</span>
            </el-form-item>
            <el-form-item label="目标高度">
              <el-input-number v-model="height" :min="1" placeholder="可留空" class="oo-field-w oo-field-w-md" />
              <span class="num">同时填宽高时按「填满并居中裁剪」处理</span>
            </el-form-item>
          </template>

          <el-form-item v-else-if="op === 'rotate'" label="旋转角度">
            <el-input-number v-model="angle" :min="-360" :max="360" :step="90" class="oo-field-w oo-field-w-md" />
            <span class="num">非 90 倍数时自动扩展画布，不裁掉四角</span>
          </el-form-item>

          <el-form-item v-else-if="op === 'crop'" label="裁剪比例">
            <el-input v-model="cropRatio" placeholder="16:9" class="oo-field-w oo-field-w-md" />
            <span class="num">居中裁剪，如 1:1 / 16:9 / 4:3</span>
          </el-form-item>

          <template v-else>
            <el-form-item label="水印文字">
              <el-input v-model="text" placeholder="如：内部资料 请勿外传" style="max-width: 320px" />
            </el-form-item>
            <el-form-item label="位置">
              <el-select v-model="position" class="oo-field-w oo-field-w-sm">
                <el-option v-for="p in positions" :key="p.value" :label="p.label" :value="p.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="不透明度">
              <div class="ctl">
                <el-slider v-model="opacity" :min="1" :max="100" class="ctl-slider" />
                <span class="num oo-num">{{ opacity }}%</span>
              </div>
            </el-form-item>
            <el-form-item label="字号">
              <el-input-number v-model="fontSize" :min="10" :max="200" placeholder="自动" class="oo-field-w oo-field-w-md" />
              <span class="num">留空则按图片尺寸自动推算</span>
            </el-form-item>
          </template>

          <el-form-item label="输出格式">
            <el-select v-model="targetFormat" clearable placeholder="保持原格式" class="oo-field-w oo-field-w-md">
              <el-option v-for="f in caps?.outputFormats ?? []" :key="f.id" :label="f.label" :value="f.id" />
            </el-select>
          </el-form-item>
        </el-form>
      </div>
    </OOCard>

    <OOCard
      title="处理结果"
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
          <OOSectionTitle title="输出文件" description="处理后的新图片已同时保存到「我的图库」，原图保持不变" />
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
          </dl>
        </div>
      </div>

      <OOEmptyState
        v-else
        variant="inbox"
        title="还没有处理结果"
        description="选好图片与操作类型后点击「应用」，处理后的新图片会显示在这里"
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
  margin-left: var(--oo-space-3);
  font-size: var(--oo-text-xs);
  color: var(--oo-text-secondary);
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
}
</style>
