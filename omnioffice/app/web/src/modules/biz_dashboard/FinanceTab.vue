<script setup lang="ts">
/** 财务管理：收支流水 CRUD + 分类统计。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizCapabilities, type BizExpense } from "@/api/biz-dashboard";
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

const categoryOption = computed(() => {
  const agg: Record<string, number> = {};
  items.value
    .filter((x) => x.kind === "expense")
    .forEach((x) => {
      const k = x.category || "未分类";
      agg[k] = (agg[k] ?? 0) + x.amount;
    });
  const rows = Object.entries(agg).sort((a, b) => b[1] - a[1]);
  return {
    tooltip: { trigger: "item" },
    legend: { orient: "vertical", right: 0, top: "center" },
    series: [
      {
        type: "pie",
        radius: ["40%", "66%"],
        center: ["36%", "50%"],
        data: rows.map(([name, value]) => ({ name, value })),
      },
    ],
  };
});

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
</script>

<template>
  <div>
    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <div class="bz-toolbar">
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
      <el-button type="primary" @click="openCreate">新增流水</el-button>
      <span class="bz-spacer" />
      <span class="bz-sum">收入 <b>{{ money(totalIncome) }}</b></span>
      <span class="bz-sum">支出 <b>{{ money(totalExpense) }}</b></span>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :span="24" :md="10">
        <el-card shadow="never">
          <template #header>支出分类构成</template>
          <ChartBox type="pie" :option="categoryOption" height="260px" />
        </el-card>
      </el-col>
      <el-col :span="24" :md="14">
        <el-card shadow="never">
          <template #header>流水明细</template>
          <el-table :data="items" size="small" v-loading="loading" empty-text="暂无流水" max-height="260">
            <el-table-column prop="occurredOn" label="日期" width="105" />
            <el-table-column label="类型" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="row.kind === 'income' ? 'success' : 'danger'">
                  {{ row.kind === "income" ? "收入" : "支出" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="category" label="类别" width="90" />
            <el-table-column label="客户" min-width="110">
              <template #default="{ row }">
                {{ customers.find((c) => c.id === row.customerId)?.name ?? "—" }}
              </template>
            </el-table-column>
            <el-table-column label="金额" width="110" align="right">
              <template #default="{ row }">{{ money(row.amount) }}</template>
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
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dialog" :title="editing ? '编辑流水' : '新增流水'" width="560px">
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
.bz-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.bz-spacer {
  flex: 1;
}
.bz-sum {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.w180 {
  width: 180px;
}
.w-full {
  width: 100%;
}
.mb {
  margin-bottom: 16px;
}
</style>
