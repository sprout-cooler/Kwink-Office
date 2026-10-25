<script setup lang="ts">
/** 总览看板：大屏首屏 KPI + 关键图表。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizOverview } from "@/api/biz-dashboard";
import ChartBox from "./ChartBox.vue";

const overview = ref<BizOverview | null>(null);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    overview.value = await bizApi.overview();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const hours = (n: number) => `${Number(n || 0).toFixed(1)} h`;

/** 工时趋势（双口径堆叠） */
const workloadOption = computed(() => {
  const buckets = overview.value?.workload.buckets ?? [];
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["周报工时", "台账工时"], top: 0 },
    grid: { left: 40, right: 16, top: 32, bottom: 28 },
    xAxis: { type: "category", data: buckets.map((b) => b.label) },
    yAxis: { type: "value", name: "小时" },
    series: [
      {
        name: "周报工时",
        type: "bar",
        stack: "total",
        data: buckets.map((b) => b.weeklyHours),
        itemStyle: { color: "#378ADD" },
      },
      {
        name: "台账工时",
        type: "bar",
        stack: "total",
        data: buckets.map((b) => b.manualHours),
        itemStyle: { color: "#5DCAA5" },
      },
    ],
  };
});

/** 客户工时分布 */
const customerOption = computed(() => {
  const rows = (overview.value?.workload.byCustomer ?? []).slice(0, 8);
  return {
    tooltip: { trigger: "item" },
    legend: { orient: "vertical", right: 0, top: "center" },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["38%", "50%"],
        avoidLabelOverlap: true,
        data: rows.map((r) => ({ name: r.customerName, value: r.hours })),
      },
    ],
  };
});

/** 出差按月 */
const tripOption = computed(() => {
  const rows = overview.value?.tripsByMonth ?? [];
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    xAxis: { type: "category", data: rows.map((r) => r.label) },
    yAxis: { type: "value", name: "次" },
    series: [
      {
        type: "line",
        smooth: true,
        data: rows.map((r) => r.count),
        itemStyle: { color: "#D4537E" },
        areaStyle: { color: "rgba(212,83,126,0.12)" },
      },
    ],
  };
});
</script>

<template>
  <div class="bz-overview">
    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
      show-icon
      class="mb"
    />

    <div v-loading="loading" class="bz-kpis">
      <div class="bz-kpi">
        <p class="bz-kpi-label">客户数</p>
        <p class="bz-kpi-value">{{ overview?.customers ?? 0 }}</p>
      </div>
      <div class="bz-kpi">
        <p class="bz-kpi-label">出差次数</p>
        <p class="bz-kpi-value">{{ overview?.trips ?? 0 }}</p>
      </div>
      <div class="bz-kpi">
        <p class="bz-kpi-label">总工时</p>
        <p class="bz-kpi-value">{{ hours(overview?.workload.totalHours ?? 0) }}</p>
      </div>
      <div class="bz-kpi">
        <p class="bz-kpi-label">收入</p>
        <p class="bz-kpi-value">{{ money(overview?.totalIncome ?? 0) }}</p>
      </div>
      <div class="bz-kpi">
        <p class="bz-kpi-label">支出</p>
        <p class="bz-kpi-value">{{ money(overview?.totalExpense ?? 0) }}</p>
      </div>
      <div class="bz-kpi">
        <p class="bz-kpi-label">结余</p>
        <p
          class="bz-kpi-value"
          :style="{ color: (overview?.balance ?? 0) >= 0 ? '#A32D2D' : '#3B6D11' }"
        >
          {{ money(overview?.balance ?? 0) }}
        </p>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="24" :md="12">
        <el-card shadow="never">
          <template #header>工作量趋势（周报 + 台账双口径）</template>
          <ChartBox type="bar" :option="workloadOption" height="280px" />
        </el-card>
      </el-col>
      <el-col :span="24" :md="12">
        <el-card shadow="never">
          <template #header>客户工时分布</template>
          <ChartBox type="pie" :option="customerOption" height="280px" />
        </el-card>
      </el-col>
      <el-col :span="24" :md="12">
        <el-card shadow="never">
          <template #header>出差频次（按月）</template>
          <ChartBox type="line" :option="tripOption" height="240px" />
        </el-card>
      </el-col>
      <el-col :span="24" :md="12">
        <el-card shadow="never">
          <template #header>近期客户</template>
          <el-table :data="overview?.topCustomers ?? []" size="small" empty-text="暂无客户">
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="industry" label="行业" width="120" />
            <el-table-column prop="status" label="状态" width="90" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.bz-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.bz-kpi {
  background: var(--el-fill-color-light);
  border-radius: var(--el-border-radius-md);
  padding: 1rem;
}
.bz-kpi-label {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.bz-kpi-value {
  margin: 0;
  font-size: 24px;
  font-weight: 500;
}
.mb {
  margin-bottom: 12px;
}
</style>
