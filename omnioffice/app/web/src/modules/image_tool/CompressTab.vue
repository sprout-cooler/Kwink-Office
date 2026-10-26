<script setup lang="ts">
/** 图片压缩 Tab：质量因子模式与目标体积模式（含二分搜索是否达标的如实回报）。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type Capabilities, type ImageAssetDto } from "@/api/image-tool";
import ImagePicker from "./ImagePicker.vue";
import { downloadAsset } from "./useDownload";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOSectionTitle, OOToolbar } from "@/components/ui";

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
    <OOPageHeader
      title="图片压缩"
      description="按质量因子或目标体积压缩图片，压缩后体积不降反升时会如实告知"
      badge="🗜"
    />

    <el-alert type="info" :closable="false" class="oo-mb-4">
      压缩会生成新图片并保留原图。<strong>目标体积模式</strong>会二分搜索质量因子，尽量贴近目标大小；
      若图片本身已高度压缩（如纯色截图），压不动时会如实告知，而不是给你一个更大的文件。
    </el-alert>

    <OOCard flush class="oo-mb-4">
      <ImagePicker
        ref="picker"
        v-model="ids"
        @update:model-value="loadForCompare"
        tips="上传或从图库中挑一张要压缩的原图"
      />
    </OOCard>

    <OOCard flush class="oo-mb-4">
      <OOToolbar>
        <template #left>
          <span class="bar-title">压缩方式</span>
          <el-radio-group v-model="mode" size="small">
            <el-radio-button value="quality">质量因子</el-radio-button>
            <el-radio-button value="target">目标体积</el-radio-button>
          </el-radio-group>
        </template>
        <template #right>
          <span v-if="source" class="count oo-num">原图 {{ humanSize(source.size) }}</span>
          <el-button type="primary" :loading="busy" :disabled="!ids.length" @click="run">
            开始压缩
          </el-button>
        </template>
      </OOToolbar>

      <div class="card-pad" v-loading="busy">
        <el-form label-width="96px">
          <el-form-item v-if="mode === 'quality'" label="质量因子">
            <div class="ctl">
              <el-slider
                v-model="quality"
                :min="caps?.quality.min ?? 1"
                :max="caps?.quality.max ?? 100"
                class="ctl-slider"
              />
              <span class="num oo-num">{{ quality }}</span>
            </div>
            <p class="hint-text">数值越低体积越小，画质损失也越明显。</p>
          </el-form-item>
          <el-form-item v-else label="目标体积">
            <el-input-number v-model="targetKib" :min="1" :max="102400" :step="10" class="oo-field-w oo-field-w-md" />
            <span class="num oo-num">KB</span>
            <p class="hint-text">系统会二分搜索质量因子，尽量贴近这个大小；压不到时如实告知。</p>
          </el-form-item>
          <el-form-item label="输出格式">
            <el-select v-model="targetFormat" clearable placeholder="保持原格式" class="oo-field-w oo-field-w-lg">
              <el-option v-for="f in caps?.outputFormats ?? []" :key="f.id" :label="f.label" :value="f.id" />
            </el-select>
            <span v-if="!targetFormat" class="num">
              保持原格式{{ keepFormat ? "（纯压缩，不换格式）" : "（回退 JPEG）" }}
            </span>
          </el-form-item>
          <el-form-item v-if="!targetFormat && mode === 'quality'">
            <el-checkbox v-model="keepFormat">保持原格式（取消则转为 JPEG，压缩率更高）</el-checkbox>
          </el-form-item>
        </el-form>
      </div>
    </OOCard>

    <OOCard
      title="压缩结果"
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

      <template v-if="result && verdict">
        <!-- 前后对比：左原图 / 右压缩后，中间一条分隔线 -->
        <div class="compare">
          <figure class="compare-side">
            <div class="compare-frame">
              <img v-if="source" :src="assetFileUrl(source.id)" :alt="source.filename" />
              <span v-else class="compare-none">原图不可用</span>
            </div>
            <figcaption class="compare-cap">
              <span class="compare-cap-title">原图</span>
              <span class="compare-cap-val oo-num">{{ humanSize(verdict.original) }}</span>
            </figcaption>
          </figure>

          <div class="compare-divider" aria-hidden="true"></div>

          <figure class="compare-side">
            <div class="compare-frame">
              <img :src="assetFileUrl(result.id)" :alt="result.filename" />
            </div>
            <figcaption class="compare-cap">
              <span class="compare-cap-title">压缩后</span>
              <span class="compare-cap-val oo-num">{{ humanSize(verdict.compressed) }}</span>
            </figcaption>
          </figure>
        </div>

        <div class="verdict-row">
          <el-tag v-if="verdict.ratio > 0" type="success" size="small">
            体积减少 {{ verdict.ratio }}%
          </el-tag>
          <el-tag v-else-if="verdict.ratio < 0" type="warning" size="small">
            反而增大 {{ Math.abs(verdict.ratio) }}%
          </el-tag>
          <el-tag v-else type="info" size="small">体积基本持平</el-tag>
          <el-tag v-if="mode === 'target' && verdict.reached === false" type="warning" size="small">
            未达到目标体积
          </el-tag>
        </div>

        <OOSectionTitle
          class="oo-mt-4"
          title="处理说明"
          description="压缩后的新图片已同时保存到「我的图库」，原图保持不变"
        />
        <p v-if="verdict.hint" class="hint-text hint-warn">{{ verdict.hint }}</p>
      </template>

      <OOEmptyState
        v-else
        variant="inbox"
        title="还没有压缩结果"
        description="选好图片与压缩方式后点击「开始压缩」，会在这里对比压缩前后的体积"
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

.hint-text {
  margin-top: 2px;
  font-size: var(--oo-text-xs);
  line-height: var(--oo-line-relaxed);
  color: var(--oo-text-tertiary);
}

.hint-warn {
  margin-top: var(--oo-space-2);
  color: var(--oo-warning-text);
}

/* —— 前后对比 —— */
.compare {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr);
  gap: var(--oo-space-4);
  align-items: start;
}

.compare-side {
  margin: 0;
  min-width: 0;
}

.compare-frame {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
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

.compare-frame img {
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
  border-radius: var(--oo-radius-xs);
}

.compare-none {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.compare-divider {
  align-self: stretch;
  background: var(--oo-border-subtle);
}

.compare-cap {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--oo-space-3);
  margin-top: var(--oo-space-2);
  padding-top: var(--oo-space-2);
  border-top: 1px solid var(--oo-border-subtle);
}

.compare-cap-title {
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-medium);
  color: var(--oo-text-secondary);
}

.compare-cap-val {
  font-size: var(--oo-text-sm);
  color: var(--oo-text-primary);
}

.verdict-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--oo-space-2);
  margin-top: var(--oo-space-4);
}

/* —— 窄屏 —— */
@media (max-width: 768px) {
  .compare {
    grid-template-columns: 1fr;
    gap: var(--oo-space-3);
  }
  .compare-divider {
    height: 1px;
    width: 100%;
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
