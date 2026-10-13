<script setup lang="ts">
// 工作汇总 Tab（V10 3.6/3.7）：四项统计 + 未分类清单归类。
// 口径：分区优先 + 关键词兜底，多命中按 培训>售后>售前；手工归类后锁定不再自动刷新。
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  weeklyApi,
  STAT_CATEGORY_LABELS,
  ASSIGNABLE_CATEGORIES,
  type SummaryData,
} from "@/api/weekly-report";

const loading = ref(false);
const data = ref<SummaryData | null>(null);

async function refresh() {
  loading.value = true;
  try {
    data.value = await weeklyApi.summary();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
defineExpose({ refresh });

const offlineItems = computed(() => {
  const d = data.value;
  if (!d) return [];
  return d.items.filter((i) => i.category === "training" || i.category === "offline_service" || i.category === "presale");
});

async function categorize(taskId: number, cat: string) {
  try {
    await weeklyApi.patchTask(taskId, { statCategory: cat });
    ElMessage.success(`已归类为「${STAT_CATEGORY_LABELS[cat]}」`);
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

async function clearCategory(taskId: number) {
  try {
    await weeklyApi.patchTask(taskId, { statCategory: "unclassified" });
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

// ---- 企微会话量（线上售后数量的真实口径）--------------------------
const editingSessions = ref(false);
const sessionsInput = ref<number>(0);
const savingSessions = ref(false);

function startEditSessions() {
  sessionsInput.value = data.value?.wechatSessions ?? 0;
  editingSessions.value = true;
}

async function saveSessions() {
  if (!Number.isInteger(sessionsInput.value) || sessionsInput.value < 0) {
    ElMessage.warning("会话量需为非负整数");
    return;
  }
  savingSessions.value = true;
  try {
    await weeklyApi.saveWechatSessions(sessionsInput.value);
    ElMessage.success("企微会话量已保存");
    editingSessions.value = false;
    await refresh();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    savingSessions.value = false;
  }
}
</script>

<template>
  <div v-loading="loading" class="summary-tab">
    <el-empty
      v-if="!loading && data && data.total === 0 && data.wechatSessions == null"
      description="还没有任务数据 —— 请先上传截图并识别"
    />

    <template v-else-if="data">
      <!-- 四项统计 -->
      <div class="stat-grid">
        <!-- 线上售后：模板口径为「企微会话量：N次」，取企微一周小结，不取任务条数 -->
        <el-card
          v-for="it in data.items.filter((x) => x.category === 'online_service')"
          :key="it.category"
          shadow="never"
          class="stat-card stat-card--online"
        >
          <div v-if="!editingSessions" class="stat-num">
            {{ data.wechatSessions ?? "—" }}
            <el-button link type="primary" class="edit-btn" title="修正会话量" @click="startEditSessions">
              修正
            </el-button>
          </div>
          <div v-else class="sessions-edit">
            <el-input-number
              v-model="sessionsInput"
              :min="0"
              :max="1000000"
              :controls="false"
              size="small"
              class="sessions-input"
              @keyup.enter="saveSessions"
            />
            <el-button type="primary" size="small" :loading="savingSessions" @click="saveSessions">保存</el-button>
            <el-button size="small" @click="editingSessions = false">取消</el-button>
          </div>
          <div class="stat-label">{{ it.label }}（企微会话量/次）</div>
          <div class="stat-sub">
            <el-tag v-if="data.wechatSource === 'manual'" size="small" type="warning" effect="plain">人工修正</el-tag>
            <el-tag v-else-if="data.wechatSource === 'ai'" size="small" type="success" effect="plain">截图识别</el-tag>
            <el-tag v-else size="small" type="info" effect="plain">未提供企微小结</el-tag>
            <span v-if="data.wechatMinutes" class="stat-sub-text">本周 {{ data.wechatMinutes }} 分钟</span>
          </div>
        </el-card>

        <el-card
          v-for="it in data.items.filter((x) => x.category !== 'online_service')"
          :key="it.category"
          shadow="never"
          class="stat-card"
        >
          <div class="stat-num">{{ it.count }}</div>
          <div class="stat-label">{{ it.label }}</div>
        </el-card>
      </div>

      <div class="extra-row">
        <el-tag type="info" effect="plain">线下合计：{{ data.offlineTotal }} 条</el-tag>
        <el-tag type="info" effect="plain">下周计划：{{ data.planTotal }} 条</el-tag>
        <el-tag type="info" effect="plain">任务总数：{{ data.total }} 条</el-tag>
        <el-tag v-if="data.unclassifiedItems.length > 0" type="warning" effect="plain">
          未分类：{{ data.unclassifiedItems.length }} 条
        </el-tag>
      </div>

      <el-alert type="info" :closable="false" class="rule-tip">
        统计口径（与 Excel 模板一致）：<b>线上售后数量</b>填企业微信「一周小结」里的<b>工作会话次数</b>
        （导出为「企微会话量：N次」，可在卡片上直接修正）；
        <b>培训 / 线下售后 / 售前</b>按任务标题关键词判定，
        一条命中多个时按「培训 &gt; 线下售后 &gt; 售前」取优先级最高的；未命中进入下方未分类清单。
        「下周工作计划」分区的任务只进 Excel 计划区，不计入四项数量。
      </el-alert>

      <!-- 未分类清单 -->
      <section v-if="data.unclassifiedItems.length > 0" class="unc">
        <header class="unc-head">
          <h3>未分类清单</h3>
          <span class="unc-sub">
            这些任务标题未命中任何关键词，请手工归类；归类后统计会立即更新且不再自动刷新
          </span>
        </header>
        <el-table :data="data.unclassifiedItems" size="small" border>
          <el-table-column label="任务标题" min-width="240" prop="title" />
          <el-table-column label="分区" width="130">
            <template #default="{ row }">{{ row.partitionLabel }}</template>
          </el-table-column>
          <el-table-column label="归类为" width="180">
            <template #default="{ row }">
              <el-select
                :model-value="row.statCategory"
                size="small"
                placeholder="请选择"
                @change="(v: string) => categorize(row.id, v)"
              >
                <el-option
                  v-for="c in ASSIGNABLE_CATEGORIES.filter((x) => x !== 'unclassified')"
                  :key="c"
                  :label="STAT_CATEGORY_LABELS[c]"
                  :value="c"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link size="small" @click="clearCategory(row.id)">重置</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <!-- 线下明细 -->
      <section class="offline">
        <header class="unc-head">
          <h3>线下工作明细</h3>
          <span class="unc-sub">按统计分类归组，便于核对</span>
        </header>
        <el-empty v-if="offlineItems.length === 0" description="线下工作分区暂无任务" :image-size="70" />
        <div v-else class="offline-grid">
          <el-card v-for="it in offlineItems" :key="it.category" shadow="never" class="stat-card">
            <div class="stat-num">{{ it.count }}</div>
            <div class="stat-label">{{ it.label }}</div>
          </el-card>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.summary-tab {
  padding-bottom: 24px;
}
.stat-grid,
.offline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.stat-card {
  text-align: center;
}
.stat-card--online {
  border-color: var(--el-color-primary-light-5);
}
.stat-num {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.2;
}
.edit-btn {
  font-size: 13px;
  font-weight: 400;
  padding: 0 0 0 4px;
  vertical-align: middle;
}
.sessions-edit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 36px;
}
.sessions-input {
  width: 110px;
}
.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.stat-sub {
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.stat-sub-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.extra-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.rule-tip {
  margin-bottom: 18px;
  line-height: 1.7;
}
.unc,
.offline {
  margin-bottom: 22px;
}
.unc-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.unc-head h3 {
  margin: 0;
  font-size: 15px;
}
.unc-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
