<script setup lang="ts">
/** 我的图库：上传原件与加工产物统一管理（预览、下载、删除、按来源溯源）。 */
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { imageApi, assetFileUrl, humanSize, type AssetKind, type ImageAssetDto } from "@/api/image-tool";
import { downloadAsset } from "./useDownload";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOToolbar } from "@/components/ui";

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
    <OOPageHeader
      title="我的图库"
      description="上传的原件与各项加工产物统一存放，可预览、下载、删除并按来源溯源"
      badge="🗂"
    />

    <el-alert type="info" :closable="false" class="oo-mb-4">
      图库统一存放<strong>上传的原件</strong>与各功能的加工产物（转换 / 拼接 / 压缩 / 编辑），可预览、下载、删除；
      「来源」列显示产物由哪一张原件生成，点击缩略图可查看大图。
    </el-alert>

    <OOCard flush>
      <OOToolbar>
        <template #left>
          <el-radio-group v-model="filter" size="small" @change="refresh">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="original">原件</el-radio-button>
            <el-radio-button value="convert">转换</el-radio-button>
            <el-radio-button value="stitch">拼接</el-radio-button>
            <el-radio-button value="compress">压缩</el-radio-button>
            <el-radio-button value="transform">编辑</el-radio-button>
          </el-radio-group>
          <span class="stat oo-num">共 {{ shown.length }} 张 · 合计 {{ humanSize(totalSize) }}</span>
        </template>
        <template #right>
          <el-button size="small" :loading="loading" @click="refresh">
            <span class="oo-btn-icon"><OOIcon name="refresh" :size="14" /></span>
            刷新
          </el-button>
        </template>
      </OOToolbar>

      <div class="table-wrap" v-loading="loading">
        <el-table
          v-if="shown.length"
          :data="shown"
          size="small"
          row-key="id"
        >
          <el-table-column label="预览" width="96">
            <template #default="{ row }: { row: ImageAssetDto }">
              <div class="thumb-wrap">
                <img
                  v-if="!row.fileMissing"
                  class="thumb"
                  :src="assetFileUrl(row.id)"
                  :alt="row.filename"
                  @click="preview = row"
                />
                <el-tag v-else type="danger" size="small">文件丢失</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip>
            <template #default="{ row }: { row: ImageAssetDto }">
              <span class="name oo-truncate">{{ row.filename }}</span>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }: { row: ImageAssetDto }">
              <el-tag size="small" :type="row.kind === 'original' ? 'info' : 'success'">
                {{ KIND_LABEL[row.kind] ?? row.kind }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="尺寸" width="124">
            <template #default="{ row }: { row: ImageAssetDto }">
              <span class="oo-num">{{ row.width }}×{{ row.height }}</span>
            </template>
          </el-table-column>
          <el-table-column label="体积" width="96">
            <template #default="{ row }: { row: ImageAssetDto }">
              <span class="oo-num">{{ humanSize(row.size) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="80">
            <template #default="{ row }: { row: ImageAssetDto }">
              <span v-if="row.sourceId" class="oo-num">#{{ row.sourceId }}</span>
              <span v-else class="oo-text-tertiary">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="createdAt" label="创建时间" width="180">
            <template #default="{ row }: { row: ImageAssetDto }">
              <span class="oo-num">{{ row.createdAt ?? "—" }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }: { row: ImageAssetDto }">
              <el-button text size="small" :disabled="row.fileMissing" @click="downloadAsset(row)">
                下载
              </el-button>
              <el-button text size="small" type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <OOEmptyState
          v-else-if="!loading"
          variant="folder"
          :title="filter ? '该类型下暂无图片' : '图库还是空的'"
          description="去「格式转换」上传第一张图片，或用「图片拼接」批量导入，处理产物也会自动存到这里"
        />
      </div>
    </OOCard>

    <el-dialog
      :model-value="!!preview"
      width="auto"
      title="图片预览"
      align-center
      @update:model-value="(v: boolean) => { if (!v) preview = null; }"
    >
      <div v-if="preview" class="preview-frame">
        <img class="preview-img" :src="assetFileUrl(preview.id)" :alt="preview.filename" />
      </div>
      <p v-if="preview" class="preview-meta oo-num">
        {{ preview.width }}×{{ preview.height }} · {{ humanSize(preview.size) }}
      </p>
    </el-dialog>
  </div>
</template>

<style scoped>
.tab {
  max-width: 1080px;
}

.oo-btn-icon {
  display: inline-flex;
  align-items: center;
  vertical-align: -2px;
  margin-right: 4px;
}

/* —— 工具条 —— */
.stat {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

/* —— 表格 —— */
.table-wrap {
  min-height: 200px;
  padding: var(--oo-space-3) var(--oo-space-4) var(--oo-space-4);
}

.name {
  color: var(--oo-text-primary);
  font-weight: var(--oo-weight-medium);
}

.thumb-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 44px;
}

.thumb {
  width: 68px;
  height: 44px;
  object-fit: contain;
  border-radius: var(--oo-radius-xs);
  cursor: zoom-in;
  border: 1px solid var(--oo-border-subtle);
  /* 透明棋盘格底 */
  background-color: var(--oo-bg-surface-3);
  background-image: linear-gradient(45deg, var(--oo-bg-surface-2) 25%, transparent 25%, transparent 75%, var(--oo-bg-surface-2) 75%),
    linear-gradient(45deg, var(--oo-bg-surface-2) 25%, transparent 25%, transparent 75%, var(--oo-bg-surface-2) 75%);
  background-size: 10px 10px;
  background-position: 0 0, 5px 5px;
  transition: box-shadow var(--oo-dur-base) var(--oo-ease-out);
}

.thumb:hover {
  box-shadow: var(--oo-shadow-brand);
}

/* —— 预览 —— */
.preview-frame {
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
  background-size: 18px 18px;
  background-position: 0 0, 9px 9px;
}

.preview-img {
  max-width: 76vw;
  max-height: 70vh;
  object-fit: contain;
  border-radius: var(--oo-radius-xs);
}

.preview-meta {
  margin-top: var(--oo-space-3);
  text-align: center;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}
</style>
