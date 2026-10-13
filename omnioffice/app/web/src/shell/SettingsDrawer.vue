<script setup lang="ts">
// 设置抽屉（V10 2.4 A 层功能）：应用配置（分类） + 用户手册 + 关于。
// 分类设计：通用设置 / AI 模型（全局默认）/ 各模块独立 AI ——
// 后续新增模块只需在模块注册表登记，这里自动出现该模块的配置项，无需改前端。
import { onMounted, ref, watch } from "vue";
import { ElDrawer, ElTabs, ElTabPane, ElCard, ElDescriptions, ElDescriptionsItem, ElTag, ElMessage, ElMessageBox, ElForm, ElFormItem, ElInputNumber, ElCollapse, ElCollapseItem, ElBadge, ElCheckbox } from "element-plus";
import { settingsApi, downloadSettingsFile, type SettingsPayload, type AppSettingMeta } from "@/api/settings";
import { API_BASE } from "@/api/client";
import AiConfigForm from "./AiConfigForm.vue";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ "update:modelValue": [val: boolean] }>();

const tab = ref("config");
const loading = ref(false);
const data = ref<SettingsPayload | null>(null);
/** 版本号来自后端 /health，避免前端硬编码与 manifest 漂移 */
const appVersion = ref("-");

/** 应用级配置草稿 */
const appDraft = ref<Record<string, number>>({});
const savingApp = ref(false);

async function load() {
  loading.value = true;
  try {
    const [d, health] = await Promise.all([
      settingsApi.get(),
      fetch(`${API_BASE}/health`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ]);
    data.value = d;
    if (health?.version) appVersion.value = health.version;
    const draft: Record<string, number> = {};
    for (const [k, v] of Object.entries(d.app)) draft[k] = (v as AppSettingMeta).value;
    appDraft.value = draft;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  if (props.modelValue) void load();
});
watch(
  () => props.modelValue,
  (v) => {
    if (v) void load();
  },
);

/** 子组件保存成功后刷新聚合数据 */
async function reload() {
  await load();
}

async function saveApp() {
  savingApp.value = true;
  try {
    await settingsApi.saveApp(appDraft.value);
    ElMessage.success("通用设置已保存");
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    savingApp.value = false;
  }
}

async function resetModuleAi(moduleId: string, name: string) {
  try {
    await ElMessageBox.confirm(
      `确定清除「${name}」的独立 AI 配置？清除后该模块将继承全局默认配置。`,
      "恢复继承全局",
      { type: "warning", confirmButtonText: "清除覆盖", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await settingsApi.resetModule(moduleId);
    ElMessage.success("已恢复继承全局配置");
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

// ------------------------------------------------------- 配置导入 / 导出
//
// 导出默认不含 API Key：配置文件常被随手转发留档，默认不把密钥带出去。
// 导入时「空值字段 = 不改」，因此导入一份不含 Key 的文件不会把现有 Key 抹掉。

const includeSecrets = ref(false);
const importing = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

function doExport() {
  downloadSettingsFile(includeSecrets.value);
  ElMessage.info(includeSecrets.value ? "已导出（含 API Key，请妥善保管）" : "已导出（不含 API Key）");
}

function pickFile() {
  fileInput.value?.click();
}

async function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = ""; // 允许连续导入同一个文件
  if (!file) return;
  let payload: unknown;
  try {
    payload = JSON.parse(await file.text());
  } catch {
    ElMessage.error("不是有效的 JSON 配置文件");
    return;
  }
  importing.value = true;
  try {
    const r = await settingsApi.importConfig(payload);
    data.value = r.settings;
    ElMessage.success(
      `已导入：通用 ${r.applied.app.length} 项、AI 全局 ${r.applied.ai_default.length} 项、` +
        `模块覆盖 ${r.applied.ai_modules.length} 项` +
        (r.skipped.length ? `（忽略未知项 ${r.skipped.length} 个）` : ""),
    );
    await load();
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : String(err));
  } finally {
    importing.value = false;
  }
}
</script>

<template>
  <ElDrawer
    :model-value="modelValue"
    title="设置"
    size="720px"
    direction="rtl"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <ElTabs v-model="tab" v-loading="loading" class="settings-tabs">
      <!-- ============ 应用配置（分类） ============ -->
      <ElTabPane name="config">
        <template #label>
          <span class="tab-label">应用配置</span>
          <ElBadge
            v-if="data && !data.ai_default.has_key"
            is-dot
            type="warning"
            title="尚未配置 AI"
          />
        </template>

        <div v-if="!data" class="empty-hint">加载中…</div>
        <template v-else>
          <el-alert
            v-if="!data.ai_default.has_key"
            type="warning"
            show-icon
            :closable="false"
            class="cfg-alert"
            title="尚未配置 AI 模型"
            description="周报的截图识别依赖大模型。请在下方「AI 模型（全局默认）」中填写 API Key；后续模块可各自配置不同模型。"
          />

          <!-- 分类一：通用设置 -->
          <ElCard shadow="never" class="cfg-card">
            <template #header>
              <div class="card-head">
                <b>通用设置</b>
                <span class="card-sub">对所有模块生效的应用级参数</span>
              </div>
            </template>
            <ElForm label-width="200px" label-position="left">
              <ElFormItem
                v-for="(meta, key) in data.app"
                :key="key"
                :label="(meta as AppSettingMeta).label"
              >
                <ElInputNumber
                  v-model="appDraft[key]"
                  :min="(meta as AppSettingMeta).min"
                  :max="(meta as AppSettingMeta).max"
                />
                <div class="field-hint">{{ (meta as AppSettingMeta).desc }}</div>
              </ElFormItem>
            </ElForm>
            <div class="cfg-actions">
              <ElButton type="primary" :loading="savingApp" @click="saveApp">保存通用设置</ElButton>
              <span class="field-hint">识别并发调整后需重启应用生效；其余项立即生效</span>
            </div>
          </ElCard>

          <!-- 分类四：配置备份与迁移 -->
          <ElCard shadow="never" class="cfg-card">
            <template #header>
              <div class="card-head">
                <b>配置备份与迁移</b>
                <span class="card-sub">导出的是当前账号的配置；导入只影响你自己的账号</span>
              </div>
            </template>
            <div class="cfg-actions">
              <ElCheckbox v-model="includeSecrets">导出时包含 API Key</ElCheckbox>
              <ElButton :disabled="!data" @click="doExport">导出配置文件</ElButton>
              <ElButton type="primary" :loading="importing" @click="pickFile">导入配置文件</ElButton>
              <input
                ref="fileInput"
                type="file"
                accept="application/json,.json"
                class="hidden-input"
                @change="onFilePicked"
              />
            </div>
            <div class="field-hint">
              默认不导出 API Key；导入时配置里为空的项表示「保持现状」，不会被清空。
            </div>
          </ElCard>

          <!-- 分类二：AI 模型（全局默认） -->
          <ElCard shadow="never" class="cfg-card">
            <template #header>
              <div class="card-head">
                <b>AI 模型（全局默认）</b>
                <ElTag size="small" effect="plain">所有模块默认继承这里</ElTag>
              </div>
            </template>
            <ElForm label-width="110px" label-position="left">
              <AiConfigForm
                :config="data.ai_default"
                :providers="data.providers"
                @changed="reload"
              />
            </ElForm>
          </ElCard>

          <!-- 分类三：各模块独立 AI -->
          <ElCard shadow="never" class="cfg-card">
            <template #header>
              <div class="card-head">
                <b>各模块 AI 配置</b>
                <span class="card-sub">留空即继承全局；按需为不同模块指定不同模型</span>
              </div>
            </template>

            <div v-if="data.ai_modules.length === 0" class="empty-hint">暂无可配置的模块</div>

            <div
              v-for="m in data.ai_modules"
              :key="m.id"
              class="module-block"
            >
              <div class="module-head">
                <div class="module-title">
                  <b>{{ m.displayName }}</b>
                  <span class="module-sub">{{ m.tabCount }} 个功能页</span>
                </div>
                <div class="module-tags">
                  <ElTag v-if="m.overridden" size="small" type="success" effect="plain">独立配置</ElTag>
                  <ElTag v-else size="small" type="info" effect="plain">继承全局</ElTag>
                  <ElTag v-if="m.ai.has_key" size="small" type="success" effect="dark">AI 可用</ElTag>
                  <ElTag v-else size="small" type="info" effect="plain">继承全局 Key</ElTag>
                  <ElButton
                    v-if="m.overridden"
                    link
                    size="small"
                    @click="resetModuleAi(m.id, m.displayName)"
                  >
                    清除覆盖
                  </ElButton>
                </div>
              </div>

              <ElCollapse>
                <ElCollapseItem :title="m.overridden ? '编辑本模块 AI 配置' : '为本模块单独配置 AI（可选）'">
                  <ElForm label-width="110px" label-position="left">
                    <AiConfigForm
                      :module="m.id"
                      :module-name="m.displayName"
                      :config="m.ai"
                      :providers="data.providers"
                      @changed="reload"
                    />
                  </ElForm>
                </ElCollapseItem>
              </ElCollapse>
            </div>
          </ElCard>
        </template>
      </ElTabPane>

      <!-- 用户手册 -->
      <ElTabPane label="用户手册">
        <div class="manual">
          <h3>欢迎使用全能办公室</h3>
          <p class="manual-intro">
            全能办公室是一个统一的工作入口，把分散在各系统的工作内容收拢到一处。内置周报模块，支持截图上传、AI 识别、数据校对与周报导出。
          </p>

          <ElCard shadow="never" class="manual-card">
            <template #header><b>1. 配置大模型（首次使用必读）</b></template>
            <ol>
              <li>点击左侧竖栏顶部的 <b>⚙ 设置</b>，进入「<b>应用配置</b>」页。</li>
              <li>在「<b>AI 模型（全局默认）</b>」中选择服务商与模型：
                <ul>
                  <li><b>通义千问（推荐）</b>：前往 <a href="https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key" target="_blank">阿里云百炼</a> 申请 API Key。</li>
                  <li><b>豆包</b>：前往 <a href="https://console.volcengine.com/ark" target="_blank">火山方舟</a> 创建视觉模型接入点，模型填 endpoint id（<code>ep-xxxx</code>）。</li>
                </ul>
              </li>
              <li>
                <b>模型怎么选</b>：周报识别要求模型支持<b>图像输入 + JSON 结构化输出</b>，下拉里已按此筛选
                <ul>
                  <li><b>qwen3.8-flash</b>（推荐）：现役轻量旗舰，1M 上下文，省钱且够用，综合首选</li>
                  <li><b>qwen3.8-max</b>：能力最强，版式复杂或截图模糊时用它，费用最高</li>
                  <li><b>qwen3.7-plus / qwen3.7-flash</b>：能力接近旗舰 / 更快更省，按预算选</li>
                  <li><b>qwen3.5-ocr</b>：仅文字提取专项，不判断任务归属与时间语义，周报一般不首选</li>
                  <li><b>qwen3-vl-plus / qwen3-vl-flash</b>：旧版，官方已不推荐，部分地域会返回 404</li>
                </ul>
              </li>
              <li>
                <b>关于阿里云百炼的服务地址（404 必看）</b>：官方已将模型推理接入分为三种域名
                <ul>
                  <li><b>业务空间专属域名（推荐，且多数地域必须使用）</b>：<code>https://{WorkspaceId}.{地域}.maas.aliyuncs.com/compatible-mode/v1</code>。最快拿法：百炼控制台「API Key」页<b>导出 CSV</b>，里面的 <code>openAiCompatible</code> 一列就是完整地址，整段粘贴到「服务地址」即可；或在创建 Key 的弹窗里复制 <b>API Host</b>。优势：仅访问当前业务空间、并发更高、超时 3600 秒。</li>
                  <li><b>DashScope 通用域名</b>：<code>https://dashscope.aliyuncs.com/compatible-mode/v1</code>（北京）、<code>dashscope-intl</code>（新加坡）、<code>cn-hongkong.dashscope</code>（中国香港）、<code>dashscope-us</code>（美国）。⚠️ 官方自 <b>2026-09-30 起不再支持新特性</b>，用它调用 qwen3.8 / qwen3.7 等现役模型会返回 <b>404「地址或模型不存在」</b>。</li>
                </ul>
                填写专属域名后，页面会自动识别并显示「已识别为业务空间专属域名」标签。各地域的 API Key 与模型列表<b>不能跨地域混用</b>。地域 ID 可在 <a href="https://help.aliyun.com/zh/model-studio/regions" target="_blank">官方地域说明</a> 查看（北京 <code>cn-beijing</code>、新加坡 <code>ap-southeast-1</code>、中国香港 <code>cn-hongkong</code> 等）。
              </li>
              <li>粘贴 API Key，点「<b>测试连接</b>」确认可用，再点保存。</li>
              <li>也可以在<b>安装应用时</b>的向导中填写，效果相同。</li>
              <li>后续如需为不同模块指定不同模型，可在「<b>各模块 AI 配置</b>」中单独设置 —— 不填则继承全局默认。</li>
            </ol>
          </ElCard>

          <ElCard shadow="never" class="manual-card">
            <template #header><b>2. 上传任务截图</b></template>
            <ol>
              <li>进入「周报 → 任务上传」。</li>
              <li>页面显示三个分区卡片：
                <ul>
                  <li><b>本周线下工作</b>：日常开发/运维/线下任务、线下培训/售后/售前回访截图</li>
                  <li><b>线上售后</b>：企业微信「一周小结」截图（包含「本周处理了 N 次工作会话」的那张），系统据此自动读取企微会话量</li>
                  <li><b>下周工作计划</b>：排期/计划类截图（如后续日期的工单），导出时填入 Excel「下周计划」区</li>
                </ul>
              </li>
              <li>点击分区卡片上传，或直接拖拽图片到分区卡片上。</li>
              <li>误传的图片可拖到另一分区卡片，或用右下角下拉框调整归属。</li>
              <li>重复图片（同 md5）自动跳过，不会重复入库。</li>
              <li>支持 PNG / JPEG / WEBP，默认单张 ≤ 10MB（可在设置中调整）。</li>
            </ol>
          </ElCard>

          <ElCard shadow="never" class="manual-card">
            <template #header><b>3. AI 识别</b></template>
            <ol>
              <li>上传完成后，点击顶部「开始识别」按钮。</li>
              <li>系统将逐张截图发送给大模型，自动提取每条任务的：
                <ul>
                  <li>任务标题（原文，不改写）</li>
                  <li>开始时间与结束时间（原样抄录，后端自动归一化为标准格式）</li>
                  <li>任务状态（如 已完成/进行中/待处理）</li>
                  <li>识别置信度（0~1）</li>
                </ul>
              </li>
              <li>识别状态实时更新：待识别 → 识别中 → 已识别 / 识别失败。</li>
              <li>识别失败的截图可点击「重试失败」重新识别。</li>
              <li><b>分类规则</b>：截图归属哪个分区由上传时选择决定，AI 不做内容推断。</li>
              <li><b>工单截图</b>：标题即为工作内容，预计时间即为对应日期。</li>
              <li><b>企微一周小结</b>：识别后不会生成任务条目，而是自动读取「处理了 N 次工作会话」的次数，显示在「工作汇总」页的线上售后卡片上（标记为「截图识别」）；识别不准时点卡片上的「修正」直接改数，修正后标记为「人工修正」。</li>
            </ol>
          </ElCard>

          <ElCard shadow="never" class="manual-card">
            <template #header><b>4. 数据校对</b></template>
            <ol>
              <li>进入「周报 → 识别校对」，按分区查看识别出的任务列表。</li>
              <li>识别置信度低的字段会高亮提醒。</li>
              <li>落在周报周期之外的任务（如跨周工单）会标记为「越界」，需人工确认。</li>
              <li>解析失败的时间字段标红，可手动修正——修正后保存回写。</li>
              <li>校对完成后进入下一步导出。</li>
            </ol>
            <p class="manual-tip"><b>提示</b>：时间格式支持多种写法，系统会自动识别：2026-10-09、10月9日、Oct 9、周四、261012 等。系统不做猜测，无法解析的会标红让你手动修正。</p>
          </ElCard>

          <ElCard shadow="never" class="manual-card">
            <template #header><b>5. 周报导出</b></template>
            <ol>
              <li>进入「周报 → 预览与导出」，确认本周数据无误。</li>
              <li>在「周报模板」区可<b>上传多个模板版本</b>并在下拉框中随时切换；当前选中版本即本次导出使用的版本（未手动选择时默认最新版），切换会立即绑定到当前周报批次。</li>
              <li>导出 Excel 的版式与所选模板完全一致：标题、合并单元格、边框字体均沿用模板，只往对应区域填内容。</li>
              <li>导出内容按分区落位：
                <ul>
                  <li><b>本周线下工作</b>：按星期几填入每日区域，培训/线下售后/售前数量进汇总区；</li>
                  <li><b>线上售后</b>：汇总区写「企微会话量：N次」（N 取一周小结，可在工作汇总页修正）；</li>
                  <li><b>下周工作计划</b>：任务标题逐条填入「下周计划」区。</li>
                </ul>
              </li>
              <li>导出前检查未通过（低置信度未确认、时间无法解析等）时，导出按钮会禁用，按提示处理后再导出。</li>
            </ol>
          </ElCard>

          <ElCard shadow="never" class="manual-card">
            <template #header><b>常见问题</b></template>
            <p><b>Q：在哪里配置 AI？</b></p>
            <p>左侧竖栏顶部 ⚙ → 「应用配置」→ 「AI 模型（全局默认）」。这是识别功能的前提。</p>
            <p><b>Q：不同模块能用不同模型吗？</b></p>
            <p>可以。在「各模块 AI 配置」中展开对应模块单独设置即可。不设置则继承全局默认，节省配置成本。</p>
            <p><b>Q：识别速度慢？</b></p>
            <p>20 张截图约需 30~60 秒（取决于模型响应速度和网络）。可在「通用设置」中调高识别并发数（默认 3），或改用更快的模型（如 qwen-vl-plus）。</p>
            <p><b>Q：识别结果不准？</b></p>
            <p>可在「识别校对」中手动修正。修正后保存即可，无需重新识别。如果整张图识别质量很差，可在「任务上传」中删除后重新上传。</p>
            <p><b>Q：Key 安全吗？</b></p>
            <p>Key 仅存储在本 NAS 的应用配置中，不上传任何第三方服务器，且界面上不回显明文。识别请求直接从你的 NAS 发送到模型服务商。</p>
            <p><b>Q：升级后数据会丢吗？</b></p>
            <p>不会。应用数据（含你保存的配置）存储在 NAS 的独立数据卷中，升级安装只更新应用代码，不影响数据。</p>
          </ElCard>
        </div>
      </ElTabPane>

      <!-- 关于 -->
      <ElTabPane label="关于">
        <ElDescriptions :column="1" border>
          <ElDescriptionsItem label="应用名称">全能办公室</ElDescriptionsItem>
          <ElDescriptionsItem label="版本">v{{ appVersion }}</ElDescriptionsItem>
          <ElDescriptionsItem label="平台">飞牛 fnOS（FPK 应用）</ElDescriptionsItem>
          <ElDescriptionsItem label="技术栈">
            Vue 3 + FastAPI + PostgreSQL + Redis
          </ElDescriptionsItem>
          <ElDescriptionsItem label="识别引擎">
            <ElTag type="info" effect="plain">用户自带 VLM API Key</ElTag>
          </ElDescriptionsItem>
          <ElDescriptionsItem label="数据存储">
            本 NAS 独立数据卷，升级不丢失
          </ElDescriptionsItem>
        </ElDescriptions>
      </ElTabPane>
    </ElTabs>
  </ElDrawer>
</template>

<style scoped>
.settings-tabs {
  --el-tabs-header-height: 44px;
}
/* ---- 应用配置页 ---- */
.tab-label {
  margin-right: 4px;
}
.cfg-alert {
  margin-bottom: 14px;
}
.cfg-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: normal;
}
.field-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.cfg-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 4px;
  flex-wrap: wrap;
}
.hidden-input {
  display: none;
}
.module-block {
  padding: 12px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}
.module-block:first-of-type {
  border-top: none;
}
.module-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.module-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.module-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.module-tags {
  display: flex;
  align-items: center;
  gap: 6px;
}
.empty-hint {
  padding: 24px 0;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
/* ---- 用户手册 ---- */
.manual {
  padding: 0 4px 24px;
  line-height: 1.7;
}
.manual h3 {
  margin: 0 0 8px;
  font-size: 18px;
}
.manual-intro {
  color: var(--el-text-color-secondary);
  margin: 0 0 16px;
}
.manual-card {
  margin-bottom: 16px;
}
.manual-card ol {
  padding-left: 20px;
  margin: 0;
}
.manual-card li {
  margin-bottom: 6px;
}
.manual-card code {
  background: var(--el-fill-color-light);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.9em;
}
.manual-card a {
  color: var(--el-color-primary);
}
.manual-tip {
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--el-color-warning-light-9);
  border-radius: 4px;
  font-size: 0.9em;
}
</style>
