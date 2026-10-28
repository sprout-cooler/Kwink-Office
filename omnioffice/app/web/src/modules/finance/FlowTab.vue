<script setup lang="ts">
/** 财务 · 流水明细：收支 CRUD、多条件筛选、XLSX 导出。
 *
 * v1.0.35 从原「财务管理」Tab 拆出成为财务一级模块的第 1 个子页。
 * 与「趋势分析」页的分工：这里管**明细与录入**，那里管**汇总与走势**。
 */
import { computed, onMounted, ref } from "vue";
import {
  bizApi,
  type BizCapabilities,
  type BizExpense,
} from "@/api/biz-dashboard";
import {
  OOCard,
  OOEmptyState,
  OOIcon,
  OOPageHeader,
  OOStatTile,
  OOToolbar,
} from "@/components/ui";

const items = ref<BizExpense[]>([]);
const customers = ref<{ id: number; name: string }[]>([]);
const caps = ref<BizCapabilities | null>(null);
const loading = ref(false);
const error = ref("");

const filterKind = ref("");
const filterCustomer = ref<number | undefined>(undefined);
/** 交易方关键字（模糊搜索；后端同时会匹配关联客户名以兼容历史流水） */
const filterCounterparty = ref("");
/** 支付方式（精确匹配） */
const filterPayment = ref("");
const dateRange = ref<[string, string] | null>(null);
const paymentMethods = ref<string[]>([]);
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
    const [list, cs, c, pm] = await Promise.all([
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
      bizApi.listPaymentMethods(),
    ]);
    items.value = list.items;
    customers.value = cs.items.map((x) => ({ id: x.id, name: x.name }));
    caps.value = c;
    paymentMethods.value = pm.items;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

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

const totalIncome = computed(() =>
  items.value.filter((x) => x.kind === "income").reduce((s, x) => s + x.amount, 0),
);
const totalExpense = computed(() =>
  items.value.filter((x) => x.kind === "expense").reduce((s, x) => s + x.amount, 0),
);
const netAmount = computed(() => totalIncome.value - totalExpense.value);

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
</script>

<template>
  <div>
    <OOPageHeader
      title="流水明细"
      description="记录日常收支流水，按交易方、类型、支付方式与时间范围筛选，并导出对账表"
    >
      <el-button type="primary" @click="openCreate">
        <OOIcon name="plus" :size="16" style="margin-right: 6px; vertical-align: -2px" />
        新增流水
      </el-button>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <div class="bz-kpis">
      <OOStatTile label="收入合计" icon="↑" tone="green" :value="money(totalIncome)" hint="当前筛选范围内" />
      <OOStatTile label="支出合计" icon="↓" tone="red" :value="money(totalExpense)" hint="当前筛选范围内" />
      <OOStatTile label="净额" icon="Σ" tone="brand" :value="money(netAmount)" hint="收入 − 支出" />
      <OOStatTile label="流水条数" icon="N" tone="purple" :value="items.length" hint="当前筛选范围内" />
    </div>

    <OOCard flush>
      <OOToolbar hint="按交易方、类型、关联客户、支付方式与时间筛选">
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
          <el-select v-model="filterCustomer" placeholder="关联客户" clearable class="w180" @change="load">
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select v-model="filterPayment" placeholder="支付方式" clearable class="w180" @change="load">
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

      <el-table :data="items" size="small" v-loading="loading" max-height="520">
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
            {{ row.counterparty || customers.find((c) => c.id === row.customerId)?.name || "—" }}
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
            <el-option v-for="c in caps?.expenseCategories ?? []" :key="c" :label="c" :value="c" />
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
.bz-range {
  width: 250px;
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
@media (max-width: 560px) {
  .bz-kpis {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--oo-space-2);
  }
  .bz-range {
    width: 100%;
  }
}
</style>
