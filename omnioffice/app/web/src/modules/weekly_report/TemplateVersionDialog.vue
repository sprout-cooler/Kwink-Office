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
import { OOEmptyState, OOIcon } from "@/components/ui";

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
    width="min(900px, 94vw)"
    align-center
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="dlg-head">
        <span class="dlg-icon"><OOIcon name="weekly-report" :size="18" /></span>
        <div class="dlg-head-text">
          <h3 class="dlg-title">模板版本管理</h3>
          <p class="dlg-sub">版本链只增不改：回滚会从旧版派生新版本，历史版本全部保留</p>
        </div>
      </div>
    </template>

    <div class="cmp-body">
      <h4 class="cmp-title">版本列表</h4>
      <el-table :data="versions" size="small" max-height="240" class="cmp-tbl">
        <el-table-column label="版本" width="90">
          <template #default="{ row }"><b class="oo-num">v{{ row.version }}</b></template>
        </el-table-column>
        <el-table-column label="文件名" prop="filename" min-width="180" show-overflow-tooltip />
        <el-table-column label="备注" prop="note" min-width="140" show-overflow-tooltip />
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }"><span class="oo-num">{{ fmtTime(row.createdAt) }}</span></template>
        </el-table-column>
        <el-table-column label="更新时间" width="150">
          <template #default="{ row }"><span class="oo-num">{{ fmtTime(row.updatedAt) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>

      <h4 class="cmp-title">版本差异对比</h4>

      <div class="cmp-bar">
        <span class="cmp-bar-label">参照版本</span>
        <el-select v-model="baseId" size="small" class="cmp-select" placeholder="选择一个版本">
          <el-option v-for="t in versions" :key="t.id" :label="`v${t.version} · ${t.filename}`" :value="t.id" />
        </el-select>
        <span class="cmp-bar-label">对比版本</span>
        <el-select v-model="targetId" size="small" class="cmp-select" placeholder="选择一个版本">
          <el-option v-for="t in versions" :key="t.id" :label="`v${t.version} · ${t.filename}`" :value="t.id" />
        </el-select>
        <el-button size="small" type="primary" :loading="diffing" @click="runDiff">对比</el-button>
      </div>

      <OOEmptyState
        v-if="!diff"
        variant="search"
        title="选择两个版本后点「对比」"
        description="参照版本通常选旧版，对比版本选新版，就能看到这次改动动了哪些单元格"
      />
      <template v-else>
        <div class="diff-head">
          <span>共 <b class="oo-num">{{ diff.total }}</b> 处差异</span>
          <el-checkbox v-model="onlyChanges" size="small">只看单元格变化</el-checkbox>
          <el-tag v-if="diff.truncated" type="warning" effect="plain">
            差异过多，仅显示前 <span class="oo-num">{{ diff.limit }}</span> 条
          </el-tag>
        </div>
        <el-table :data="rows" size="small" max-height="300" class="cmp-tbl">
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
    </div>
  </el-dialog>
</template>

<style scoped>
.dlg-head {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  padding-right: var(--oo-space-6);
}

.dlg-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--oo-radius-sm);
  background: var(--oo-brand-soft);
  color: var(--oo-text-brand);
  flex-shrink: 0;
}

.dlg-head-text {
  min-width: 0;
}

.dlg-title {
  font-size: var(--oo-text-lg);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
  line-height: var(--oo-line-tight);
}

.dlg-sub {
  margin-top: 2px;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.cmp-body {
  display: flex;
  flex-direction: column;
}

.cmp-title {
  margin: 0 0 var(--oo-space-3);
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
}

.cmp-title:not(:first-child) {
  margin-top: var(--oo-space-5);
}

.cmp-tbl {
  width: 100%;
}

.cmp-bar {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
  font-size: var(--oo-text-sm);
  color: var(--oo-text-secondary);
  margin-bottom: var(--oo-space-4);
}

.cmp-bar-label {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.cmp-select {
  width: 230px;
  max-width: 100%;
}

.diff-head {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  flex-wrap: wrap;
  font-size: var(--oo-text-sm);
  margin-bottom: var(--oo-space-3);
  color: var(--oo-text-secondary);
}

.diff-head b {
  color: var(--oo-text-primary);
  font-weight: var(--oo-weight-semibold);
}

@media (max-width: 768px) {
  .cmp-select {
    width: 100%;
  }
}
</style>
