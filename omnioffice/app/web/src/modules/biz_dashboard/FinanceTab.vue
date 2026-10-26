<script setup lang="ts">
/** 财务管理：收支流水 CRUD + 分类统计。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizCapabilities, type BizExpense } from "@/api/biz-dashboard";
import { chartColor, chartTextColor, chartTooltipBg, chartTooltipBorder, chartTooltipTextColor } from "@/composables/chart-theme";
import {
  OOCard,
  OOEmptyState,
  OOIcon,
  OOPageHeader,
  OOStatTile,
  OOToolbar,
} from "@/components/ui";
import ChartBox from "./ChartBox.vue";

const items = ref<BizExpense[]>([]);
const customers = ref<{ id: number; name: string }[]>([]);
const caps = ref<BizCapabilities | null>(null);
const loading = ref(false);
const error = ref("");

const filterKind = ref("");
const filterCustomer = ref<number | undefined>(undefined);

const dialog = ref(false);
const editing = ref<BizExpense | null>(null);
const form = ref({
  kind: "expense",
  category: "",
  amount: 0,
  occurredOn: new Date().toISOString().slice(0, 10),
  customerId: undefined as number | undefined,
  tripId: undefined as number | undefined,
  note: "",
});
const saving = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [list, cs, c] = await Promise.all([
      bizApi.listExpenses({ kind: filterKind.value, customerId: filterCustomer.value }),
      bizApi.listCustomers(),
      bizApi.capabilities(),
    ]);
    items.value = list.items;
    customers.value = cs.items.map((x) => ({ id: x.id, name: x.name }));
    caps.value = c;
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

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
</script>

<template>
  <div>
    <OOPageHeader title="财务管理" description="记录日常收支流水，并按类别统计支出构成">
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
      <OOToolbar hint="按类型与客户筛选">
        <template #left>
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
            placeholder="全部客户"
            clearable
            class="w180"
            @change="load"
          >
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </template>
        <template #right>
          <span class="bz-sum">收入 <b class="oo-num">{{ money(totalIncome) }}</b></span>
          <span class="bz-sum">支出 <b class="oo-num">{{ money(totalExpense) }}</b></span>
        </template>
      </OOToolbar>

      <div class="bz-grid">
        <OOCard title="支出分类构成" subtitle="仅统计支出类流水">
          <ChartBox type="pie" :option="categoryOption" height="280px" />
        </OOCard>

        <OOCard title="流水明细" :subtitle="`共 ${items.length} 条`" flush>
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
            <el-table-column label="客户" min-width="110">
              <template #default="{ row }">
                {{ customers.find((c) => c.id === row.customerId)?.name ?? "—" }}
              </template>
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
      </div>
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
        <el-form-item label="客户">
          <el-select v-model="form.customerId" clearable placeholder="选择客户（可选）" class="w-full">
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

.bz-grid {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--oo-space-4);
  padding: var(--oo-space-4);
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
  .bz-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .bz-kpis {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--oo-space-2);
  }
  .bz-grid {
    padding: var(--oo-space-3);
  }
}
</style>
