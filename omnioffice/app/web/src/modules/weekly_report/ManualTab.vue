<script setup lang="ts">
// 手工补充 Tab（V10 3.10）：重点问题（模板 19-20 行）、工作需求（21-22 行）。
// 这两段无固定结构，由用户按周自由填写，随周报一起导出。
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { weeklyApi, type ManualData } from "@/api/weekly-report";

const loading = ref(false);
const saving = ref(false);
const form = ref<ManualData>({ issues: "", demands: "" });

async function refresh() {
  loading.value = true;
  try {
    form.value = await weeklyApi.getManual();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
defineExpose({ refresh });

async function save() {
  saving.value = true;
  try {
    form.value = await weeklyApi.saveManual({
      issues: form.value.issues,
      demands: form.value.demands,
    });
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
    <el-alert type="info" :closable="false" class="tip-alert">
      这两段内容会原样写入周报模板的对应行，不参与 AI 识别与统计校对。每条建议一行，写完点保存。
    </el-alert>

    <el-card shadow="never" class="blk">
      <template #header>
        <div class="blk-head">
          <b>重点问题跟进</b>
          <span class="blk-sub">模板第 19-20 行</span>
        </div>
      </template>
      <el-input
        v-model="form.issues"
        type="textarea"
        :rows="7"
        placeholder="如：&#10;1. 客户对 XX 功能反馈较多，计划下周集中优化&#10;2. 跨部门接口联调进度滞后，需协调资源"
      />
      <div class="counter">{{ form.issues.length }} / 4000</div>
    </el-card>

    <el-card shadow="never" class="blk">
      <template #header>
        <div class="blk-head">
          <b>工作需求</b>
          <span class="blk-sub">模板第 21-22 行</span>
        </div>
      </template>
      <el-input
        v-model="form.demands"
        type="textarea"
        :rows="7"
        placeholder="如：&#10;1. 需要 XX 部门提供测试环境&#10;2. 申请下周外出培训名额"
      />
      <div class="counter">{{ form.demands.length }} / 4000</div>
    </el-card>

    <div class="actions">
      <el-button type="primary" :loading="saving" @click="save">保存补充内容</el-button>
    </div>
  </div>
</template>

<style scoped>
.manual-tab {
  padding-bottom: 24px;
  max-width: 860px;
}
.tip-alert {
  margin-bottom: 16px;
}
.blk {
  margin-bottom: 16px;
}
.blk-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.blk-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: normal;
}
.counter {
  text-align: right;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 6px;
}
.actions {
  padding-top: 4px;
}
</style>
