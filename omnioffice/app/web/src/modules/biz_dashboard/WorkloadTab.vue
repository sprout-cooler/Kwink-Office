<script setup lang="ts">
/** 工作量：双口径（周报工时只读 + 独立台账）。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizTimeEntry, type WorkloadOverview } from "@/api/biz-dashboard";
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
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["周报工时", "台账工时"], top: 0 },
    grid: { left: 44, right: 16, top: 32, bottom: 28 },
    xAxis: { type: "category", data: b.map((x) => x.label) },
    yAxis: { type: "value", name: "小时" },
    series: [
      {
        name: "周报工时",
        type: "bar",
        stack: "t",
        data: b.map((x) => x.weeklyHours),
        itemStyle: { color: "#378ADD" },
      },
      {
        name: "台账工时",
        type: "bar",
        stack: "t",
        data: b.map((x) => x.manualHours),
        itemStyle: { color: "#5DCAA5" },
      },
    ],
  };
});

const customerOption = computed(() => {
  const rows = data.value?.byCustomer ?? [];
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 110, right: 24, top: 16, bottom: 28 },
    xAxis: { type: "value", name: "小时" },
    yAxis: {
      type: "category",
      data: rows.map((r) => r.customerName).reverse(),
    },
    series: [
      {
        type: "bar",
        data: rows.map((r) => r.hours).reverse(),
        itemStyle: { color: "#639922" },
      },
    ],
  };
});
</script>

<template>
  <div class="bz-workload">
    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
      show-icon
      class="mb"
    />

    <el-card shadow="never" class="mb">
      <template #header>
        <div class="hdr">
          <span>登记工时（独立台账）</span>
          <el-radio-group v-model="granularity" size="small" @change="load">
            <el-radio-button value="day">按日</el-radio-button>
            <el-radio-button value="week">按周</el-radio-button>
            <el-radio-button value="month">按月</el-radio-button>
          </el-radio-group>
        </div>
      </template>
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
    </el-card>

    <el-row :gutter="16">
      <el-col :span="24" :md="12">
        <el-card shadow="never">
          <template #header>工时趋势</template>
          <ChartBox type="bar" :option="trendOption" height="260px" />
        </el-card>
      </el-col>
      <el-col :span="24" :md="12">
        <el-card shadow="never">
          <template #header>客户工时排行</template>
          <ChartBox type="bar" :option="customerOption" height="260px" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="mt">
      <template #header>工时台账明细</template>
      <el-table :data="entries" size="small" empty-text="暂无台账工时记录" v-loading="loading">
        <el-table-column prop="taskDate" label="日期" width="110" />
        <el-table-column prop="title" label="事项" />
        <el-table-column prop="hours" label="工时(h)" width="90" align="right" />
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
    </el-card>
  </div>
</template>

<style scoped>
.hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.bz-form-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.f-title {
  flex: 1 1 240px;
}
.f-cust {
  width: 180px;
}
.bz-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.mb {
  margin-bottom: 16px;
}
.mt {
  margin-top: 16px;
}
</style>
