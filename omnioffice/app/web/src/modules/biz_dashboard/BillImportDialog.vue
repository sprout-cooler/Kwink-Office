<script setup lang="ts">
/** 账单文件导入：上传 → 预览 → 确认导入。
 *
 * 三步走而不是「选完直接导」：账单解析一旦错位（编码判断错、列错位）
 * 是**静默**的，钱会记错且不报错。所以必须先让用户看到
 * 「识别成什么平台、每列对应到什么字段、哪几行会被跳过以及为什么」，
 * 确认无误后再落库。
 *
 * 预览与正式导入都重新上传原始文件：前端不回传解析结果，
 * 避免被篡改后把坏数据塞进库。
 */
import { computed, ref } from "vue";
import {
  bizApi,
  type BillPreview,
  type BillRow,
} from "@/api/biz-dashboard";
import { OOEmptyState, OOIcon, OOSectionTitle } from "@/components/ui";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ "update:modelValue": [boolean]; imported: [] }>();

const file = ref<File | null>(null);
const preview = ref<BillPreview | null>(null);
const result = ref<BillPreview | null>(null);
const previewing = ref(false);
const committing = ref(false);
const error = ref("");
const statusFilter = ref<"all" | "ok" | "duplicate" | "skipped" | "failed">("all");

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const PLATFORM_LABEL: Record<string, string> = {
  alipay: "支付宝",
  wechat: "微信支付",
  unknown: "未识别平台",
};
const FIELD_LABEL: Record<string, string> = {
  txn_time: "交易时间",
  txn_type: "交易类型",
  counterparty: "交易对方",
  amount: "金额",
  direction: "收支方向",
  order_no: "订单号",
  note: "备注",
};
const STATUS_META: Record<string, { label: string; type: string }> = {
  ok: { label: "将导入", type: "success" },
  duplicate: { label: "重复跳过", type: "info" },
  skipped: { label: "不纳入", type: "warning" },
  failed: { label: "无法导入", type: "danger" },
};

const rows = computed<BillRow[]>(() => {
  const src = result.value ?? preview.value;
  if (!src) return [];
  if (statusFilter.value === "all") return src.rows;
  return src.rows.filter((r) => r.status === statusFilter.value);
});

const summary = computed(() => (result.value ?? preview.value)?.summary ?? null);

const platformLabel = computed(() => {
  const p = (result.value ?? preview.value)?.platform ?? "";
  return PLATFORM_LABEL[p] ?? "未识别平台";
});

/** 已识别出的字段映射（用于告诉用户「哪一列被当成了金额」） */
const mappingPairs = computed(() => {
  const m = (result.value ?? preview.value)?.mapping ?? {};
  return Object.entries(m)
    .filter(([k]) => FIELD_LABEL[k])
    .map(([k, v]) => ({ field: FIELD_LABEL[k], column: v, key: k }));
});

function reset() {
  file.value = null;
  preview.value = null;
  result.value = null;
  error.value = "";
  statusFilter.value = "all";
}

function close() {
  emit("update:modelValue", false);
  reset();
}

function onPick(uploadFile: { raw?: File; name?: string }) {
  const raw = uploadFile?.raw;
  if (!raw) return;
  file.value = raw;
  result.value = null;
  error.value = "";
  void doPreview(raw);
}

async function doPreview(f: File) {
  previewing.value = true;
  error.value = "";
  try {
    preview.value = await bizApi.previewBillImport(f);
  } catch (e) {
    preview.value = null;
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    previewing.value = false;
  }
}

async function commit() {
  if (!file.value) return;
  committing.value = true;
  error.value = "";
  try {
    result.value = await bizApi.commitBillImport(file.value);
    emit("imported");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    committing.value = false;
  }
}

const canCommit = computed(
  () => !!file.value && !result.value && (preview.value?.summary.ok ?? 0) > 0,
);
</script>

<template>
  <el-dialog
    :model-value="props.modelValue"
    width="900px"
    align-center
    @update:model-value="(v: boolean) => (v ? undefined : close())"
  >
    <template #header>
      <div class="oo-dialog-head">
        <span class="oo-dialog-icon"><OOIcon name="upload" :size="18" /></span>
        <div>
          <h3 class="oo-dialog-title">导入支付平台账单</h3>
          <p class="oo-dialog-desc">
            支持支付宝 / 微信支付导出的 CSV（自动识别 UTF-8 / GBK 编码），导入前可先预览核对
          </p>
        </div>
      </div>
    </template>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <!-- 第一步：选文件 -->
    <OOSectionTitle v-if="!preview && !result" title="选择账单文件">
      请使用支付平台官方导出的原始 CSV，不要自行编辑或另存为 Excel 表格
    </OOSectionTitle>
    <el-upload
      v-if="!preview && !result"
      drag
      :auto-upload="false"
      :show-file-list="false"
      accept=".csv,.txt"
      :on-change="onPick"
    >
      <div class="bz-drop">
        <OOIcon name="upload" :size="26" />
        <p class="bz-drop-main">把账单文件拖到这里，或点击选择</p>
        <p class="bz-drop-sub">支持 .csv，自动识别 UTF-8 / GBK 编码</p>
      </div>
    </el-upload>

    <!-- 第二步：预览 -->
    <template v-if="preview && !result">
      <div class="bz-meta">
        <el-tag size="small" effect="light" type="success">{{ platformLabel }}</el-tag>
        <el-tag size="small" effect="plain">{{ preview.encoding }}</el-tag>
        <span class="bz-meta-text">
          表头在第 {{ preview.headerLine }} 行 · 共 {{ preview.summary.total }} 条
        </span>
      </div>

      <div class="bz-stats">
        <div class="bz-stat bz-stat-ok">
          <b class="oo-num">{{ preview.summary.ok }}</b>
          <span>将导入</span>
        </div>
        <div class="bz-stat">
          <b class="oo-num">{{ preview.summary.duplicate }}</b>
          <span>重复跳过</span>
        </div>
        <div class="bz-stat">
          <b class="oo-num">{{ preview.summary.skipped }}</b>
          <span>不纳入</span>
        </div>
        <div class="bz-stat bz-stat-bad">
          <b class="oo-num">{{ preview.summary.failed }}</b>
          <span>无法导入</span>
        </div>
        <div class="bz-stat bz-stat-money">
          <b class="oo-num">{{ money(preview.amountTotal) }}</b>
          <span>合计金额</span>
        </div>
      </div>

      <OOSectionTitle title="字段识别结果">确认每一列都被正确识别后再导入</OOSectionTitle>
      <div class="bz-mapping">
        <span v-for="m in mappingPairs" :key="m.key" class="bz-map-chip">
          {{ m.field }}<i>←</i>{{ m.column }}
        </span>
        <span v-if="!mappingPairs.length" class="oo-text-tertiary oo-text-xs">
          未能识别出账单字段
        </span>
      </div>

      <OOSectionTitle title="明细预览">被跳过的行都会在下方给出原因</OOSectionTitle>
    </template>

    <!-- 第三步：结果 -->
    <template v-if="result">
      <el-alert
        type="success"
        :closable="false"
        show-icon
        class="mb"
        :title="`已导入 ${result.imported ?? 0} 条，合计 ${money(result.amountTotal)}`"
      />
    </template>

    <!-- 明细表（预览与结果共用） -->
    <div v-if="preview || result" class="bz-rows">
      <div class="bz-filter">
        <el-radio-group v-model="statusFilter" size="small">
          <el-radio-button value="all">全部 {{ summary?.total ?? 0 }}</el-radio-button>
          <el-radio-button value="ok">将导入 {{ summary?.ok ?? 0 }}</el-radio-button>
          <el-radio-button value="duplicate">重复 {{ summary?.duplicate ?? 0 }}</el-radio-button>
          <el-radio-button value="skipped">不纳入 {{ summary?.skipped ?? 0 }}</el-radio-button>
          <el-radio-button value="failed">失败 {{ summary?.failed ?? 0 }}</el-radio-button>
        </el-radio-group>
      </div>
      <el-table :data="rows" size="small" max-height="320" v-loading="previewing || committing">
        <template #empty>
          <OOEmptyState variant="inbox" title="该分类下没有记录" />
        </template>
        <el-table-column prop="line" label="行" width="52" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.line }}</span></template>
        </el-table-column>
        <el-table-column prop="txnTime" label="交易时间" width="102" />
        <el-table-column label="交易对方" min-width="110">
          <template #default="{ row }">{{ row.counterparty || "—" }}</template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ row.txnType || "—" }}</template>
        </el-table-column>
        <el-table-column label="金额" width="100" align="right">
          <template #default="{ row }">
            <span class="oo-num">{{ row.amount === null ? "—" : money(row.amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="72">
          <template #default="{ row }">
            <el-tag
              v-if="row.direction"
              size="small"
              effect="light"
              :type="row.direction === 'income' ? 'success' : 'danger'"
            >
              {{ row.direction === "income" ? "收入" : "支出" }}
            </el-tag>
            <span v-else class="oo-text-tertiary">—</span>
          </template>
        </el-table-column>
        <el-table-column label="订单号" min-width="120">
          <template #default="{ row }">
            <span class="oo-num bz-order">{{ row.orderNo || "—" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="88">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="STATUS_META[row.status]?.type ?? 'info'">
              {{ STATUS_META[row.status]?.label ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="原因" min-width="180">
          <template #default="{ row }">
            <span class="oo-text-secondary oo-text-xs">{{ row.reason || "—" }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <template #footer>
      <template v-if="result">
        <el-button @click="reset">再导入一个</el-button>
        <el-button type="primary" @click="close">完成</el-button>
      </template>
      <template v-else>
        <el-button @click="close">取消</el-button>
        <el-button v-if="preview" @click="reset">重新选择</el-button>
        <el-button type="primary" :loading="committing" :disabled="!canCommit" @click="commit">
          确认导入{{ preview?.summary.ok ? ` ${preview.summary.ok} 条` : "" }}
        </el-button>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.bz-drop {
  padding: var(--oo-space-6) var(--oo-space-4);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--oo-space-2);
  color: var(--oo-text-secondary);
}
.bz-drop-main {
  margin: 0;
  font-size: var(--oo-text-base);
  color: var(--oo-text-primary);
  font-weight: var(--oo-weight-medium);
}
.bz-drop-sub {
  margin: 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.bz-meta {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
  margin-bottom: var(--oo-space-3);
}
.bz-meta-text {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.bz-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(96px, 100%), 1fr));
  gap: var(--oo-space-2);
  margin-bottom: var(--oo-space-4);
}
.bz-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--oo-space-3);
  border-radius: var(--oo-radius-md);
  background: var(--oo-bg-surface-2);
  border: 1px solid var(--oo-border-subtle);
}
.bz-stat b {
  font-size: var(--oo-text-xl);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
}
.bz-stat span {
  font-size: var(--oo-text-2xs);
  color: var(--oo-text-tertiary);
}
.bz-stat-ok {
  background: var(--oo-success-soft);
  border-color: transparent;
}
.bz-stat-bad {
  background: var(--oo-danger-soft);
  border-color: transparent;
}
.bz-stat-money b {
  color: var(--oo-text-brand);
}

.bz-mapping {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oo-space-2);
  margin-bottom: var(--oo-space-4);
}
.bz-map-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: var(--oo-radius-pill);
  background: var(--oo-brand-soft);
  color: var(--oo-text-brand);
  font-size: var(--oo-text-xs);
}
.bz-map-chip i {
  font-style: normal;
  color: var(--oo-text-tertiary);
}

.bz-rows {
  margin-top: var(--oo-space-2);
}
.bz-filter {
  margin-bottom: var(--oo-space-2);
}
.bz-order {
  font-size: var(--oo-text-2xs);
  color: var(--oo-text-secondary);
}

.mb {
  margin-bottom: var(--oo-space-4);
}

.oo-dialog-head {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
}
.oo-dialog-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--oo-radius-sm);
  background: var(--oo-brand-soft);
  color: var(--oo-brand);
}
.oo-dialog-title {
  margin: 0;
  font-size: var(--oo-text-lg);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
}
.oo-dialog-desc {
  margin: 2px 0 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

@media (max-width: 560px) {
  .bz-stats {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
