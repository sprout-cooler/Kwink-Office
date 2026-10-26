<script setup lang="ts">
// 手工补充 Tab（V10 3.10）：重点问题（模板 19-20 行）、工作需求（21-22 行）。
// 这两段无固定结构，由用户按周自由填写，随周报一起导出。
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { weeklyApi, type ManualData } from "@/api/weekly-report";
import { OOCard, OOPageHeader } from "@/components/ui";

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
  <div class="manual-tab">
    <OOPageHeader
      title="手工补充"
      description="填写重点问题与工作需求，这两段会原样写入周报模板的对应行"
      badge="✍️"
    >
      <el-button type="primary" :loading="saving" @click="save">
        保存补充内容
      </el-button>
    </OOPageHeader>

    <el-alert type="info" :closable="false" class="tip-alert">
      这两段内容会原样写入周报模板的对应行，不参与 AI 识别与统计校对。每条建议一行，写完点保存。
    </el-alert>

    <OOCard
      title="重点问题跟进"
      subtitle="模板第 19-20 行"
      class="blk"
      :loading="loading"
    >
      <el-input
        v-model="form.issues"
        type="textarea"
        :rows="7"
        placeholder="如：&#10;1. 客户对 XX 功能反馈较多，计划下周集中优化&#10;2. 跨部门接口联调进度滞后，需协调资源"
      />
      <div class="counter oo-num">{{ form.issues.length }} / 4000</div>
    </OOCard>

    <OOCard
      title="工作需求"
      subtitle="模板第 21-22 行"
      class="blk"
      :loading="loading"
    >
      <el-input
        v-model="form.demands"
        type="textarea"
        :rows="7"
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
  max-width: 860px;
}

.tip-alert {
  margin-bottom: var(--oo-space-4);
}

.blk {
  margin-bottom: var(--oo-space-4);
}

.counter {
  text-align: right;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  margin-top: var(--oo-space-2);
}

.actions {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--oo-space-1);
}
</style>
