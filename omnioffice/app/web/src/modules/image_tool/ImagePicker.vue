<script setup lang="ts">
/** 图片选择器：上传 + 缩略图网格 + 多选/单选 + 排序。
 *
 * 六个 Tab 共用（拼接是多选，其余单选）。上传后立即回显缩略图，
 * 缩略图用后端 file 接口直读，不在前端 hold base64 —— 大图 base64 会撑爆内存。
 */
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type ImageAssetDto } from "@/api/image-tool";

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
    <div class="picker-head">
      <span class="picker-label">{{ label }}</span>
      <el-button size="small" :loading="uploading" @click="trigger">选择图片</el-button>
      <input ref="fileInput" type="file" accept="image/*" multiple hidden @change="onFiles" />
    </div>
    <p v-if="tips" class="picker-tips">{{ tips }}</p>

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
        <img v-if="!item.fileMissing" :src="assetFileUrl(item.id)" :alt="item.filename" loading="lazy" />
        <span v-else class="broken-tip">文件丢失</span>
        <span class="cell-name">{{ item.filename }}</span>
      </div>
      <el-empty v-if="!list.length" description="还没有图片，点上方按钮上传" :image-size="60" />
    </div>
  </div>
</template>

<style scoped>
.picker-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}
.picker-label {
  font-size: 13px;
  color: var(--color-text-primary, #303133);
}
.picker-tips {
  margin: 0 0 8px;
  font-size: 12px;
  color: #909399;
}
.picker-order {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}
.order-label {
  font-size: 12px;
  color: #909399;
}
.order-tag {
  max-width: 320px;
}
.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
  gap: 10px;
  max-height: 320px;
  overflow-y: auto;
  padding: 2px;
}
.cell {
  position: relative;
  border: 2px solid transparent;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  background: var(--color-background-secondary, #f5f7fa);
  transition: border-color 0.15s;
}
.cell:hover {
  border-color: #c0c4cc;
}
.cell.active {
  border-color: var(--el-color-primary, #409eff);
}
.cell img {
  display: block;
  width: 100%;
  height: 76px;
  object-fit: cover;
}
.cell-name {
  display: block;
  padding: 3px 5px;
  font-size: 11px;
  color: #606266;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cell.broken {
  opacity: 0.6;
}
.broken-tip {
  display: block;
  height: 76px;
  line-height: 76px;
  text-align: center;
  font-size: 12px;
  color: #f56c6c;
}
</style>
