<script setup lang="ts">
/** 客户管理：客户主数据的增删改查。 */
import { onMounted, ref } from "vue";
import { bizApi, type BizCapabilities, type BizCustomer } from "@/api/biz-dashboard";

const items = ref<BizCustomer[]>([]);
const caps = ref<BizCapabilities | null>(null);
const keyword = ref("");
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
  tags: [] as string[],
  note: "",
  status: "active",
});
const saving = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [list, c] = await Promise.all([bizApi.listCustomers(keyword.value), bizApi.capabilities()]);
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
    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <div class="bz-toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索名称 / 联系人 / 行业"
        clearable
        class="bz-search"
        @keyup.enter="load"
        @clear="load"
      />
      <el-button @click="load">搜索</el-button>
      <el-button type="primary" @click="openCreate">新增客户</el-button>
    </div>

    <el-table :data="items" size="small" v-loading="loading" empty-text="暂无客户">
      <el-table-column prop="name" label="客户名称" min-width="160" />
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
          <el-popconfirm title="删除该客户？关联的出差/财务/工时会解绑但保留。" @confirm="remove(row)">
            <template #reference>
              <el-button link type="danger" size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? '编辑客户' : '新增客户'" width="620px">
      <el-form label-width="80px">
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
.bz-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.bz-search {
  width: 280px;
}
.w-full {
  width: 100%;
}
.mb {
  margin-bottom: 12px;
}
</style>
