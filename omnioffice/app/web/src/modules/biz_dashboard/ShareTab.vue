<script setup lang="ts">
/** 选择性分享：财务涉敏数据的受控外发。
 *
 * 三件套缺一不可：**显式勾选 + 有时效 + 可撤销**。
 * 明文 token 只在创建时返回一次，列表里不再显示。
 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizExpense, type BizShare, type ShareCreated } from "@/api/biz-dashboard";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOStatTile, OOToolbar } from "@/components/ui";

const shares = ref<BizShare[]>([]);
const expenses = ref<BizExpense[]>([]);
const loading = ref(false);
const error = ref("");

const dialog = ref(false);
const selected = ref<number[]>([]);
const title = ref("");
const days = ref(7);
const saving = ref(false);
const created = ref<ShareCreated | null>(null);
const createdUrl = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [s, e] = await Promise.all([bizApi.listShares(), bizApi.listExpenses()]);
    shares.value = s.items;
    expenses.value = e.items;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function openCreate() {
  selected.value = [];
  title.value = "";
  days.value = 7;
  created.value = null;
  createdUrl.value = "";
  dialog.value = true;
}

async function create() {
  if (!selected.value.length) {
    error.value = "请先勾选要分享的流水记录";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const r = await bizApi.createShare({
      scopeKind: "expense",
      scopeIds: selected.value,
      title: title.value,
      days: days.value,
    });
    created.value = r;
    // 分享链接：走应用网关前缀，接收者无需登录即可打开
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

async function copyLink() {
  if (!createdUrl.value) return;
  try {
    await navigator.clipboard.writeText(createdUrl.value);
  } catch {
    // 非安全上下文（HTTP + 局域网）下 clipboard 不可用，退回选中提示
    const el = document.querySelector(".bz-created-url input") as HTMLInputElement | null;
    el?.select();
  }
}

/** 表格勾选变化：记下被选中的流水 id（分享范围）。 */
function onSelectionChange(rows: BizExpense[]) {
  selected.value = rows.map((r) => r.id);
}

const money = (n: number) =>
  `¥${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const scopeLabel = (code: string) =>
  code === "expense" ? "财务流水" : code === "trip" ? "出差记录" : "工作量";

const activeCount = computed(() => shares.value.filter((s) => s.active).length);
const revokedCount = computed(() => shares.value.filter((s) => s.revoked).length);
const totalViews = computed(() => shares.value.reduce((s, x) => s + (x.viewCount ?? 0), 0));
</script>

<template>
  <div>
    <OOPageHeader title="选择性分享" description="财务数据涉敏，分享必须显式勾选、限时有效、可随时撤销">
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
      title="财务数据涉敏：分享仅能包含你显式勾选的记录，且链接有到期时间、可随时撤销。撤销后链接立即失效。"
    />

    <div class="bz-kpis">
      <OOStatTile
        label="生效中链接"
        icon="🔗"
        tone="green"
        :value="activeCount"
        hint="可正常访问"
      />
      <OOStatTile
        label="已撤销"
        icon="⊘"
        tone="red"
        :value="revokedCount"
        hint="链接已立即失效"
      />
      <OOStatTile
        label="累计访问"
        icon="👁"
        tone="brand"
        :value="totalViews"
        hint="全部链接合计"
      />
    </div>

    <OOCard title="分享链接" :subtitle="`共 ${shares.length} 条`" flush>
      <OOToolbar hint="撤销后链接立即失效" dense>
        <template #right>
          <span class="oo-text-tertiary oo-text-xs">明文链接仅在创建时展示一次</span>
        </template>
      </OOToolbar>
      <el-table :data="shares" size="small" v-loading="loading">
        <template #empty>
          <OOEmptyState variant="inbox" title="尚未创建任何分享" description="点击右上角「创建分享链接」开始" />
        </template>
        <el-table-column prop="title" label="标题" min-width="140">
          <template #default="{ row }">{{ row.title || "（未命名）" }}</template>
        </el-table-column>
        <el-table-column label="内容" width="110">
          <template #default="{ row }">{{ scopeLabel(row.scopeKind) }}</template>
        </el-table-column>
        <el-table-column label="记录数" width="90" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.scopeCount }}</span></template>
        </el-table-column>
        <el-table-column label="到期时间" width="180">
          <template #default="{ row }">
            <span class="oo-num">
              {{ row.expiresAt ? new Date(row.expiresAt).toLocaleString("zh-CN") : "—" }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="访问次数" width="90" align="right">
          <template #default="{ row }"><span class="oo-num">{{ row.viewCount }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.revoked" size="small" type="info" effect="plain">已撤销</el-tag>
            <el-tag v-else-if="row.expired" size="small" type="warning" effect="plain">已过期</el-tag>
            <el-tag v-else size="small" type="success" effect="light">生效中</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.active"
              link
              type="danger"
              size="small"
              @click="revoke(row)"
            >
              撤销
            </el-button>
            <span v-else class="oo-text-tertiary oo-text-xs">—</span>
          </template>
        </el-table-column>
      </el-table>
    </OOCard>

    <el-dialog v-model="dialog" width="720px" align-center>
      <template #header>
        <div class="oo-dialog-head">
          <span class="oo-dialog-icon"><OOIcon name="link" :size="18" /></span>
          <div>
            <h3 class="oo-dialog-title">创建分享链接</h3>
            <p class="oo-dialog-desc">仅包含你显式勾选的记录，链接到期或撤销后立即失效</p>
          </div>
        </div>
      </template>

      <div v-if="created" class="bz-created">
        <el-alert type="success" :closable="false" show-icon>
          分享已创建，<b>链接只显示这一次</b>（关闭后无法再次查看，请立即复制发给对方）。
        </el-alert>
        <div class="bz-created-url">
          <el-input :model-value="createdUrl" readonly />
          <el-button type="primary" @click="copyLink">复制</el-button>
        </div>
        <p class="bz-dim">
          包含 {{ created.scopeCount }} 条记录，
          到期时间：{{ created.expiresAt ? new Date(created.expiresAt).toLocaleString("zh-CN") : "—" }}
        </p>
      </div>

      <template v-else>
        <el-form label-width="80px">
          <el-form-item label="标题">
            <el-input v-model="title" placeholder="如：Q3 XX客户对账明细" />
          </el-form-item>
          <el-form-item label="有效期">
            <el-input-number v-model="days" :min="1" :max="90" />
            <span class="bz-dim">天（最长 90 天）</span>
          </el-form-item>
          <el-form-item label="勾选记录">
            <div class="bz-pick-box">
              <el-table
                :data="expenses"
                size="small"
                height="280"
                @selection-change="onSelectionChange"
              >
                <template #empty>
                  <OOEmptyState variant="inbox" title="暂无财务流水可分享" description="先在「财务管理」里录入流水" />
                </template>
                <el-table-column type="selection" width="45" />
                <el-table-column prop="occurredOn" label="日期" width="105" />
                <el-table-column label="类别" width="90">
                  <template #default="{ row }">{{ row.category || "未分类" }}</template>
                </el-table-column>
                <el-table-column label="金额" width="110" align="right">
                  <template #default="{ row }"><span class="oo-num">{{ money(row.amount) }}</span></template>
                </el-table-column>
                <el-table-column prop="note" label="备注" min-width="120" />
              </el-table>
              <p class="bz-picked">已勾选 {{ selected.length }} 条记录</p>
            </div>
          </el-form-item>
        </el-form>
      </template>

      <template #footer>
        <template v-if="created">
          <el-button type="primary" @click="dialog = false">完成</el-button>
        </template>
        <template v-else>
          <el-button @click="dialog = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="create">生成链接</el-button>
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
.bz-dim {
  color: var(--oo-text-tertiary);
  font-size: var(--oo-text-xs);
}
.bz-pick-box {
  width: 100%;
}
.bz-picked {
  margin: var(--oo-space-2) 0 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-secondary);
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
}
</style>
