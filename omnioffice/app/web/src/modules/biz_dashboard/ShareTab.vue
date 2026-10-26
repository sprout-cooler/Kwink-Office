<script setup lang="ts">
/** 选择性分享：涉敏数据的受控外发（v1.0.32）。
 *
 * 四件套缺一不可：**显式勾选 + 有时效 + 可撤销 + 可选口令**。
 *
 * v1.0.32 相比上一版的两处变化：
 * 1. 一次分享可同时包含财务流水 / 客户信息 / 工作量统计 / 出差路径，
 *    每项独立开关 —— 上版一次只能选一类，要分享客户+出差就得建两条链接；
 * 2. 可加访问口令 —— 财务数据发给外部人员时，仅有链接还不够。
 *
 * 明文 token 只在创建时返回一次，列表里不再显示。
 */
import { computed, onMounted, ref } from "vue";
import {
  bizApi,
  type BizCapabilities,
  type BizCustomer,
  type BizExpense,
  type BizShare,
  type BizTrip,
  type ShareCreated,
} from "@/api/biz-dashboard";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOStatTile, OOToolbar } from "@/components/ui";

const shares = ref<BizShare[]>([]);
const expenses = ref<BizExpense[]>([]);
const customers = ref<BizCustomer[]>([]);
const trips = ref<BizTrip[]>([]);
const caps = ref<BizCapabilities | null>(null);
const loading = ref(false);
const error = ref("");

const dialog = ref(false);
const title = ref("");
const days = ref(7);
const passcode = ref("");
const usePass = ref(false);
const saving = ref(false);
const created = ref<ShareCreated | null>(null);
const createdUrl = ref("");

/** 各类是否开启（独立开关） */
const enabled = ref<Record<string, boolean>>({
  expense: false,
  customer: false,
  workload: false,
  trip: false,
});
/** 各类被勾选的记录 id */
const selected = ref<Record<string, number[]>>({ expense: [], customer: [], trip: [] });

const SCOPE_LABEL: Record<string, string> = {
  expense: "财务流水",
  customer: "客户信息",
  workload: "工作量统计",
  trip: "出差路径",
};
const SCOPE_DESC: Record<string, string> = {
  expense: "勾选要公开的收支流水",
  customer: "仅含名称/行业/地区等基本信息，不含联系方式与备注",
  workload: "按客户与月份汇总的工时统计（聚合口径，不逐条列出）",
  trip: "勾选要公开的出差记录，含起止地点与里程",
};

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [s, e, c, t, cap] = await Promise.all([
      bizApi.listShares(),
      bizApi.listExpenses(),
      bizApi.listCustomers(),
      bizApi.listTrips(),
      bizApi.capabilities(),
    ]);
    shares.value = s.items;
    expenses.value = e.items;
    customers.value = c.items;
    trips.value = t.items;
    caps.value = cap;
    days.value = cap?.shareDefaultDays ?? 7;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function openCreate() {
  title.value = "";
  days.value = caps.value?.shareDefaultDays ?? 7;
  passcode.value = "";
  usePass.value = false;
  enabled.value = { expense: false, customer: false, workload: false, trip: false };
  selected.value = { expense: [], customer: [], trip: [] };
  created.value = null;
  createdUrl.value = "";
  dialog.value = true;
}

/** 提交给后端的 scopes：只含「已开启且有内容」的类别。 */
const scopes = computed<Record<string, number[]>>(() => {
  const out: Record<string, number[]> = {};
  if (enabled.value.expense && selected.value.expense.length) {
    out.expense = selected.value.expense;
  }
  if (enabled.value.customer && selected.value.customer.length) {
    out.customer = selected.value.customer;
  }
  if (enabled.value.trip && selected.value.trip.length) {
    out.trip = selected.value.trip;
  }
  if (enabled.value.workload) {
    out.workload = []; // 聚合口径：键存在即表示包含
  }
  return out;
});

/** 预览：让用户创建前就看清楚「到底分享出去了什么」。 */
const previewItems = computed(() =>
  Object.entries(scopes.value).map(([kind, ids]) => ({
    kind,
    label: SCOPE_LABEL[kind] ?? kind,
    count: kind === "workload" ? 0 : ids.length,
    isAggregate: kind === "workload",
  })),
);
const canCreate = computed(() => Object.keys(scopes.value).length > 0);

async function create() {
  if (!canCreate.value) {
    error.value = "请至少开启一项分享内容";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const r = await bizApi.createShare({
      scopes: scopes.value,
      title: title.value,
      days: days.value,
      ...(usePass.value && passcode.value ? { passcode: passcode.value } : {}),
    });
    created.value = r;
    const base = window.location.origin + window.location.pathname.replace(/\/[^/]*$/, "");
    createdUrl.value = `${base}/biz-dashboard/shares/public/${r.token}`;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function revoke(row: BizShare) {
  error.value = "";
  try {
    await bizApi.revokeShare(row.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 非安全上下文（HTTP + 局域网）下 clipboard 不可用，退回选中提示
    const el = document.querySelector(".bz-created-url input") as HTMLInputElement | null;
    el?.select();
  }
}

const scopeLabels = (s: Record<string, number>) =>
  Object.entries(s ?? {})
    .map(([k, v]) => `${SCOPE_LABEL[k] ?? k}${k === "workload" ? "" : ` ${v}`}`)
    .join("、") || "—";

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const tripTitle = (t: BizTrip) => t.title || `${t.originName || "?"} → ${t.destName || "?"}`;

const activeCount = computed(() => shares.value.filter((s) => s.active).length);
const revokedCount = computed(() => shares.value.filter((s) => s.revoked).length);
const totalViews = computed(() => shares.value.reduce((s, x) => s + (x.viewCount ?? 0), 0));

function onSelection(kind: string, rows: { id: number }[]) {
  selected.value[kind] = rows.map((r) => r.id);
}
</script>

<template>
  <div>
    <OOPageHeader
      title="选择性分享"
      description="涉敏数据外发必须显式勾选、限时有效、可随时撤销，必要时再加访问口令"
    >
      <el-button type="primary" @click="openCreate">
        <OOIcon name="plus" :size="16" style="margin-right: 6px; vertical-align: -2px" />
        创建分享链接
      </el-button>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="mb"
      title="分享出去的内容仅限你勾选的部分：链接有到期时间、可随时撤销，撤销后立即失效。客户信息默认不含联系方式与备注。"
    />

    <div class="bz-kpis">
      <OOStatTile label="生效中链接" icon="🔗" tone="green" :value="activeCount" hint="可正常访问" />
      <OOStatTile label="已撤销" icon="⊘" tone="red" :value="revokedCount" hint="链接已立即失效" />
      <OOStatTile label="累计访问" icon="👁" tone="brand" :value="totalViews" hint="全部链接合计" />
    </div>

    <OOCard title="分享链接" :subtitle="`共 ${shares.length} 条`" flush>
      <OOToolbar hint="撤销后链接立即失效" dense>
        <template #right>
          <span class="oo-text-tertiary oo-text-xs">明文链接仅在创建时展示一次</span>
        </template>
      </OOToolbar>
      <el-table :data="shares" size="small" v-loading="loading">
        <template #empty>
          <OOEmptyState
            variant="inbox"
            title="尚未创建任何分享"
            description="点击右上角「创建分享链接」开始"
          />
        </template>
        <el-table-column prop="title" label="标题" min-width="130">
          <template #default="{ row }">{{ row.title || "（未命名）" }}</template>
        </el-table-column>
        <el-table-column label="包含内容" min-width="180">
          <template #default="{ row }">
            <span class="oo-text-xs">{{ scopeLabels(row.scopes) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="口令" width="72" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.hasPass" size="small" effect="light" type="warning">已设</el-tag>
            <span v-else class="oo-text-tertiary oo-text-xs">无</span>
          </template>
        </el-table-column>
        <el-table-column label="到期时间" width="170">
          <template #default="{ row }">
            <span class="oo-num oo-text-xs">
              {{ row.expiresAt ? new Date(row.expiresAt).toLocaleString("zh-CN") : "—" }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="访问" width="72" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.viewCount }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag v-if="row.revoked" size="small" type="info" effect="plain">已撤销</el-tag>
            <el-tag v-else-if="row.expired" size="small" type="warning" effect="plain">已过期</el-tag>
            <el-tag v-else size="small" type="success" effect="light">生效中</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button v-if="row.active" link type="danger" size="small" @click="revoke(row)">
              撤销
            </el-button>
            <span v-else class="oo-text-tertiary oo-text-xs">—</span>
          </template>
        </el-table-column>
      </el-table>
    </OOCard>

    <el-dialog v-model="dialog" width="820px" align-center>
      <template #header>
        <div class="oo-dialog-head">
          <span class="oo-dialog-icon"><OOIcon name="link" :size="18" /></span>
          <div>
            <h3 class="oo-dialog-title">创建分享链接</h3>
            <p class="oo-dialog-desc">每项独立开关，仅包含你勾选的内容；到期或撤销后立即失效</p>
          </div>
        </div>
      </template>

      <div v-if="created" class="bz-created">
        <el-alert type="success" :closable="false" show-icon>
          分享已创建，<b>链接只显示这一次</b>（关闭后无法再次查看，请立即复制发给对方）。
        </el-alert>
        <div class="bz-created-url">
          <el-input :model-value="createdUrl" readonly />
          <el-button type="primary" @click="copyText(createdUrl)">复制链接</el-button>
        </div>
        <div v-if="created.hasPass" class="bz-pass-box">
          <span class="bz-pass-label">访问口令</span>
          <code class="bz-pass">{{ passcode }}</code>
          <el-button size="small" @click="copyText(`链接：${createdUrl}\n访问口令：${passcode}`)">
            复制链接和口令
          </el-button>
        </div>
        <p class="bz-dim">
          <template v-if="created.hasPass">
            对方需要<b>同时</b>拿到链接和口令才能打开。建议分开发送（链接走一种渠道、口令走另一种）。
          </template>
          <template v-else>
            任何拿到此链接的人都可以查看，无需登录。
          </template>
          共 {{ created.scopeCount }} 条记录，到期：
          {{ created.expiresAt ? new Date(created.expiresAt).toLocaleString("zh-CN") : "—" }}
        </p>
      </div>

      <template v-else>
        <el-form label-width="76px">
          <el-form-item label="标题">
            <el-input v-model="title" placeholder="如：Q3 对账明细" />
          </el-form-item>
          <el-form-item label="有效期">
            <el-input-number v-model="days" :min="1" :max="caps?.shareMaxDays ?? 90" />
            <span class="bz-dim">天（最长 {{ caps?.shareMaxDays ?? 90 }} 天）</span>
          </el-form-item>
          <el-form-item label="访问口令">
            <el-switch v-model="usePass" class="bz-switch" />
            <span class="bz-dim">{{ usePass ? "对方需输入口令才能查看" : "不设口令（拿到链接即可查看）" }}</span>
          </el-form-item>
          <el-form-item v-if="usePass" label="口令">
            <el-input
              v-model="passcode"
              class="oo-field-w oo-field-w-md"
              show-password
              :placeholder="`${caps?.sharePassMinLen ?? 4} ~ ${caps?.sharePassMaxLen ?? 32} 位`"
            />
          </el-form-item>
        </el-form>

        <div class="bz-scopes">
          <div v-for="kind in ['expense', 'customer', 'workload', 'trip']" :key="kind" class="bz-scope">
            <div class="bz-scope-head">
              <el-switch v-model="enabled[kind]" />
              <div class="bz-scope-title">
                <b>{{ SCOPE_LABEL[kind] }}</b>
                <span class="oo-text-tertiary oo-text-xs">{{ SCOPE_DESC[kind] }}</span>
              </div>
              <span v-if="enabled[kind]" class="bz-scope-count">
                <template v-if="kind === 'workload'">已包含</template>
                <template v-else>已选 {{ selected[kind]?.length ?? 0 }} 条</template>
              </span>
            </div>

            <div v-if="enabled[kind] && kind === 'expense'" class="bz-pick">
              <el-table
                :data="expenses"
                size="small"
                height="220"
                @selection-change="(r: BizExpense[]) => onSelection('expense', r)"
              >
                <template #empty>
                  <OOEmptyState variant="inbox" title="暂无财务流水" description="先在「财务管理」录入或导入账单" />
                </template>
                <el-table-column type="selection" width="45" />
                <el-table-column prop="occurredOn" label="日期" width="105" />
                <el-table-column label="类别" width="90">
                  <template #default="{ row }">{{ row.category || "未分类" }}</template>
                </el-table-column>
                <el-table-column label="交易对方" min-width="110">
                  <template #default="{ row }">{{ row.counterparty || "—" }}</template>
                </el-table-column>
                <el-table-column label="金额" width="110" align="right">
                  <template #default="{ row }"><span class="oo-num">{{ money(row.amount) }}</span></template>
                </el-table-column>
              </el-table>
            </div>

            <div v-if="enabled[kind] && kind === 'customer'" class="bz-pick">
              <el-table
                :data="customers"
                size="small"
                height="220"
                @selection-change="(r: BizCustomer[]) => onSelection('customer', r)"
              >
                <template #empty>
                  <OOEmptyState variant="users" title="暂无客户" description="先在「客户管理」添加客户" />
                </template>
                <el-table-column type="selection" width="45" />
                <el-table-column prop="name" label="客户名称" min-width="140" />
                <el-table-column prop="industry" label="行业" width="100" />
                <el-table-column prop="region" label="地区" width="100" />
                <el-table-column prop="level" label="等级" width="80" />
              </el-table>
            </div>

            <div v-if="enabled[kind] && kind === 'trip'" class="bz-pick">
              <el-table
                :data="trips"
                size="small"
                height="220"
                @selection-change="(r: BizTrip[]) => onSelection('trip', r)"
              >
                <template #empty>
                  <OOEmptyState variant="inbox" title="暂无出差记录" description="先在「出差与路径」添加记录" />
                </template>
                <el-table-column type="selection" width="45" />
                <el-table-column label="主题" min-width="150">
                  <template #default="{ row }">{{ tripTitle(row) }}</template>
                </el-table-column>
                <el-table-column prop="startDate" label="开始" width="105" />
                <el-table-column prop="endDate" label="结束" width="105" />
                <el-table-column prop="mileageKm" label="里程" width="80" align="right">
                  <template #default="{ row }"><span class="oo-num">{{ row.mileageKm ?? "—" }}</span></template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>

        <div class="bz-preview">
          <b class="bz-preview-title">分享预览</b>
          <template v-if="previewItems.length">
            <ul class="bz-preview-list">
              <li v-for="p in previewItems" :key="p.kind">
                {{ p.label }}
                <span class="oo-text-tertiary oo-text-xs">
                  {{ p.isAggregate ? "（工时汇总）" : `${p.count} 条` }}
                </span>
              </li>
            </ul>
            <p class="bz-dim">
              任何拿到此链接的人都可以查看，无需登录<template v-if="usePass && passcode">，且需要输入口令</template>。
            </p>
          </template>
          <p v-else class="bz-dim">尚未开启任何分享内容</p>
        </div>
      </template>

      <template #footer>
        <template v-if="created">
          <el-button type="primary" @click="dialog = false">完成</el-button>
        </template>
        <template v-else>
          <el-button @click="dialog = false">取消</el-button>
          <el-button type="primary" :loading="saving" :disabled="!canCreate" @click="create">
            生成链接
          </el-button>
        </template>
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

.bz-created-url {
  display: flex;
  gap: var(--oo-space-2);
  margin: var(--oo-space-3) 0 var(--oo-space-2);
}
.bz-pass-box {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
  margin-bottom: var(--oo-space-2);
}
.bz-pass-label {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-secondary);
}
.bz-pass {
  padding: 3px 10px;
  border-radius: var(--oo-radius-sm);
  background: var(--oo-brand-soft);
  color: var(--oo-text-brand);
  font-size: var(--oo-text-base);
  font-weight: var(--oo-weight-semibold);
}
.bz-dim {
  color: var(--oo-text-tertiary);
  font-size: var(--oo-text-xs);
  line-height: 1.6;
}
.mb {
  margin-bottom: var(--oo-space-5);
}

.bz-scopes {
  display: flex;
  flex-direction: column;
  gap: var(--oo-space-3);
  margin: var(--oo-space-2) 0 var(--oo-space-4);
}
.bz-scope {
  border: 1px solid var(--oo-border-subtle);
  border-radius: var(--oo-radius-md);
  background: var(--oo-bg-surface-2);
  overflow: hidden;
}
.bz-scope-head {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  padding: var(--oo-space-3) var(--oo-space-4);
}
.bz-scope-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.bz-scope-title b {
  font-size: var(--oo-text-sm);
  color: var(--oo-text-primary);
}
.bz-scope-count {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-brand);
  white-space: nowrap;
}
.bz-pick {
  padding: 0 var(--oo-space-4) var(--oo-space-3);
}
.bz-switch {
  flex-shrink: 0;
}

.bz-preview {
  padding: var(--oo-space-3) var(--oo-space-4);
  border-radius: var(--oo-radius-md);
  background: var(--oo-brand-soft);
}
.bz-preview-title {
  display: block;
  font-size: var(--oo-text-sm);
  color: var(--oo-text-primary);
  margin-bottom: var(--oo-space-2);
}
.bz-preview-list {
  margin: 0 0 var(--oo-space-2);
  padding-left: var(--oo-space-5);
  font-size: var(--oo-text-sm);
  color: var(--oo-text-primary);
}
.bz-preview-list li {
  margin-bottom: 2px;
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
  .bz-scope-head {
    padding: var(--oo-space-3);
  }
}
</style>
