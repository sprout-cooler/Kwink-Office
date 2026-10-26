<script setup lang="ts">
/** 总览看板：大屏首屏 KPI + 关键图表。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizOverview } from "@/api/biz-dashboard";
import ChartBox from "./ChartBox.vue";
import { OOCard, OOEmptyState, OOPageHeader, OOStatTile } from "@/components/ui";
import {
  chartColor,
  chartPalette,
  chartSplitLineColor,
  chartTextColor,
  chartTooltipBg,
  chartTooltipBorder,
  chartTooltipTextColor,
} from "@/composables/chart-theme";

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

/** 图表公共配置：坐标轴/提示框随深浅色主题切换 */
function baseOption() {
  const text = chartTextColor();
  const split = chartSplitLineColor();
  return {
    tooltip: {
      trigger: "axis",
      backgroundColor: chartTooltipBg(),
      borderColor: chartTooltipBorder(),
      textStyle: { color: chartTooltipTextColor(), fontSize: 12 },
    },
    textStyle: { color: text },
  };
}

/** 工时趋势（双口径堆叠） */
const workloadOption = computed(() => {
  const buckets = overview.value?.workload.buckets ?? [];
  const base = baseOption();
  return {
    ...base,
    legend: {
      data: ["周报工时", "台账工时"],
      top: 0,
      textStyle: { color: chartTextColor() },
      itemWidth: 8,
      itemHeight: 8,
      icon: "circle",
    },
    grid: { left: 40, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: "category",
      data: buckets.map((b) => b.label),
      axisLine: { lineStyle: { color: chartSplitLineColor() } },
      axisLabel: { color: chartTextColor() },
    },
    yAxis: {
      type: "value",
      name: "小时",
      nameTextStyle: { color: chartTextColor() },
      axisLabel: { color: chartTextColor() },
      splitLine: { lineStyle: { color: chartSplitLineColor() } },
    },
    series: [
      {
        name: "周报工时",
        type: "bar",
        stack: "total",
        data: buckets.map((b) => b.weeklyHours),
        itemStyle: { color: chartColor(0), borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "台账工时",
        type: "bar",
        stack: "total",
        data: buckets.map((b) => b.manualHours),
        itemStyle: { color: chartColor(1), borderRadius: [4, 4, 0, 0] },
      },
    ],
  };
});

/** 客户工时分布 */
const customerOption = computed(() => {
  const rows = (overview.value?.workload.byCustomer ?? []).slice(0, 8);
  const base = baseOption();
  const palette = chartPalette();
  return {
    ...base,
    tooltip: { ...base.tooltip, trigger: "item" },
    legend: {
      orient: "vertical",
      right: 0,
      top: "center",
      textStyle: { color: chartTextColor() },
      itemWidth: 8,
      itemHeight: 8,
      icon: "circle",
    },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["38%", "50%"],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 6, borderWidth: 2, borderColor: "transparent" },
        label: { color: chartTextColor(), fontSize: 12 },
        data: rows.map((r, i) => ({
          name: r.customerName,
          value: r.hours,
          itemStyle: { color: palette[i % palette.length] },
        })),
      },
    ],
  };
});

/** 出差按月 */
const tripOption = computed(() => {
  const rows = overview.value?.tripsByMonth ?? [];
  const base = baseOption();
  return {
    ...base,
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: "category",
      data: rows.map((r) => r.label),
      axisLine: { lineStyle: { color: chartSplitLineColor() } },
      axisLabel: { color: chartTextColor() },
    },
    yAxis: {
      type: "value",
      name: "次",
      nameTextStyle: { color: chartTextColor() },
      axisLabel: { color: chartTextColor() },
      splitLine: { lineStyle: { color: chartSplitLineColor() } },
    },
    series: [
      {
        name: "出差次数",
        type: "line",
        smooth: true,
        data: rows.map((r) => r.count),
        itemStyle: { color: chartColor(3) },
        lineStyle: { color: chartColor(3), width: 3 },
        areaStyle: { color: chartColor(3), opacity: 0.12 },
      },
    ],
  };
});
</script>

<template>
  <div class="bz-overview">
    <OOPageHeader
      title="总览看板"
      description="客户、出差、工时与收支的一屏概览，数据来自业务大屏实时统计"
      badge="📊"
    >
      <el-button :loading="loading" @click="load">
        <span class="oo-btn-icon">↻</span>
        刷新
      </el-button>
    </OOPageHeader>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
      show-icon
      class="oo-mb-4"
    />

    <div class="bz-kpis">
      <OOStatTile
        label="客户数"
        icon="👥"
        tone="brand"
        :value="overview?.customers ?? 0"
      />
      <OOStatTile
        label="出差次数"
        icon="✈️"
        tone="purple"
        :value="overview?.trips ?? 0"
      />
      <OOStatTile
        label="总工时"
        icon="⏱"
        tone="teal"
        :value="hours(overview?.workload.totalHours ?? 0)"
      />
      <OOStatTile
        label="收入"
        icon="↑"
        tone="green"
        :value="money(overview?.totalIncome ?? 0)"
      />
      <OOStatTile
        label="支出"
        icon="↓"
        tone="amber"
        :value="money(overview?.totalExpense ?? 0)"
      />
      <OOStatTile
        label="结余"
        icon="◎"
        tone="pink"
        :value="money(overview?.balance ?? 0)"
        :hint="(overview?.balance ?? 0) >= 0 ? '本期盈余' : '本期超支'"
      />
    </div>

    <div class="bz-grid">
      <OOCard title="工作量趋势" subtitle="周报工时 + 台账工时双口径">
        <ChartBox type="bar" :option="workloadOption" height="280px" />
      </OOCard>

      <OOCard title="客户工时分布" subtitle="工时占比前 8 位客户">
        <ChartBox type="pie" :option="customerOption" height="280px" />
      </OOCard>

      <OOCard title="出差频次" subtitle="按月统计出差次数">
        <ChartBox type="line" :option="tripOption" height="240px" />
      </OOCard>

      <OOCard title="近期客户" subtitle="最近录入的客户档案" flush>
        <el-table
          v-if="(overview?.topCustomers ?? []).length"
          :data="overview?.topCustomers ?? []"
          size="small"
          empty-text="暂无客户"
        >
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="industry" label="行业" width="120" />
          <el-table-column prop="status" label="状态" width="90" />
        </el-table>
        <OOEmptyState
          v-else
          variant="users"
          title="暂无客户"
          description="在「客户管理」中新增客户后，这里会显示最近的客户档案"
        />
      </OOCard>
    </div>
  </div>
</template>

<style scoped>
.bz-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-5);
}

.bz-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: var(--oo-space-4);
}

.oo-btn-icon {
  margin-right: 4px;
}

@media (max-width: 900px) {
  .bz-grid {
    grid-template-columns: 1fr;
  }
}

/* 窄屏：KPI 改两列，避免单列时每张卡过高、需大量滚动 */
@media (max-width: 560px) {
  .bz-kpis {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--oo-space-2);
  }
}
</style>
