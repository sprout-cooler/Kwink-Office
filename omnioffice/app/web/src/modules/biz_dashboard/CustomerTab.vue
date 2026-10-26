<script setup lang="ts">
/** 客户管理：客户主数据的增删改查。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizCapabilities, type BizCustomer } from "@/api/biz-dashboard";
import { OOEmptyState, OOPageHeader } from "@/components/ui";

const items = ref<BizCustomer[]>([]);
const caps = ref<BizCapabilities | null>(null);
const keyword = ref("");
/** 按来源筛选（空=全部） */
const filterSource = ref("");
const loading = ref(false);
const error = ref("");

const dialog = ref(false);
const editing = ref<BizCustomer | null>(null);
const form = ref({
  name: "",
  contact: "",
  phone: "",
  address: "",
  industry: "",
  level: "",
  region: "",
  source: "",
  sourceNote: "",
  tags: [] as string[],
  note: "",
  status: "active",
});
const saving = ref(false);

/** 「其他」来源才需要补充说明 */
const sourceNeedsNote = computed(
  () => caps.value?.customerSourceNeedsNote.includes(form.value.source) ?? false,
);

/** 来源 code → 中文标签（列表显示用） */
const sourceLabels = computed(() => {
  const m: Record<string, string> = {};
  for (const s of caps.value?.customerSources ?? []) m[s.value] = s.label;
  return m;
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [list, c] = await Promise.all([
      bizApi.listCustomers(keyword.value, filterSource.value),
      bizApi.capabilities(),
    ]);
    items.value = list.items;
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
    name: "",
    contact: "",
    phone: "",
    address: "",
    industry: "",
    level: "",
    region: "",
    source: "",
    sourceNote: "",
    tags: [],
    note: "",
    status: "active",
  };
  dialog.value = true;
}

function openEdit(row: BizCustomer) {
  editing.value = row;
  form.value = {
    name: row.name,
    contact: row.contact,
    phone: row.phone,
    address: row.address,
    industry: row.industry,
    level: row.level,
    region: row.region,
    source: row.source ?? "",
    sourceNote: row.sourceNote ?? "",
    tags: [...(row.tags ?? [])],
    note: row.note,
    status: row.status,
  };
  dialog.value = true;
}

async function save() {
  if (!form.value.name.trim()) {
    error.value = "请填写客户名称";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    if (editing.value) {
      await bizApi.updateCustomer(editing.value.id, form.value);
    } else {
      await bizApi.createCustomer(form.value);
    }
    dialog.value = false;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function remove(row: BizCustomer) {
  error.value = "";
  try {
    await bizApi.deleteCustomer(row.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

const statusLabel = (code: string) =>
  caps.value?.customerStatus.find((s) => s.value === code)?.label ?? code;
</script>

<template>
  <div>
    <OOPageHeader
      title="客户管理"
      description="客户主数据的增删改查，来源字段可由周报联动自动回填"
      badge="👥"
    >
      <el-button type="primary" @click="openCreate">
        <span class="oo-btn-icon">＋</span>
        新增客户
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

    <div class="bz-card">
      <div class="bz-toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索名称 / 联系人 / 行业"
          clearable
          class="bz-search"
          @keyup.enter="load"
          @clear="load"
        />
        <el-select
          v-model="filterSource"
          placeholder="全部来源"
          clearable
          class="bz-source-filter"
          @change="load"
        >
          <el-option
            v-for="s in caps?.customerSources ?? []"
            :key="s.value"
            :label="s.label"
            :value="s.value"
          />
        </el-select>
        <el-button @click="load">搜索</el-button>
        <span class="oo-spacer" />
        <span class="bz-count">共 {{ items.length }} 位客户</span>
      </div>

      <div v-loading="loading" class="bz-table-wrap">
        <el-table
          v-if="items.length"
          :data="items"
          size="small"
          row-key="id"
          class="bz-table"
        >
          <el-table-column prop="name" label="客户名称" min-width="160">
            <template #default="{ row }">
              <span class="bz-name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.source" size="small" effect="light" class="bz-src-tag">
                {{ sourceLabels[row.source] ?? row.source }}
              </el-tag>
              <span v-else class="bz-muted">未指定</span>
            </template>
          </el-table-column>
          <el-table-column prop="industry" label="行业" width="110" />
          <el-table-column prop="contact" label="联系人" width="110" />
          <el-table-column prop="phone" label="电话" width="130" />
          <el-table-column prop="region" label="区域" width="100" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-popconfirm
                title="删除该客户？关联的出差/财务/工时会解绑但保留。"
                @confirm="remove(row)"
              >
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>

        <OOEmptyState
          v-else-if="!loading"
          variant="users"
          :title="keyword || filterSource ? '没有匹配的客户' : '还没有客户'"
          :description="
            keyword || filterSource
              ? '换个关键词或清除筛选条件试试'
              : '新增第一位客户后，出差、财务与工时统计都会关联到它'
          "
        >
          <el-button type="primary" @click="openCreate">新增客户</el-button>
        </OOEmptyState>
      </div>
    </div>

    <el-dialog
      v-model="dialog"
      :title="editing ? '编辑客户' : '新增客户'"
      width="620px"
      align-center
    >
      <el-form label-width="80px" label-position="right">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="客户名称" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="form.contact" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" placeholder="如：制造业 / 金融 / 教育" />
        </el-form-item>
        <el-form-item label="等级">
          <el-input v-model="form.level" placeholder="如：A / B / C" />
        </el-form-item>
        <el-form-item label="区域">
          <el-input v-model="form.region" placeholder="如：华东 / 华南" />
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.address" />
        </el-form-item>
        <el-form-item label="客户来源">
          <el-select v-model="form.source" placeholder="未指定" clearable class="w-full">
            <el-option
              v-for="s in caps?.customerSources ?? []"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
          <div v-if="sourceNeedsNote" class="bz-hint oo-mt-2">
            选择「其他」时请补充说明，便于日后按来源统计。
          </div>
        </el-form-item>
        <el-form-item v-if="sourceNeedsNote" label="来源说明">
          <el-input v-model="form.sourceNote" placeholder="如：XX 展会现场留资" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select
            v-model="form.tags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="回车创建标签"
            class="w-full"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" class="w-full">
            <el-option
              v-for="s in caps?.customerStatus ?? []"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="3" />
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
/* —— 卡片容器 —— */
.bz-card {
  background: var(--oo-bg-surface);
  border: 1px solid var(--oo-border-subtle);
  border-radius: var(--oo-radius-lg);
  box-shadow: var(--oo-shadow-sm);
  overflow: hidden;
}

/* —— 工具条 —— */
.bz-toolbar {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  padding: 14px 20px;
  border-bottom: 1px solid var(--oo-border-subtle);
  flex-wrap: wrap;
}

.bz-search {
  width: 280px;
}

.bz-source-filter {
  width: 150px;
}

.bz-count {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.bz-table-wrap {
  min-height: 160px;
}

.bz-table {
  width: 100%;
}

.bz-name {
  font-weight: var(--oo-weight-medium);
  color: var(--oo-text-primary);
}

.bz-src-tag {
  background: var(--oo-brand-soft);
  color: var(--oo-text-brand);
  font-weight: var(--oo-weight-medium);
}

.bz-muted {
  color: var(--oo-text-tertiary);
  font-size: var(--oo-text-xs);
}

.bz-hint {
  color: var(--oo-text-tertiary);
  font-size: var(--oo-text-xs);
  line-height: var(--oo-line-relaxed);
}

.w-full {
  width: 100%;
}

.oo-btn-icon {
  margin-right: 2px;
  font-size: 15px;
}

@media (max-width: 768px) {
  .bz-toolbar {
    padding: 12px 14px;
  }
  .bz-search,
  .bz-source-filter {
    width: 100%;
  }
}
</style>
