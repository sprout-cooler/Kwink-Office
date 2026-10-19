<script setup lang="ts">
/** 我的图库：上传原件与加工产物统一管理（预览、下载、删除、按来源溯源）。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type AssetKind, type ImageAssetDto } from "@/api/image-tool";
import { downloadAsset } from "./useDownload";

const items = ref<ImageAssetDto[]>([]);
const loading = ref(false);
const filter = ref<AssetKind | "">("");
const preview = ref<ImageAssetDto | null>(null);

const KIND_LABEL: Record<string, string> = {
  original: "原件",
  convert: "转换",
  stitch: "拼接",
  compress: "压缩",
  transform: "编辑",
};

const shown = computed(() => (filter.value ? items.value.filter((i) => i.kind === filter.value) : items.value));

const totalSize = computed(() => items.value.reduce((sum, i) => sum + i.size, 0));

async function refresh() {
  loading.value = true;
  try {
    const r = await imageApi.list();
    items.value = r.items;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

async function remove(item: ImageAssetDto) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${item.filename}」？图片文件会一并删除，此操作不可撤销。`,
      "删除图片",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    const r = await imageApi.remove(item.id);
    ElMessage.success(r.fileDeleted ? "已删除" : "记录已删除（文件本就不存在）");
    if (preview.value?.id === item.id) preview.value = null;
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

onMounted(refresh);
defineExpose({ refresh });
</script>

<template>
  <div class="tab">
    <div class="bar">
      <el-radio-group v-model="filter" size="small" @change="refresh">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="original">原件</el-radio-button>
        <el-radio-button value="convert">转换</el-radio-button>
        <el-radio-button value="stitch">拼接</el-radio-button>
        <el-radio-button value="compress">压缩</el-radio-button>
        <el-radio-button value="transform">编辑</el-radio-button>
      </el-radio-group>
      <span class="stat">共 {{ shown.length }} 张 · 合计 {{ humanSize(totalSize) }}</span>
      <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
    </div>

    <el-table :data="shown" v-loading="loading" size="small" border>
      <el-table-column label="预览" width="88">
        <template #default="{ row }: { row: ImageAssetDto }">
          <img
            v-if="!row.fileMissing"
            class="thumb"
            :src="assetFileUrl(row.id)"
            :alt="row.filename"
            @click="preview = row"
          />
          <el-tag v-else type="danger" size="small">文件丢失</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip />
      <el-table-column label="类型" width="76">
        <template #default="{ row }: { row: ImageAssetDto }">
          <el-tag size="small" :type="row.kind === 'original' ? 'info' : 'success'">
            {{ KIND_LABEL[row.kind] ?? row.kind }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="尺寸" width="120">
        <template #default="{ row }: { row: ImageAssetDto }">{{ row.width }}×{{ row.height }}</template>
      </el-table-column>
      <el-table-column label="体积" width="92">
        <template #default="{ row }: { row: ImageAssetDto }">{{ humanSize(row.size) }}</template>
      </el-table-column>
      <el-table-column label="来源" width="76">
        <template #default="{ row }: { row: ImageAssetDto }">
          <span v-if="row.sourceId">#{{ row.sourceId }}</span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="创建时间" width="180" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }: { row: ImageAssetDto }">
          <el-button text size="small" :disabled="row.fileMissing" @click="downloadAsset(row)">
            下载
          </el-button>
          <el-button text size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="图库还是空的，去「格式转换」上传第一张图片" :image-size="70" />
      </template>
    </el-table>

    <el-dialog
      :model-value="!!preview"
      width="auto"
      title="图片预览"
      @update:model-value="(v: boolean) => { if (!v) preview = null; }"
    >
      <img v-if="preview" class="preview-img" :src="assetFileUrl(preview.id)" :alt="preview.filename" />
    </el-dialog>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}
.stat {
  font-size: 12px;
  color: #909399;
}
.thumb {
  width: 64px;
  height: 44px;
  object-fit: cover;
  border-radius: 4px;
  cursor: zoom-in;
  background: #f5f7fa;
}
.preview-img {
  max-width: 76vw;
  max-height: 70vh;
  object-fit: contain;
}
</style>
