<script setup lang="ts">
/** 财务 · 账单导入：导入支付宝/微信账单，查看批次历史并可整批撤销。 */
import { onMounted, ref } from "vue";
import { bizApi, type BillImportBatch } from "@/api/biz-dashboard";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOToolbar } from "@/components/ui";
import BillImportDialog from "@/modules/biz_dashboard/BillImportDialog.vue";

const batches = ref<BillImportBatch[]>([]);
const loading = ref(false);
const error = ref("");
const importDialog = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const res = await bizApi.listBillImports();
    batches.value = res.items;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

/** 撤销整批导入：删掉该批次导入的全部流水（误导入整个文件时的兜底）。 */
async function rollbackBatch(row: BillImportBatch) {
  error.value = "";
  try {
    await bizApi.deleteBillImport(row.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

const PLATFORM_LABEL: Record<string, string> = {
  alipay: "支付宝",
  wechat: "微信支付",
  unknown: "未识别",
};

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
</script>

<template>
  <div>
    <OOPageHeader
      title="账单导入"
      description="导入支付平台导出的 CSV，自动识别编码与字段，按规则归类并跳过重复"
    >
      <el-button type="primary" @click="importDialog = true">
        <OOIcon name="upload" :size="16" style="margin-right: 6px; vertical-align: -2px" />
        导入账单
      </el-button>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="mb"
      title="导入前会先预览：显示识别出的平台、每列对应什么字段、哪些行会被跳过以及原因。同一份文件重复导入不会重复记账。"
    />

    <OOCard title="导入记录" :subtitle="`共 ${batches.length} 次导入`" flush>
      <OOToolbar hint="撤销会删除该批次导入的全部流水" dense />
      <el-table :data="batches" size="small" v-loading="loading">
        <template #empty>
          <OOEmptyState
            variant="inbox"
            title="尚未导入过账单"
            description="点击右上角「导入账单」，选择支付平台导出的 CSV 文件"
          />
        </template>
        <el-table-column label="文件" min-width="150">
          <template #default="{ row }">
            <span class="oo-truncate">{{ row.fileName || "—" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="平台" width="88">
          <template #default="{ row }">{{ PLATFORM_LABEL[row.platform] ?? row.platform }}</template>
        </el-table-column>
        <el-table-column prop="encoding" label="编码" width="88" />
        <el-table-column label="导入" width="76" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.importedRows }}</span></template>
        </el-table-column>
        <el-table-column label="重复" width="76" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.duplicateRows }}</span></template>
        </el-table-column>
        <el-table-column label="失败" width="76" align="right">
          <template #default="{ row }">
            <span class="oo-num" :class="{ 'oo-text-danger': row.failedRows > 0 }">
              {{ row.failedRows }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="110" align="right">
          <template #default="{ row }">
            <span class="oo-num">{{ money(row.amountTotal) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">
            <span class="oo-num oo-text-xs oo-text-secondary">
              {{ row.createdAt ? new Date(row.createdAt).toLocaleString("zh-CN") : "—" }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-popconfirm
              title="撤销该批次导入？该批次导入的流水会被一并删除"
              @confirm="rollbackBatch(row)"
            >
              <template #reference>
                <el-button link type="danger" size="small">撤销</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </OOCard>

    <BillImportDialog v-model="importDialog" @imported="load" />
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: var(--oo-space-5);
}
</style>
