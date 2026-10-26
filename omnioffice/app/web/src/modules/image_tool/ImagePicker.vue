<script setup lang="ts">
/** 图片选择器：上传 + 缩略图网格 + 多选/单选 + 排序。
 *
 * 六个 Tab 共用（拼接是多选，其余单选）。上传后立即回显缩略图，
 * 缩略图用后端 file 接口直读，不在前端 hold base64 —— 大图 base64 会撑爆内存。
 */
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type ImageAssetDto } from "@/api/image-tool";
import { OOEmptyState, OOIcon, OOToolbar } from "@/components/ui";

const props = withDefaults(
  defineProps<{
    modelValue: number[];
    multiple?: boolean;
    label?: string;
    tips?: string;
    /** 只显示上传的原件（加工产物也可作为输入时置 false） */
    originalsOnly?: boolean;
  }>(),
  { multiple: false, label: "选择图片", tips: "", originalsOnly: true },
);

const emit = defineEmits<{ "update:modelValue": [ids: number[]] }>();

const list = ref<ImageAssetDto[]>([]);
const uploading = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
/** 拖拽悬停态（纯视觉反馈，不参与任何业务判断） */
const dragOver = ref(false);

const picked = computed(() => list.value.filter((i) => props.modelValue.includes(i.id)));

function trigger() {
  fileInput.value?.click();
}

async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  if (!files.length) return;
  uploading.value = true;
  try {
    const r = await imageApi.upload(files);
    await refresh();
    if (r.accepted.length) {
      // 新上传的自动选中：用户传完图通常就是想对它操作，减少一次点击
      const add = r.accepted.map((a) => a.id);
      emit("update:modelValue", props.multiple ? [...props.modelValue, ...add] : [add[0]]);
      ElMessage.success(`已上传 ${r.accepted.length} 张`);
    }
    if (r.duplicates.length) ElMessage.info(`${r.duplicates.length} 张为重复图片，已复用已有记录`);
    for (const rj of r.rejected) ElMessage.error(`${rj.filename}：${rj.reason}`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    uploading.value = false;
    input.value = "";
  }
}

async function refresh() {
  try {
    const r = await imageApi.list(props.originalsOnly ? "original" : undefined);
    list.value = r.items;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

function pick(item: ImageAssetDto) {
  if (item.fileMissing) {
    ElMessage.warning(`「${item.filename}」的文件已丢失，请重新上传`);
    return;
  }
  if (props.multiple) {
    const has = props.modelValue.includes(item.id);
    emit("update:modelValue", has ? props.modelValue.filter((i) => i !== item.id) : [...props.modelValue, item.id]);
  } else {
    emit("update:modelValue", [item.id]);
  }
}

/** 拼接顺序可调：前后移动（拼接结果对顺序敏感，用户必须有控制权）。 */
function move(idx: number, dir: -1 | 1) {
  const arr = [...props.modelValue];
  const to = idx + dir;
  if (to < 0 || to >= arr.length) return;
  [arr[idx], arr[to]] = [arr[to], arr[idx]];
  emit("update:modelValue", arr);
}

defineExpose({ refresh });

watch(() => props.originalsOnly, refresh);
</script>

<template>
  <div class="picker">
    <OOToolbar>
      <template #left>
        <div class="picker-head">
          <span class="picker-label">{{ label }}</span>
          <span v-if="tips" class="picker-tips oo-truncate">{{ tips }}</span>
        </div>
      </template>
      <template #right>
        <el-button size="small" :loading="uploading" @click="trigger">
          <span class="oo-btn-icon"><OOIcon name="upload" :size="14" /></span>
          上传图片
        </el-button>
      </template>
    </OOToolbar>

    <div class="picker-body" v-loading="uploading">
      <!--
        投放区：file input 以透明层铺满整块区域，
        因此「点击选中」与「把文件拖进来」都落到同一个 change 事件链路上。
      -->
      <div class="picker-drop" :class="{ 'is-dragover': dragOver }">
        <input
          ref="fileInput"
          class="picker-drop-input"
          type="file"
          accept="image/*"
          multiple
          @change="onFiles"
          @dragenter="dragOver = true"
          @dragover="dragOver = true"
          @dragleave="dragOver = false"
          @drop="dragOver = false"
        />
        <span class="picker-drop-icon" aria-hidden="true"><OOIcon name="upload" :size="22" /></span>
        <span class="picker-drop-title">点击选择，或把图片拖到这里</span>
        <span class="picker-drop-hint">支持 JPG / PNG / WEBP / GIF / BMP / TIFF，可一次多选</span>
      </div>

      <div v-if="picked.length && multiple" class="picker-order">
        <span class="order-label">拼接顺序：</span>
        <el-tag
          v-for="(id, i) in modelValue"
          :key="id"
          size="small"
          closable
          class="order-tag"
          @close="pick(list.find((x) => x.id === id)!)"
        >
          {{ i + 1 }}. {{ list.find((x) => x.id === id)?.filename ?? id }}
          <el-button
            text
            size="small"
            :disabled="i === 0"
            @click.stop="move(i, -1)"
          >↑</el-button>
          <el-button
            text
            size="small"
            :disabled="i === modelValue.length - 1"
            @click.stop="move(i, 1)"
          >↓</el-button>
        </el-tag>
      </div>

      <div class="picker-grid">
        <div
          v-for="item in list"
          :key="item.id"
          class="cell"
          :class="{ active: modelValue.includes(item.id), broken: item.fileMissing }"
          :title="`${item.filename} · ${item.width}×${item.height} · ${humanSize(item.size)}`"
          @click="pick(item)"
        >
          <div class="cell-thumb">
            <img v-if="!item.fileMissing" :src="assetFileUrl(item.id)" :alt="item.filename" loading="lazy" />
            <span v-else class="broken-tip">文件丢失</span>
            <span v-if="modelValue.includes(item.id)" class="cell-check" aria-hidden="true">
              <OOIcon name="check" :size="12" />
            </span>
          </div>
          <span class="cell-name">{{ item.filename }}</span>
        </div>
      </div>

      <OOEmptyState
        v-if="!list.length && !uploading"
        variant="inbox"
        title="还没有图片"
        description="点击上方投放区上传，或直接把图片拖进来；上传后会自动选中最新一张"
      />
    </div>
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
}

.picker-body {
  display: flex;
  flex-direction: column;
  gap: var(--oo-space-3);
  padding: var(--oo-space-4) var(--oo-space-5) var(--oo-space-5);
}

/* —— 头部：标题 + 上传按钮 —— */
.picker-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.picker-label {
  font-size: var(--oo-text-base);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
  line-height: var(--oo-line-tight);
}

.picker-tips {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  line-height: var(--oo-line-relaxed);
  max-width: 52ch;
}

.oo-btn-icon {
  display: inline-flex;
  align-items: center;
  vertical-align: -2px;
  margin-right: 4px;
}

/* —— 投放区 —— */
.picker-drop {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--oo-space-2);
  padding: var(--oo-space-6) var(--oo-space-4);
  border: 1px dashed var(--oo-border-default);
  border-radius: var(--oo-radius-lg);
  background: var(--oo-bg-surface-2);
  cursor: pointer;
  transition: border-color var(--oo-dur-base) var(--oo-ease-out),
    background var(--oo-dur-base) var(--oo-ease-out),
    box-shadow var(--oo-dur-base) var(--oo-ease-out);
}

/* hover 与「拖入悬停」共用一套高亮（拖动文件经过时浏览器同样触发 hover） */
.picker-drop:hover,
.picker-drop:focus-within,
.picker-drop.is-dragover {
  border-color: var(--oo-border-brand);
  background: var(--oo-brand-soft);
  box-shadow: var(--oo-shadow-brand);
}

/* 透明层铺满整块区域：点击即选中，拖入的文件也会落到这个 input 上 */
.picker-drop-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.picker-drop-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border-radius: var(--oo-radius-md);
  background: var(--oo-brand-soft);
  color: var(--oo-brand);
  transition: background var(--oo-dur-base) var(--oo-ease-out),
    color var(--oo-dur-base) var(--oo-ease-out);
}

.picker-drop:hover .picker-drop-icon,
.picker-drop:focus-within .picker-drop-icon,
.picker-drop.is-dragover .picker-drop-icon {
  background: var(--oo-brand);
  color: var(--oo-brand-on);
}

.picker-drop-title {
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-medium);
  color: var(--oo-text-primary);
}

.picker-drop-hint {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

/* —— 拼接顺序 —— */
.picker-order {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--oo-space-2);
  padding: var(--oo-space-3);
  border-radius: var(--oo-radius-md);
  border: 1px solid var(--oo-border-subtle);
  background: var(--oo-bg-surface-2);
}

.order-label {
  font-size: var(--oo-text-xs);
  font-weight: var(--oo-weight-medium);
  color: var(--oo-text-secondary);
}

.order-tag {
  max-width: 320px;
}

/* —— 缩略图网格 —— */
.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(120px, 100%), 1fr));
  gap: var(--oo-space-3);
  max-height: 340px;
  overflow-y: auto;
}

.cell {
  display: flex;
  flex-direction: column;
  border: 2px solid transparent;
  border-radius: var(--oo-radius-md);
  overflow: hidden;
  cursor: pointer;
  background: var(--oo-bg-surface);
  transition: border-color var(--oo-dur-base) var(--oo-ease-out),
    box-shadow var(--oo-dur-base) var(--oo-ease-out),
    transform var(--oo-dur-base) var(--oo-ease-out);
}

.cell:hover {
  border-color: var(--oo-border-strong);
  box-shadow: var(--oo-shadow-sm);
  transform: translateY(-1px);
}

.cell.active {
  border-color: var(--oo-border-brand);
  box-shadow: var(--oo-shadow-brand);
}

.cell-thumb {
  position: relative;
  aspect-ratio: 4 / 3;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 透明棋盘格底：能看出 PNG 的透明区域 */
  background-color: var(--oo-bg-surface-3);
  background-image: linear-gradient(45deg, var(--oo-bg-surface-2) 25%, transparent 25%, transparent 75%, var(--oo-bg-surface-2) 75%),
    linear-gradient(45deg, var(--oo-bg-surface-2) 25%, transparent 25%, transparent 75%, var(--oo-bg-surface-2) 75%);
  background-size: 14px 14px;
  background-position: 0 0, 7px 7px;
}

.cell-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.cell-check {
  position: absolute;
  top: 6px;
  right: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: var(--oo-radius-pill);
  background: var(--oo-brand);
  color: var(--oo-brand-on);
  box-shadow: var(--oo-shadow-sm);
}

.cell-name {
  display: block;
  padding: var(--oo-space-2);
  font-size: var(--oo-text-2xs);
  color: var(--oo-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-top: 1px solid var(--oo-border-subtle);
  background: var(--oo-bg-surface);
}

.cell.broken {
  opacity: 0.72;
}

.broken-tip {
  font-size: var(--oo-text-xs);
  color: var(--oo-danger-text);
}

/* —— 窄屏 —— */
@media (max-width: 560px) {
  .picker-body {
    padding: var(--oo-space-3) var(--oo-space-4) var(--oo-space-4);
  }
  .picker-drop {
    padding: var(--oo-space-5) var(--oo-space-3);
  }
  .picker-grid {
    grid-template-columns: repeat(auto-fill, minmax(min(96px, 100%), 1fr));
    gap: var(--oo-space-2);
  }
}
</style>
