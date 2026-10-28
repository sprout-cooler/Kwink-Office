<script setup lang="ts">
/** 财务 · 分类与映射：自建类别概览 + 账单分类映射规则。
 *
 * 为什么需要映射规则：支付宝/微信导出的「交易分类」是**平台自己的口径**
 * （餐饮美食 / 交通出行 / 服饰装扮…），直接当财务类别会得到一堆和自建体系
 * 对不上的值，图表也被切得很碎。规则把「平台原始分类」转换成「我的类别」。
 *
 * 匹配规则（后端保证）：
 * - 多条命中时按优先级降序取第一条；
 * - 未命中任何规则的行**保留平台原始分类**（不猜）；
 * - 平台留空 = 通用规则，对所有平台生效。
 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizCategoryRule, type BizExpense } from "@/api/biz-dashboard";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOToolbar } from "@/components/ui";

const rules = ref<BizCategoryRule[]>([]);
const items = ref<BizExpense[]>([]);
const loading = ref(false);
const error = ref("");

const dialog = ref(false);
const editing = ref<BizCategoryRule | null>(null);
const form = ref({
  platform: "",
  pattern: "",
  matchMode: "contains" as "exact" | "contains",
  targetCategory: "",
  priority: 0,
  enabled: true,
});
const saving = ref(false);

const PLATFORM_OPTIONS = [
  { value: "", label: "通用（所有平台）" },
  { value: "alipay", label: "支付宝" },
  { value: "wechat", label: "微信支付" },
  { value: "unknown", label: "未识别平台" },
];

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [r, list] = await Promise.all([bizApi.listCategoryRules(), bizApi.listExpenses()]);
    rules.value = r.items;
    items.value = list.items;
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
    platform: "",
    pattern: "",
    matchMode: "contains",
    targetCategory: "",
    priority: 0,
    enabled: true,
  };
  dialog.value = true;
}

function openEdit(row: BizCategoryRule) {
  editing.value = row;
  form.value = {
    platform: row.platform,
    pattern: row.pattern,
    matchMode: row.matchMode,
    targetCategory: row.targetCategory,
    priority: row.priority,
    enabled: row.enabled,
  };
  dialog.value = true;
}

async function save() {
  saving.value = true;
  error.value = "";
  try {
    if (editing.value) {
      await bizApi.updateCategoryRule(editing.value.id, form.value);
    } else {
      await bizApi.createCategoryRule(form.value);
    }
    dialog.value = false;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function toggle(row: BizCategoryRule) {
  error.value = "";
  try {
    await bizApi.updateCategoryRule(row.id, { enabled: !row.enabled });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function remove(row: BizCategoryRule) {
  error.value = "";
  try {
    await bizApi.deleteCategoryRule(row.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

/** 现有类别概览：每个类别有多少条流水、合计多少钱。 */
const categorySummary = computed(() => {
  const agg: Record<string, { count: number; amount: number }> = {};
  items.value.forEach((x) => {
    const k = x.category || "未分类";
    const cur = agg[k] ?? { count: 0, amount: 0 };
    cur.count += 1;
    cur.amount += x.amount;
    agg[k] = cur;
  });
  return Object.entries(agg)
    .map(([name, v]) => ({ name, count: v.count, amount: v.amount }))
    .sort((a, b) => b.amount - a.amount);
});

const platformLabel = (code: string) =>
  PLATFORM_OPTIONS.find((p) => p.value === code)?.label ?? code;

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
</script>

<template>
  <div>
    <OOPageHeader
      title="分类与映射"
      description="把支付平台的原始分类转换成你自己的财务类别，让图表按你习惯的口径统计"
    >
      <el-button type="primary" @click="openCreate">
        <OOIcon name="plus" :size="16" style="margin-right: 6px; vertical-align: -2px" />
        新增规则
      </el-button>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="mb"
      title="规则在导入账单时生效：按优先级从高到低匹配第一条命中的规则；都没命中时保留平台原始分类，不会乱猜。停用的规则不参与匹配。"
    />

    <OOCard title="分类映射规则" :subtitle="`共 ${rules.length} 条`" flush class="mb">
      <OOToolbar hint="优先级数字大的先匹配" dense />
      <el-table :data="rules" size="small" v-loading="loading">
        <template #empty>
          <OOEmptyState
            variant="inbox"
            title="还没有映射规则"
            description="例如把「餐饮美食」映射到「餐饮」，导入账单时就自动归类了"
          />
        </template>
        <el-table-column label="适用平台" width="120">
          <template #default="{ row }">{{ platformLabel(row.platform) }}</template>
        </el-table-column>
        <el-table-column prop="pattern" label="平台原始分类" min-width="150" />
        <el-table-column label="匹配" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.matchMode === 'exact' ? 'warning' : 'info'">
              {{ row.matchMode === "exact" ? "全等" : "包含" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="targetCategory" label="归入类别" min-width="130" />
        <el-table-column label="优先级" width="80" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.priority }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="76">
          <template #default="{ row }">
            <el-tag size="small" effect="light" :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? "启用" : "停用" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="info" size="small" @click="toggle(row)">
              {{ row.enabled ? "停用" : "启用" }}
            </el-button>
            <el-popconfirm title="删除该规则？" @confirm="remove(row)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </OOCard>

    <OOCard title="现有类别概览" :subtitle="`共 ${categorySummary.length} 个类别`" flush>
      <OOToolbar hint="按流水金额降序" dense />
      <el-table :data="categorySummary" size="small" max-height="360">
        <template #empty>
          <OOEmptyState variant="inbox" title="暂无流水" description="先录入或导入一些账单" />
        </template>
        <el-table-column prop="name" label="类别" min-width="160" />
        <el-table-column label="流水条数" width="110" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.count }}</span></template>
        </el-table-column>
        <el-table-column label="合计金额" width="140" align="right">
          <template #default="{ row }"><span class="oo-num">{{ money(row.amount) }}</span></template>
        </el-table-column>
      </el-table>
    </OOCard>

    <el-dialog v-model="dialog" width="520px" align-center>
      <template #header>
        <div class="oo-dialog-head">
          <span class="oo-dialog-icon"><OOIcon name="tag" :size="18" /></span>
          <div>
            <h3 class="oo-dialog-title">{{ editing ? "编辑映射规则" : "新增映射规则" }}</h3>
            <p class="oo-dialog-desc">把平台原始分类转换成你自己的财务类别</p>
          </div>
        </div>
      </template>
      <el-form label-width="86px">
        <el-form-item label="适用平台">
          <el-select v-model="form.platform" class="w-full">
            <el-option v-for="p in PLATFORM_OPTIONS" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="原始分类" required>
          <el-input v-model="form.pattern" placeholder="如：餐饮美食" />
        </el-form-item>
        <el-form-item label="匹配方式">
          <el-radio-group v-model="form.matchMode">
            <el-radio-button value="contains">包含</el-radio-button>
            <el-radio-button value="exact">全等</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="归入类别" required>
          <el-input v-model="form.targetCategory" placeholder="如：餐饮" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :step="1" />
          <span class="oo-dim">数字大的先匹配</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
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
.mb {
  margin-bottom: var(--oo-space-5);
}
.w-full {
  width: 100%;
}
.oo-dim {
  margin-left: var(--oo-space-2);
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
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
</style>
