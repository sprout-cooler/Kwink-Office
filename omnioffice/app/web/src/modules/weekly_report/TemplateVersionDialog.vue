<script setup lang="ts">
// 模板版本管理：版本列表 + 差异对比 + 回滚。
//
// 版本链是**只增不改**的：回滚不是把指针挪回旧版，而是从旧版内容派生一个新版本，
// 因此任何时候都能再回滚回来 —— 用户改错模板也能救。
import { computed, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  weeklyApi,
  type TemplateDiff,
  type TemplateDiffItem,
  type TemplateItem,
} from "@/api/weekly-report";

const props = defineProps<{ modelValue: boolean; templates: TemplateItem[] }>();
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "changed"): void;
}>();

// 版本号倒序（越新越靠前），与导出页列表口径一致
const versions = computed(() =>
  [...props.templates].sort((a, b) => b.version - a.version),
);

const baseId = ref<number | null>(null);
const targetId = ref<number | null>(null);
const diff = ref<TemplateDiff | null>(null);
const diffing = ref(false);
const rollingBack = ref(false);
const onlyChanges = ref(true);

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    diff.value = null;
    // 默认「最新版 vs 上一版」——绝大多数时候用户就是想看最后这次改动
    targetId.value = versions.value[0]?.id ?? null;
    baseId.value = versions.value[1]?.id ?? null;
  },
);

const canDiff = computed(
  () => baseId.value !== null && targetId.value !== null && baseId.value !== targetId.value,
);

const KIND_TAG: Record<string, { type: "success" | "warning" | "danger" | "info"; label: string }> = {
  changed: { type: "warning", label: "修改" },
  added: { type: "success", label: "新增" },
  removed: { type: "danger", label: "删除" },
  sheet_added: { type: "success", label: "新增工作表" },
  sheet_removed: { type: "danger", label: "删除工作表" },
};

const rows = computed<TemplateDiffItem[]>(() => {
  const all = diff.value?.changes ?? [];
  if (!onlyChanges.value) return all;
  // 只看单元格级变化；工作表整体的增删属于结构性事件，默认不混在行列差异里
  return all.filter((c) => !c.kind.startsWith("sheet_"));
});

async function runDiff() {
  if (!canDiff.value) {
    ElMessage.warning("请选择两个不同的版本");
    return;
  }
  diffing.value = true;
  try {
    diff.value = await weeklyApi.diffTemplates(baseId.value as number, targetId.value as number);
    if (!diff.value.changes.length) ElMessage.info("两个版本内容完全一致");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    diffing.value = false;
  }
}

async function rollback(t: TemplateItem) {
  try {
    await ElMessageBox.confirm(
      `将以 v${t.version} 的内容生成一个**新版本**并绑定到当前周报批次。历史版本全部保留，随时可以再回滚。`,
      `回滚到 v${t.version}`,
      { type: "warning", confirmButtonText: "回滚", cancelButtonText: "取消", dangerouslyUseHTMLString: true },
    );
  } catch {
    return;
  }
  rollingBack.value = true;
  try {
    const r = await weeklyApi.rollbackTemplate(t.id);
    ElMessage.success(`已生成新版本 v${r.template.version}（内容取自 v${r.sourceVersion}）`);
    emit("changed");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    rollingBack.value = false;
  }
}

function fmtTime(s: string | null | undefined): string {
  return s ? s.slice(0, 16).replace("T", " ") : "—";
}
</script>

<template>
  <el-dialog
    :model-value="props.modelValue"
    title="模板版本管理"
    width="860px"
    top="6vh"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-table :data="versions" size="small" border max-height="240">
      <el-table-column label="版本" width="80">
        <template #default="{ row }"><b>v{{ row.version }}</b></template>
      </el-table-column>
      <el-table-column label="文件名" prop="filename" min-width="180" show-overflow-tooltip />
      <el-table-column label="备注" prop="note" min-width="140" show-overflow-tooltip />
      <el-table-column label="创建时间" width="150">
        <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ fmtTime(row.updatedAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="rollback(row)">回滚</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">版本差异对比</el-divider>

    <div class="cmp-bar">
      <span>参照版本</span>
      <el-select v-model="baseId" size="small" class="cmp-select" placeholder="选择一个版本">
        <el-option v-for="t in versions" :key="t.id" :label="`v${t.version} · ${t.filename}`" :value="t.id" />
      </el-select>
      <span>对比版本</span>
      <el-select v-model="targetId" size="small" class="cmp-select" placeholder="选择一个版本">
        <el-option v-for="t in versions" :key="t.id" :label="`v${t.version} · ${t.filename}`" :value="t.id" />
      </el-select>
      <el-button size="small" type="primary" :loading="diffing" @click="runDiff">对比</el-button>
    </div>

    <el-empty v-if="!diff" description="选择两个版本后点「对比」" :image-size="70" />
    <template v-else>
      <div class="diff-head">
        <span>共 <b>{{ diff.total }}</b> 处差异</span>
        <el-checkbox v-model="onlyChanges" size="small">只看单元格变化</el-checkbox>
        <el-tag v-if="diff.truncated" type="warning" effect="plain">
          差异过多，仅显示前 {{ diff.limit }} 条
        </el-tag>
      </div>
      <el-table :data="rows" size="small" border max-height="300">
        <el-table-column label="工作表" prop="sheet" width="110" />
        <el-table-column label="单元格" prop="cell" width="90" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="KIND_TAG[row.kind].type" effect="plain">
              {{ KIND_TAG[row.kind].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="参照版本的值" prop="left" min-width="160" show-overflow-tooltip />
        <el-table-column label="对比版本的值" prop="right" min-width="160" show-overflow-tooltip />
      </el-table>
    </template>
  </el-dialog>
</template>

<style scoped>
.cmp-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 12px;
}
.cmp-select {
  width: 230px;
}
.diff-head {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--el-text-color-secondary);
}
</style>
