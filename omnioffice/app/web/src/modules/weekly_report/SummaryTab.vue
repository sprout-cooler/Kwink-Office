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
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOStatTile, OOToolbar } from "@/components/ui";

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

/** 线上售后：模板口径为「企微会话量：N次」，取企微一周小结，不取任务条数 */
const onlineItem = computed(
  () => data.value?.items.find((i) => i.category === "online_service") ?? null,
);

/** 其余三项按分类取指标块（培训 / 线下售后 / 售前） */
const otherItems = computed(
  () => data.value?.items.filter((i) => i.category !== "online_service") ?? [],
);

/** 指标块色调：按分类映射（仅视觉） */
const TONE_MAP: Record<string, "brand" | "teal" | "purple" | "pink" | "amber" | "green" | "red"> = {
  training: "purple",
  offline_service: "green",
  presale: "amber",
  online_service: "teal",
};

const ICON_MAP: Record<string, string> = {
  training: "🎓",
  offline_service: "🛠️",
  presale: "💡",
  online_service: "💬",
};

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
    <OOPageHeader
      title="工作汇总"
      description="按 Excel 模板口径统计培训、线下售后、售前与线上售后四项数量，未分类任务可在此手工归类"
      badge="📊"
    >
      <el-button :loading="loading" @click="refresh">
        <span class="oo-btn-icon"><OOIcon name="refresh" :size="16" /></span>
        刷新
      </el-button>
    </OOPageHeader>

    <OOEmptyState
      v-if="!loading && data && data.total === 0 && data.wechatSessions == null"
      variant="chart"
      title="还没有任务数据"
      description="请先上传截图并识别，识别完成后这里会给出四项统计口径"
    />

    <template v-else-if="data">
      <!-- 四项统计 -->
      <div class="stat-grid">
        <!-- 线上售后：模板口径为「企微会话量：N次」，取企微一周小结，不取任务条数 -->
        <OOStatTile
          v-if="onlineItem"
          :label="`${onlineItem.label}（企微会话量/次）`"
          :icon="ICON_MAP.online_service"
          :tone="TONE_MAP.online_service"
          :value="data.wechatSessions ?? '—'"
          :hint="data.wechatMinutes ? `本周 ${data.wechatMinutes} 分钟` : '未提供企微小结'"
        />

        <OOStatTile
          v-for="it in otherItems"
          :key="it.category"
          :label="it.label"
          :icon="ICON_MAP[it.category] ?? '📌'"
          :tone="TONE_MAP[it.category] ?? 'brand'"
          :value="it.count"
          hint="按标题关键词判定"
        />
      </div>

      <!-- 企微会话量：来源说明与人工修正 -->
      <OOCard
        v-if="onlineItem"
        class="oo-mb-4"
        title="企微会话量口径"
        subtitle="线上售后数量取企业微信「一周小结」里的工作会话次数，可在截图识别后人工修正"
      >
        <template #actions>
          <el-button
            v-if="!editingSessions"
            link
            type="primary"
            size="small"
            title="修正会话量"
            @click="startEditSessions"
          >
            修正
          </el-button>
        </template>

        <div v-if="!editingSessions" class="sessions-view">
          <div class="sessions-meta">
            <el-tag v-if="data.wechatSource === 'manual'" size="small" type="warning" effect="plain">人工修正</el-tag>
            <el-tag v-else-if="data.wechatSource === 'ai'" size="small" type="success" effect="plain">截图识别</el-tag>
            <el-tag v-else size="small" type="info" effect="plain">未提供企微小结</el-tag>
            <span v-if="data.wechatMinutes" class="sessions-sub oo-num">
              本周 {{ data.wechatMinutes }} 分钟
            </span>
          </div>
          <span class="sessions-hint">识别不到企微小结时，可在此手工填写本周会话次数</span>
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
      </OOCard>

      <!-- 合计摘要 -->
      <div class="extra-row">
        <el-tag type="info" effect="plain">线下合计：<span class="oo-num">{{ data.offlineTotal }}</span> 条</el-tag>
        <el-tag type="info" effect="plain">下周计划：<span class="oo-num">{{ data.planTotal }}</span> 条</el-tag>
        <el-tag type="info" effect="plain">任务总数：<span class="oo-num">{{ data.total }}</span> 条</el-tag>
        <el-tag v-if="data.unclassifiedItems.length > 0" type="warning" effect="plain">
          未分类：<span class="oo-num">{{ data.unclassifiedItems.length }}</span> 条
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
      <OOCard
        v-if="data.unclassifiedItems.length > 0"
        class="oo-mb-4"
        title="未分类清单"
        subtitle="这些任务标题未命中任何关键词，请手工归类；归类后统计会立即更新且不再自动刷新"
        flush
      >
        <OOToolbar dense :hint="`共 ${data.unclassifiedItems.length} 条待归类`" />
        <el-table :data="data.unclassifiedItems" size="small" class="tbl">
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
      </OOCard>

      <!-- 线下明细 -->
      <OOCard title="线下工作明细" subtitle="按统计分类归组，便于核对">
        <OOEmptyState
          v-if="offlineItems.length === 0"
          variant="inbox"
          title="线下工作分区暂无任务"
          description="上传并识别线下工作截图后，这里会按培训 / 线下售后 / 售前归组展示"
        />
        <div v-else class="offline-grid">
          <OOStatTile
            v-for="it in offlineItems"
            :key="it.category"
            :label="it.label"
            :icon="ICON_MAP[it.category] ?? '📌'"
            :tone="TONE_MAP[it.category] ?? 'brand'"
            :value="it.count"
          />
        </div>
      </OOCard>
    </template>
  </div>
</template>

<style scoped>
.summary-tab {
  padding-bottom: var(--oo-space-6);
}

.oo-btn-icon {
  display: inline-flex;
  align-items: center;
  margin-right: var(--oo-space-1);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr));
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-4);
}

/* —— 企微会话量 —— */
.sessions-view {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  flex-wrap: wrap;
}

.sessions-meta {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
}

.sessions-sub {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.sessions-hint {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.sessions-edit {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
  min-height: 40px;
}

.sessions-input {
  width: 110px;
}

.extra-row {
  display: flex;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
  margin-bottom: var(--oo-space-4);
}

.rule-tip {
  margin-bottom: var(--oo-space-5);
  line-height: var(--oo-line-relaxed);
}

.tbl {
  width: 100%;
}

.offline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr));
  gap: var(--oo-space-3);
}

@media (max-width: 560px) {
  .stat-grid {
    grid-template-columns: 1fr;
  }
  .offline-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--oo-space-2);
  }
}
</style>
