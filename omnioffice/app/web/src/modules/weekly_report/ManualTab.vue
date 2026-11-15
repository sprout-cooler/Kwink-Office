<script setup lang="ts">
/** 手工补充 Tab（V10 3.10 + v1.0.43）。
 *
 * - 重点问题（模板 19-20 行）/ 工作需求（21-22 行）：无固定结构，整段文本；
 * - 下周工作计划（模板 23 行起）：**结构化任务列表**，每条含
 *   任务标题 / 开始时间 / 结束时间 / 星期，可添加、删除、行内编辑。
 *   不再用整段文本框 —— 与「识别校对」的任务列表保持同一种交互形态。
 *
 * 保存后三条链路自动生效（无需各改一遍）：
 *   预览与导出读同一份数据 → 合并周报复用导出产物（v1.0.40 起）。
 */
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { weeklyApi, type ManualData, type ManualPlanTask } from "@/api/weekly-report";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader } from "@/components/ui";

const WEEKDAYS = ["未指定", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"];
const MAX_TASKS = 20;

const loading = ref(false);
const saving = ref(false);
const form = ref<ManualData>({ issues: "", demands: "", planTasks: [] });

function emptyTask(): ManualPlanTask {
  return { title: "", startTime: "", endTime: "", weekday: 0 };
}

async function refresh() {
  loading.value = true;
  try {
    const data = await weeklyApi.getManual();
    form.value = {
      issues: data.issues ?? "",
      demands: data.demands ?? "",
      // 兼容旧版本后端（没有 planTasks 字段）
      planTasks: Array.isArray(data.planTasks) ? data.planTasks : [],
    };
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
defineExpose({ refresh });

function addTask() {
  if (form.value.planTasks.length >= MAX_TASKS) {
    ElMessage.warning(`最多添加 ${MAX_TASKS} 条下周计划`);
    return;
  }
  form.value.planTasks.push(emptyTask());
}

function removeTask(index: number) {
  form.value.planTasks.splice(index, 1);
}

async function save() {
  saving.value = true;
  try {
    form.value = await weeklyApi.saveManual({
      issues: form.value.issues,
      demands: form.value.demands,
      // 空行交给后端过滤；这里也过滤一遍，避免保存后界面闪回空白行
      planTasks: form.value.planTasks.filter(
        (t) => t.title.trim() || t.startTime.trim() || t.endTime.trim(),
      ),
    });
    form.value.planTasks = Array.isArray(form.value.planTasks) ? form.value.planTasks : [];
    ElMessage.success("已保存，将随本周报一起导出");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div v-loading="loading" class="manual-tab">
    <OOPageHeader
      title="手工补充"
      description="填写重点问题、工作需求与下周工作计划；保存后随周报一起导出"
      badge="✍️"
    >
      <el-button type="primary" :loading="saving" @click="save">
        保存补充内容
      </el-button>
    </OOPageHeader>

    <el-alert type="info" :closable="false" class="tip-alert">
      重点问题与工作需求会原样写入周报模板对应行；下周工作计划按下面的结构化列表逐条写入「下周工作计划」区，
      每条包含星期、起止时间与任务标题。<b>保存后在「预览与导出」执行一次导出，合并周报会直接沿用那份产物。</b>
    </el-alert>

    <OOCard
      title="下周工作计划"
      subtitle="结构化任务列表 · 模板 D23:F26 起，超出槽位自动插行"
      class="blk"
    >
      <div class="plan-head">
        <el-button size="small" type="primary" plain :disabled="form.planTasks.length >= MAX_TASKS" @click="addTask">
          <span class="oo-btn-icon"><OOIcon name="plus" :size="14" /></span>
          添加任务
        </el-button>
      </div>

      <el-table v-if="form.planTasks.length" :data="form.planTasks" size="small" class="plan-tbl">
        <el-table-column label="#" width="46" type="index" />
        <el-table-column label="任务标题" min-width="240">
          <template #default="{ row }: { row: ManualPlanTask }">
            <el-input v-model="row.title" size="small" placeholder="如：广州-XX口腔-一体机-售后回访" />
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="180">
          <template #default="{ row }: { row: ManualPlanTask }">
            <el-input v-model="row.startTime" size="small" placeholder="如 11月9日 10:00" />
          </template>
        </el-table-column>
        <el-table-column label="结束时间" width="180">
          <template #default="{ row }: { row: ManualPlanTask }">
            <el-input v-model="row.endTime" size="small" placeholder="如 11月9日 12:00" />
          </template>
        </el-table-column>
        <el-table-column label="星期" width="130">
          <template #default="{ row }: { row: ManualPlanTask }">
            <el-select v-model="row.weekday" size="small" class="wd-select">
              <el-option v-for="(w, i) in WEEKDAYS" :key="i" :label="w" :value="i" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ $index }">
            <el-button link type="danger" size="small" @click="removeTask($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <OOEmptyState
        v-else
        variant="inbox"
        title="还没有下周计划"
        description="点「添加任务」逐条录入，导出的周报会按星期、时间、标题各占一行"
      />

      <div class="plan-foot">
        <el-button size="small" plain :disabled="form.planTasks.length >= MAX_TASKS" @click="addTask">
          <span class="oo-btn-icon"><OOIcon name="plus" :size="14" /></span>
          添加任务
        </el-button>
        <span class="counter oo-num">{{ form.planTasks.length }} / {{ MAX_TASKS }}</span>
      </div>
      <p class="plan-hint">
        时间按你写的原文展示，不做日期换算；与「任务上传 → 下周工作计划」识别出的任务会分成两段展示并加小标题区分来源。
      </p>
    </OOCard>

    <OOCard title="重点问题跟进" subtitle="模板第 19-20 行" class="blk">
      <el-input
        v-model="form.issues"
        type="textarea"
        :rows="6"
        placeholder="如：&#10;1. 客户对 XX 功能反馈较多，计划下周集中优化&#10;2. 跨部门接口联调进度滞后，需协调资源"
      />
      <div class="counter oo-num">{{ form.issues.length }} / 4000</div>
    </OOCard>

    <OOCard title="工作需求" subtitle="模板第 21-22 行" class="blk">
      <el-input
        v-model="form.demands"
        type="textarea"
        :rows="6"
        placeholder="如：&#10;1. 需要 XX 部门提供测试环境&#10;2. 申请下周外出培训名额"
      />
      <div class="counter oo-num">{{ form.demands.length }} / 4000</div>
    </OOCard>

    <div class="actions">
      <el-button type="primary" :loading="saving" @click="save">保存补充内容</el-button>
    </div>
  </div>
</template>

<style scoped>
.manual-tab {
  padding-bottom: var(--oo-space-6);
  max-width: 1080px;
}

.tip-alert {
  margin-bottom: var(--oo-space-4);
}

.blk {
  margin-bottom: var(--oo-space-4);
}

.plan-head {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--oo-space-3);
}

.plan-tbl {
  width: 100%;
}

.wd-select {
  width: 100%;
}

.plan-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--oo-space-3);
  margin-top: var(--oo-space-3);
}

.plan-hint {
  margin: var(--oo-space-2) 0 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  line-height: 1.6;
}

.counter {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  margin-top: var(--oo-space-2);
}

.plan-foot .counter {
  margin-top: 0;
}

.actions {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--oo-space-1);
}
</style>
