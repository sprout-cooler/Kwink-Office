<script setup lang="ts">
/** 财务管理：收支流水 CRUD + 分类统计。 */
import { computed, onMounted, ref } from "vue";
import {
  bizApi,
  type BillImportBatch,
  type BizCapabilities,
  type BizExpense,
  type ExpenseTrend,
} from "@/api/biz-dashboard";
import {
  chartColor,
  chartSplitLineColor,
  chartTextColor,
  chartTooltipBg,
  chartTooltipBorder,
  chartTooltipTextColor,
} from "@/composables/chart-theme";
import {
  OOCard,
  OOEmptyState,
  OOIcon,
  OOPageHeader,
  OOSectionTitle,
  OOStatTile,
  OOToolbar,
} from "@/components/ui";
import BillImportDialog from "./BillImportDialog.vue";
import ChartBox from "./ChartBox.vue";

const items = ref<BizExpense[]>([]);
const customers = ref<{ id: number; name: string }[]>([]);
const caps = ref<BizCapabilities | null>(null);
const loading = ref(false);
const error = ref("");

// ---- 账单导入（v1.0.32）----
const importDialog = ref(false);
const batches = ref<BillImportBatch[]>([]);

const filterKind = ref("");
const filterCustomer = ref<number | undefined>(undefined);
/** 交易方关键字（模糊搜索；后端同时会匹配关联客户名以兼容历史流水） */
const filterCounterparty = ref("");
/** v1.0.34：时间范围 + 支付方式 */
const filterPayment = ref("");
const dateRange = ref<[string, string] | null>(null);
const paymentMethods = ref<string[]>([]);
const trendMonth = ref<ExpenseTrend>({ granularity: "month", buckets: [] });
const trendDay = ref<ExpenseTrend>({ granularity: "day", buckets: [] });
const exporting = ref(false);

const dateFromStr = () => dateRange.value?.[0] ?? "";
const dateToStr = () => dateRange.value?.[1] ?? "";

const dialog = ref(false);
const editing = ref<BizExpense | null>(null);
const form = ref({
  kind: "expense",
  category: "",
  amount: 0,
  occurredOn: new Date().toISOString().slice(0, 10),
  // 交易方：这笔钱跟谁发生的（自由文本，不要求在客户档案里建过档）
  counterparty: "",
  // 关联客户：这笔流水归属哪个客户档案（用于客户维度统计，与交易方是两回事）
  customerId: undefined as number | undefined,
  tripId: undefined as number | undefined,
  note: "",
});
const saving = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [list, cs, c, bs, pm] = await Promise.all([
      bizApi.listExpenses({
        kind: filterKind.value,
        customerId: filterCustomer.value,
        counterparty: filterCounterparty.value,
        paymentMethod: filterPayment.value,
        dateFrom: dateFromStr(),
        dateTo: dateToStr(),
      }),
      bizApi.listCustomers(),
      bizApi.capabilities(),
      bizApi.listBillImports(),
      bizApi.listPaymentMethods(),
    ]);
    items.value = list.items;
    customers.value = cs.items.map((x) => ({ id: x.id, name: x.name }));
    caps.value = c;
    batches.value = bs.items;
    paymentMethods.value = pm.items;
    // 趋势图跟随时间范围，但不跟随「类型/交易方」等维度筛选 ——
    // 趋势的意义是看整体走势，被维度切成残缺片段反而误导。
    const [tm, td] = await Promise.all([
      bizApi.expenseTrend({ granularity: "month", dateFrom: dateFromStr(), dateTo: dateToStr() }),
      bizApi.expenseTrend({ granularity: "day", dateFrom: dateFromStr(), dateTo: dateToStr() }),
    ]);
    trendMonth.value = tm;
    trendDay.value = td;
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

function openCreate() {
  editing.value = null;
  form.value = {
    kind: "expense",
    category: "",
    amount: 0,
    occurredOn: new Date().toISOString().slice(0, 10),
    counterparty: "",
    customerId: undefined,
    tripId: undefined,
    note: "",
  };
  dialog.value = true;
}

function openEdit(row: BizExpense) {
  editing.value = row;
  form.value = {
    kind: row.kind,
    category: row.category,
    amount: row.amount,
    occurredOn: row.occurredOn,
    counterparty: row.counterparty ?? "",
    customerId: row.customerId ?? undefined,
    tripId: row.tripId ?? undefined,
    note: row.note,
  };
  dialog.value = true;
}

async function save() {
  saving.value = true;
  error.value = "";
  try {
    if (editing.value) {
      await bizApi.updateExpense(editing.value.id, form.value);
    } else {
      await bizApi.createExpense(form.value);
    }
    dialog.value = false;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function remove(row: BizExpense) {
  error.value = "";
  try {
    await bizApi.deleteExpense(row.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

const totalIncome = computed(() =>
  items.value.filter((x) => x.kind === "income").reduce((s, x) => s + x.amount, 0),
);
const totalExpense = computed(() =>
  items.value.filter((x) => x.kind === "expense").reduce((s, x) => s + x.amount, 0),
);
const netAmount = computed(() => totalIncome.value - totalExpense.value);

const categoryOption = computed(() => {
  const agg: Record<string, number> = {};
  items.value
    .filter((x) => x.kind === "expense")
    .forEach((x) => {
      const k = x.category || "未分类";
      agg[k] = (agg[k] ?? 0) + x.amount;
    });
  const rows = Object.entries(agg).sort((a, b) => b[1] - a[1]);
  const text = chartTextColor();
  return {
    tooltip: {
      trigger: "item",
      backgroundColor: chartTooltipBg(),
      borderColor: chartTooltipBorder(),
      textStyle: { color: chartTooltipTextColor() },
    },
    legend: {
      orient: "vertical",
      right: 0,
      top: "center",
      textStyle: { color: text },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["34%", "50%"],
        avoidLabelOverlap: true,
        label: { color: text, fontSize: 12 },
        itemStyle: { borderRadius: 6 },
        data: rows.map(([name, value], i) => ({
          name,
          value,
          itemStyle: { color: chartColor(i) },
        })),
      },
    ],
  };
});

// ---- v1.0.34 趋势图与支付方式构成 ----
// 收入用调色板第 2 色（青绿）、支出用第 4 色（粉红）：
// 深浅两套色板在这两个位置都是「绿 / 红」观感，符合收支直觉，且自动跟随主题。
const INCOME_COLOR = () => chartColor(1);
const EXPENSE_COLOR = () => chartColor(3);

function axisTooltip() {
  return {
    trigger: "axis",
    backgroundColor: chartTooltipBg(),
    borderColor: chartTooltipBorder(),
    textStyle: { color: chartTooltipTextColor() },
  };
}

function categoryAxis(labels: string[]) {
  const text = chartTextColor();
  return {
    type: "category" as const,
    data: labels,
    axisLabel: { color: text, fontSize: 11 },
    axisLine: { lineStyle: { color: chartSplitLineColor() } },
    axisTick: { show: false },
  };
}

function valueAxis() {
  const text = chartTextColor();
  return {
    type: "value" as const,
    axisLabel: { color: text, fontSize: 11 },
    splitLine: { lineStyle: { color: chartSplitLineColor() } },
  };
}

const trendMonthOption = computed(() => {
  const b = trendMonth.value.buckets;
  return {
    tooltip: axisTooltip(),
    legend: {
      data: ["收入", "支出"],
      textStyle: { color: chartTextColor() },
      itemWidth: 10,
      itemHeight: 10,
      top: 0,
    },
    grid: { left: 4, right: 12, top: 36, bottom: 4, containLabel: true },
    xAxis: categoryAxis(b.map((x) => x.label)),
    yAxis: valueAxis(),
    series: [
      {
        name: "收入",
        type: "bar",
        data: b.map((x) => x.income),
        itemStyle: { color: INCOME_COLOR(), borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "支出",
        type: "bar",
        data: b.map((x) => x.expense),
        itemStyle: { color: EXPENSE_COLOR(), borderRadius: [4, 4, 0, 0] },
      },
    ],
  };
});

const trendDayOption = computed(() => {
  // 近 30 天：日报的粒度太细，只取最后 30 个点，否则 x 轴挤成一团
  const b = trendDay.value.buckets.slice(-30);
  return {
    tooltip: axisTooltip(),
    legend: {
      data: ["收入", "支出"],
      textStyle: { color: chartTextColor() },
      itemWidth: 10,
      itemHeight: 10,
      top: 0,
    },
    grid: { left: 4, right: 12, top: 36, bottom: 4, containLabel: true },
    xAxis: categoryAxis(b.map((x) => x.key.slice(5))),
    yAxis: valueAxis(),
    series: [
      {
        name: "收入",
        type: "line",
        smooth: true,
        showSymbol: false,
        data: b.map((x) => x.income),
        itemStyle: { color: INCOME_COLOR() },
        areaStyle: { opacity: 0.12 },
      },
      {
        name: "支出",
        type: "line",
        smooth: true,
        showSymbol: false,
        data: b.map((x) => x.expense),
        itemStyle: { color: EXPENSE_COLOR() },
        areaStyle: { opacity: 0.12 },
      },
    ],
  };
});

const paymentOption = computed(() => {
  const agg: Record<string, number> = {};
  items.value
    .filter((x) => x.kind === "expense")
    .forEach((x) => {
      const k = x.paymentMethod || "未记录";
      agg[k] = (agg[k] ?? 0) + x.amount;
    });
  const rows = Object.entries(agg).sort((a, b) => b[1] - a[1]);
  const text = chartTextColor();
  return {
    tooltip: {
      trigger: "item",
      backgroundColor: chartTooltipBg(),
      borderColor: chartTooltipBorder(),
      textStyle: { color: chartTooltipTextColor() },
    },
    legend: {
      orient: "vertical",
      right: 0,
      top: "center",
      textStyle: { color: text },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["34%", "50%"],
        avoidLabelOverlap: true,
        label: { color: text, fontSize: 12 },
        itemStyle: { borderRadius: 6 },
        data: rows.map(([name, value], i) => ({
          name,
          value,
          itemStyle: { color: chartColor(i) },
        })),
      },
    ],
  };
});

async function exportXlsx() {
  exporting.value = true;
  error.value = "";
  try {
    await bizApi.exportExpenses({
      kind: filterKind.value,
      customerId: filterCustomer.value,
      dateFrom: dateFromStr(),
      dateTo: dateToStr(),
      counterparty: filterCounterparty.value,
      paymentMethod: filterPayment.value,
    });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    exporting.value = false;
  }
}

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
</script>

<template>
  <div>
    <OOPageHeader title="财务管理" description="记录日常收支流水，支持导入支付宝/微信账单，并按类别统计支出构成">
      <el-button @click="importDialog = true">
        <OOIcon name="upload" :size="16" style="margin-right: 6px; vertical-align: -2px" />
        导入账单
      </el-button>
      <el-button type="primary" @click="openCreate">
        <OOIcon name="plus" :size="16" style="margin-right: 6px; vertical-align: -2px" />
        新增流水
      </el-button>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <div class="bz-kpis">
      <OOStatTile
        label="收入合计"
        icon="↑"
        tone="green"
        :value="money(totalIncome)"
        hint="当前筛选范围内"
      />
      <OOStatTile
        label="支出合计"
        icon="↓"
        tone="red"
        :value="money(totalExpense)"
        hint="当前筛选范围内"
      />
      <OOStatTile
        label="净额"
        icon="Σ"
        tone="brand"
        :value="money(netAmount)"
        hint="收入 − 支出"
      />
      <OOStatTile
        label="流水条数"
        icon="N"
        tone="purple"
        :value="items.length"
        hint="当前筛选范围内"
      />
    </div>

    <OOCard flush class="mb">
      <OOToolbar hint="按交易方、类型或关联客户筛选">
        <template #left>
          <el-input
            v-model="filterCounterparty"
            placeholder="交易方（关键字）"
            clearable
            class="w180"
            @keyup.enter="load"
            @clear="load"
          />
          <el-select v-model="filterKind" placeholder="全部类型" clearable class="w180" @change="load">
            <el-option
              v-for="k in caps?.expenseKinds ?? []"
              :key="k.value"
              :label="k.label"
              :value="k.value"
            />
          </el-select>
          <el-select
            v-model="filterCustomer"
            placeholder="关联客户"
            clearable
            class="w180"
            @change="load"
          >
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select
            v-model="filterPayment"
            placeholder="支付方式"
            clearable
            class="w180"
            @change="load"
          >
            <el-option v-for="p in paymentMethods" :key="p" :label="p" :value="p" />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            class="bz-range"
            @change="load"
          />
        </template>
        <template #right>
          <span class="bz-sum">收入 <b class="oo-num">{{ money(totalIncome) }}</b></span>
          <span class="bz-sum">支出 <b class="oo-num">{{ money(totalExpense) }}</b></span>
          <el-button :loading="exporting" @click="exportXlsx">
            <OOIcon name="download" :size="15" style="margin-right: 5px; vertical-align: -2px" />
            导出 XLSX
          </el-button>
        </template>
      </OOToolbar>

      <div class="bz-charts">
        <OOCard title="月度收支趋势" subtitle="按月份汇总，看整体走势">
          <ChartBox type="bar" :option="trendMonthOption" height="250px" />
        </OOCard>
        <OOCard title="近 30 日走势" subtitle="按天汇总">
          <ChartBox type="line" :option="trendDayOption" height="250px" />
        </OOCard>
        <OOCard title="支出分类构成" subtitle="钱花在哪">
          <ChartBox type="pie" :option="categoryOption" height="250px" />
        </OOCard>
        <OOCard title="支付方式构成" subtitle="钱从哪个渠道出去">
          <ChartBox type="pie" :option="paymentOption" height="250px" />
        </OOCard>
      </div>

      <OOCard title="流水明细" :subtitle="`共 ${items.length} 条`" flush class="bz-table-card">
          <el-table :data="items" size="small" v-loading="loading" max-height="320">
            <template #empty>
              <OOEmptyState variant="inbox" title="暂无流水" description="调整筛选条件，或新增一条流水记录" />
            </template>
            <el-table-column prop="occurredOn" label="日期" width="105" />
            <el-table-column label="类型" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="row.kind === 'income' ? 'success' : 'danger'" effect="light">
                  {{ row.kind === "income" ? "收入" : "支出" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="类别" width="90">
              <template #default="{ row }">{{ row.category || "未分类" }}</template>
            </el-table-column>
            <el-table-column label="交易方" min-width="120">
              <template #default="{ row }">
                <!-- 交易方为空说明是 v1.0.32 之前录入的流水（当时只记了关联客户），
                     回落到客户名做读时兼容，避免历史数据在这一列全变成「—」 -->
                {{
                  row.counterparty ||
                  customers.find((c) => c.id === row.customerId)?.name ||
                  "—"
                }}
              </template>
            </el-table-column>
            <el-table-column label="支付方式" width="110">
              <template #default="{ row }">{{ row.paymentMethod || "—" }}</template>
            </el-table-column>
            <el-table-column label="金额" width="110" align="right">
              <template #default="{ row }">
                <span class="oo-num">{{ money(row.amount) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
                <el-popconfirm title="删除该条流水？" @confirm="remove(row)">
                  <template #reference>
                    <el-button link type="danger" size="small">删除</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </OOCard>
    </OOCard>

    <OOCard
      v-if="batches.length"
      title="账单导入记录"
      :subtitle="`共 ${batches.length} 次导入`"
      flush
      class="mb"
    >
      <OOToolbar hint="撤销会删除该批次导入的全部流水" dense />
      <el-table :data="batches" size="small">
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

    <el-dialog v-model="dialog" width="560px" align-center>
      <template #header>
        <div class="oo-dialog-head">
          <span class="oo-dialog-icon"><OOIcon name="wallet" :size="18" /></span>
          <div>
            <h3 class="oo-dialog-title">{{ editing ? "编辑流水" : "新增流水" }}</h3>
            <p class="oo-dialog-desc">金额单位为元，可填写两位小数</p>
          </div>
        </div>
      </template>
      <el-form label-width="80px">
        <el-form-item label="类型">
          <el-radio-group v-model="form.kind">
            <el-radio-button value="expense">支出</el-radio-button>
            <el-radio-button value="income">收入</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="金额" required>
          <el-input-number v-model="form.amount" :min="0" :step="100" :precision="2" />
        </el-form-item>
        <el-form-item label="类别">
          <el-select
            v-model="form.category"
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入类别"
            class="w-full"
          >
            <el-option
              v-for="c in caps?.expenseCategories ?? []"
              :key="c"
              :label="c"
              :value="c"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="form.occurredOn" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="交易方">
          <el-input v-model="form.counterparty" placeholder="这笔钱跟谁发生的，如：永辉超市（可留空）" />
        </el-form-item>
        <el-form-item label="关联客户">
          <el-select
            v-model="form.customerId"
            clearable
            placeholder="归属哪个客户档案（可选，用于客户维度统计）"
            class="w-full"
          >
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bz-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr));
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-5);
}

.bz-charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--oo-space-4);
  padding: var(--oo-space-4);
}

.bz-table-card {
  margin: 0 var(--oo-space-4) var(--oo-space-4);
}

.bz-range {
  width: 250px;
}

.bz-sum {
  font-size: var(--oo-text-sm);
  color: var(--oo-text-secondary);
}
.bz-sum b {
  color: var(--oo-text-primary);
  font-weight: var(--oo-weight-semibold);
}
.w180 {
  width: 180px;
}
.w-full {
  width: 100%;
}
.mb {
  margin-bottom: var(--oo-space-5);
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

@media (max-width: 900px) {
  .bz-charts {
    grid-template-columns: 1fr;
  }
  .bz-range {
    width: 100%;
  }
}

@media (max-width: 560px) {
  .bz-kpis {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--oo-space-2);
  }
  .bz-charts {
    padding: var(--oo-space-3);
  }
  .bz-table-card {
    margin: 0 var(--oo-space-3) var(--oo-space-3);
  }
}
</style>
