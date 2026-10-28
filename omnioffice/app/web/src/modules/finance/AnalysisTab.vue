<script setup lang="ts">
/** 财务 · 趋势分析：收支走势与构成。
 *
 * v1.0.35 新增页。与「流水明细」页的分工：那边看**单条**与录入，
 * 这边看**汇总**与走势。
 *
 * 趋势图只跟随时间范围筛选，**不跟随**类型/交易方等维度筛选 ——
 * 趋势的意义是看整体走势，被维度切成残缺片段反而误导。
 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizExpense, type ExpenseTrend } from "@/api/biz-dashboard";
import {
  chartColor,
  chartSplitLineColor,
  chartTextColor,
  chartTooltipBg,
  chartTooltipBorder,
  chartTooltipTextColor,
} from "@/composables/chart-theme";
import { OOCard, OOPageHeader, OOToolbar } from "@/components/ui";
import ChartBox from "@/modules/biz_dashboard/ChartBox.vue";

const trendMonth = ref<ExpenseTrend>({ granularity: "month", buckets: [] });
const trendDay = ref<ExpenseTrend>({ granularity: "day", buckets: [] });
const items = ref<BizExpense[]>([]);
const dateRange = ref<[string, string] | null>(null);
const loading = ref(false);
const error = ref("");

const dateFromStr = () => dateRange.value?.[0] ?? "";
const dateToStr = () => dateRange.value?.[1] ?? "";

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [tm, td, list] = await Promise.all([
      bizApi.expenseTrend({ granularity: "month", dateFrom: dateFromStr(), dateTo: dateToStr() }),
      bizApi.expenseTrend({ granularity: "day", dateFrom: dateFromStr(), dateTo: dateToStr() }),
      bizApi.listExpenses({ dateFrom: dateFromStr(), dateTo: dateToStr() }),
    ]);
    trendMonth.value = tm;
    trendDay.value = td;
    items.value = list.items;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

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

function pieOption(pairs: [string, number][]) {
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
        data: pairs.map(([name, value], i) => ({
          name,
          value,
          itemStyle: { color: chartColor(i) },
        })),
      },
    ],
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

/** 支出分类构成：按类别聚合。 */
const categoryOption = computed(() => {
  const agg: Record<string, number> = {};
  items.value
    .filter((x) => x.kind === "expense")
    .forEach((x) => {
      const k = x.category || "未分类";
      agg[k] = (agg[k] ?? 0) + x.amount;
    });
  return pieOption(Object.entries(agg).sort((a, b) => b[1] - a[1]) as [string, number][]);
});

/** 支付方式构成：钱从哪个渠道出去。 */
const paymentOption = computed(() => {
  const agg: Record<string, number> = {};
  items.value
    .filter((x) => x.kind === "expense")
    .forEach((x) => {
      const k = x.paymentMethod || "未记录";
      agg[k] = (agg[k] ?? 0) + x.amount;
    });
  return pieOption(Object.entries(agg).sort((a, b) => b[1] - a[1]) as [string, number][]);
});
</script>

<template>
  <div>
    <OOPageHeader title="趋势分析" description="按月/按天看收支走势，并从类别与支付渠道两个角度拆解支出构成">
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        class="bz-range"
        @change="load"
      />
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <OOCard flush class="mb">
      <OOToolbar hint="趋势不受类型/交易方等维度筛选影响，只跟随时间范围" dense />
      <div class="bz-charts" v-loading="loading">
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
    </OOCard>
  </div>
</template>

<style scoped>
.bz-charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--oo-space-4);
  padding: var(--oo-space-4);
}
.bz-range {
  width: 250px;
}
.mb {
  margin-bottom: var(--oo-space-5);
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
  .bz-charts {
    padding: var(--oo-space-3);
  }
}
</style>
