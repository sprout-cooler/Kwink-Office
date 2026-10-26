<script setup lang="ts">
/** 工作量：双口径（周报工时只读 + 独立台账）。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizTimeEntry, type WorkloadOverview } from "@/api/biz-dashboard";
import { chartColor, chartTextColor, chartSplitLineColor } from "@/composables/chart-theme";
import { OOCard, OOEmptyState, OOPageHeader, OOStatTile, OOToolbar } from "@/components/ui";
import ChartBox from "./ChartBox.vue";

const data = ref<WorkloadOverview | null>(null);
const entries = ref<BizTimeEntry[]>([]);
const customers = ref<{ id: number; name: string }[]>([]);
const granularity = ref("month");
const loading = ref(true);
const error = ref("");

// 台账录入表单
const form = ref({
  title: "",
  hours: 0,
  taskDate: new Date().toISOString().slice(0, 10),
  customerId: undefined as number | undefined,
  note: "",
});
const saving = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [wl, list, cs] = await Promise.all([
      bizApi.workload(granularity.value),
      bizApi.listTimeEntries(),
      bizApi.listCustomers(),
    ]);
    data.value = wl;
    entries.value = list.items;
    customers.value = cs.items.map((c) => ({ id: c.id, name: c.name }));
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function addEntry() {
  if (!form.value.title.trim()) {
    error.value = "请填写工作事项";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await bizApi.createTimeEntry({
      title: form.value.title,
      hours: form.value.hours,
      taskDate: form.value.taskDate,
      customerId: form.value.customerId ?? null,
      note: form.value.note,
    });
    form.value.title = "";
    form.value.hours = 0;
    form.value.note = "";
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function removeEntry(id: number) {
  error.value = "";
  try {
    await bizApi.deleteTimeEntry(id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

const trendOption = computed(() => {
  const b = data.value?.buckets ?? [];
  const text = chartTextColor();
  const split = chartSplitLineColor();
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["周报工时", "台账工时"], top: 0, textStyle: { color: text } },
    grid: { left: 44, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: "category",
      data: b.map((x) => x.label),
      axisLabel: { color: text },
      axisLine: { lineStyle: { color: split } },
    },
    yAxis: {
      type: "value",
      name: "小时",
      nameTextStyle: { color: text },
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: split } },
    },
    series: [
      {
        name: "周报工时",
        type: "bar",
        stack: "t",
        barMaxWidth: 26,
        data: b.map((x) => x.weeklyHours),
        itemStyle: { color: chartColor(0), borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "台账工时",
        type: "bar",
        stack: "t",
        barMaxWidth: 26,
        data: b.map((x) => x.manualHours),
        itemStyle: { color: chartColor(1), borderRadius: [4, 4, 0, 0] },
      },
    ],
  };
});

const customerOption = computed(() => {
  const rows = data.value?.byCustomer ?? [];
  const text = chartTextColor();
  const split = chartSplitLineColor();
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 110, right: 24, top: 16, bottom: 28 },
    xAxis: {
      type: "value",
      name: "小时",
      nameTextStyle: { color: text },
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: split } },
    },
    yAxis: {
      type: "category",
      data: rows.map((r) => r.customerName).reverse(),
      axisLabel: { color: text },
      axisLine: { lineStyle: { color: split } },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 20,
        data: rows.map((r) => r.hours).reverse(),
        itemStyle: { color: chartColor(6), borderRadius: [0, 6, 6, 0] },
      },
    ],
  };
});

/** KPI 汇总：双口径合计与台账条数。 */
const weeklyTotal = computed(() =>
  (data.value?.buckets ?? []).reduce((s, x) => s + x.weeklyHours, 0),
);
const manualTotal = computed(() =>
  (data.value?.buckets ?? []).reduce((s, x) => s + x.manualHours, 0),
);
const grandTotal = computed(() => weeklyTotal.value + manualTotal.value);
</script>

<template>
  <div class="bz-workload">
    <OOPageHeader
      title="工作量"
      description="双口径统计：周报工时来自周报识别结果（只读），台账工时在此单独登记"
    >
      <el-radio-group v-model="granularity" size="small" @change="load">
        <el-radio-button value="day">按日</el-radio-button>
        <el-radio-button value="week">按周</el-radio-button>
        <el-radio-button value="month">按月</el-radio-button>
      </el-radio-group>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <div class="bz-kpis">
      <OOStatTile
        label="周报工时"
        icon="W"
        tone="brand"
        :value="`${weeklyTotal.toFixed(1)} h`"
        hint="只读，来自周报识别结果"
      />
      <OOStatTile
        label="台账工时"
        icon="L"
        tone="teal"
        :value="`${manualTotal.toFixed(1)} h`"
        hint="独立台账登记"
      />
      <OOStatTile
        label="合计工时"
        icon="Σ"
        tone="purple"
        :value="`${grandTotal.toFixed(1)} h`"
        hint="双口径合并统计"
      />
      <OOStatTile
        label="台账条数"
        icon="N"
        tone="amber"
        :value="entries.length"
        hint="当前筛选范围内的记录"
      />
    </div>

    <OOCard title="登记工时（独立台账）" subtitle="填写事项与工时后登记，与周报数据互不影响" class="mb">
      <div class="bz-form-row">
        <el-input v-model="form.title" placeholder="工作事项（如：XX客户现场调试）" class="f-title" />
        <el-input-number v-model="form.hours" :min="0" :max="24" :step="0.5" placeholder="工时" />
        <el-date-picker
          v-model="form.taskDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="日期"
        />
        <el-select v-model="form.customerId" placeholder="归属客户（可选）" clearable class="f-cust">
          <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button type="primary" :loading="saving" @click="addEntry">登记</el-button>
      </div>
      <p class="bz-hint">
        周报工时来自周报识别结果（只读，不改动周报数据）；此处登记的是独立台账工时。
      </p>
    </OOCard>

    <div class="bz-charts">
      <OOCard title="工时趋势" subtitle="按当前时间粒度展示双口径堆叠">
        <ChartBox type="bar" :option="trendOption" height="260px" />
      </OOCard>
      <OOCard title="客户工时排行" subtitle="按客户维度合并统计">
        <ChartBox type="bar" :option="customerOption" height="260px" />
      </OOCard>
    </div>

    <OOCard title="工时台账明细" :subtitle="`共 ${entries.length} 条`" flush class="mt">
      <el-table :data="entries" size="small" v-loading="loading">
        <template #empty>
          <OOEmptyState variant="inbox" title="暂无台账工时记录" description="在上方登记第一条工时台账" />
        </template>
        <el-table-column prop="taskDate" label="日期" width="110" />
        <el-table-column prop="title" label="事项" min-width="180" />
        <el-table-column label="工时(h)" width="90" align="right">
          <template #default="{ row }">
            <span class="oo-num">{{ Number(row.hours).toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="归属客户" width="140">
          <template #default="{ row }">
            {{ customers.find((c) => c.id === row.customerId)?.name ?? "—" }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="removeEntry(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </OOCard>
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
  grid-template-columns: repeat(auto-fit, minmax(min(380px, 100%), 1fr));
  gap: var(--oo-space-4);
}

.bz-form-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oo-space-2);
}
.f-title {
  flex: 1 1 240px;
}
.f-cust {
  width: 180px;
}
.bz-hint {
  margin: var(--oo-space-3) 0 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}
.mb {
  margin-bottom: var(--oo-space-5);
}
.mt {
  margin-top: var(--oo-space-5);
}

@media (max-width: 560px) {
  .bz-kpis {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--oo-space-2);
  }
}
</style>
