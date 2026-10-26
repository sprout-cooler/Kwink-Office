<script setup lang="ts">
/** AI 配置编辑块（全局默认与模块覆盖共用一套 UI）。
 *
 * 继承语义：模块模式下，未填写的字段显示为「继承全局」占位，
 * 提交时只传用户实际改动过的字段 → 后端只写这些字段的覆盖层。
 */
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { settingsApi, type AiConfig, type ModelDetail, type ModelTier, type ProviderPreset } from "@/api/settings";

const props = defineProps<{
  /** undefined = 全局默认配置 */
  module?: string;
  moduleName?: string;
  config: AiConfig;
  providers: ProviderPreset[];
}>();

/** 本次编辑的草稿；key 只在内存中，不回显后端明文 */
const draft = ref({ base_url: "", model: "", api_key: "" });
const touched = ref<Record<string, boolean>>({ base_url: false, model: false, api_key: false });
const saving = ref(false);
const testing = ref(false);
const testResult = ref<{ ok: boolean; message: string } | null>(null);

const isModule = computed(() => !!props.module);

function reset() {
  draft.value = {
    base_url: props.config.base_url ?? "",
    model: props.config.model ?? "",
    api_key: "",
  };
  touched.value = { base_url: false, model: false, api_key: false };
  testResult.value = null;
}
watch(() => props.config, reset, { immediate: true, deep: true });

/** 当前展示值：模块未覆盖的字段回落到全局值 + 「继承」标记 */
const inherited = computed(() => props.config.module_overrides ?? {});

const effBaseUrl = computed(() => draft.value.base_url || props.config.base_url || "");
const effModel = computed(() => draft.value.model || props.config.model || "");

/** 阿里云百炼业务空间专属域名：https://{WorkspaceId}.{region}.maas.aliyuncs.com/...
 *  必须容许 https:// 前缀，且结尾只允许 / 或字符串末尾 ——
 *  这样 "...maas.aliyuncs.com.attacker.com/v1" 这类后缀伪造不会被误判为专属域名。
 */
const WORKSPACE_DOMAIN_RE = /^(?:https?:\/\/)?[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com(?:\/|$)/i;
const isWorkspaceDomain = computed(() => WORKSPACE_DOMAIN_RE.test(effBaseUrl.value.trim()));

/** 由 base_url 反查 provider：先精确匹配预设，再识别业务空间专属域名 */
const matchedProvider = computed(() => {
  const url = effBaseUrl.value.trim().replace(/\/+$/, "");
  const exact = props.providers.find((p) => p.baseUrl && p.baseUrl.replace(/\/+$/, "") === url);
  if (exact) return exact;
  if (isWorkspaceDomain.value) {
    return props.providers.find((p) => p.id === "qwen_workspace") ?? null;
  }
  return props.providers.find((p) => p.id === "custom") ?? null;
});

/** 服务商下拉的当前值：无法识别时归到「自建兼容端点」 */
const providerId = computed(() => matchedProvider.value?.id ?? "custom");

const modelOptions = computed(() => matchedProvider.value?.models ?? []);

/** 模型档位 → 角标样式（与后端 tier 字段对应） */
const TIER_STYLE: Record<ModelTier, { type: "success" | "warning" | "info" | "danger"; label: string }> = {
  recommended: { type: "success", label: "推荐" },
  economy: { type: "success", label: "省钱" },
  stable: { type: "info", label: "稳定" },
  strong: { type: "warning", label: "高能" },
  special: { type: "info", label: "专项" },
  legacy: { type: "danger", label: "旧版" },
};

/** 带说明的模型清单（后端提供时优先，用于渲染下拉内的说明与角标） */
const modelDetails = computed<ModelDetail[]>(() => matchedProvider.value?.modelDetails ?? []);

function modelDetail(id: string): ModelDetail | undefined {
  return modelDetails.value.find((m) => m.id === id);
}

function tierOf(id: string): { type: "success" | "warning" | "info" | "danger"; label: string } | null {
  const d = modelDetail(id);
  return d ? TIER_STYLE[d.tier] : null;
}
/** 服务商说明（域名迁移提示 / 专属域名优势等） */
const activeNote = computed(() => matchedProvider.value?.note ?? "");

/** 服务地址占位提示：专属域名给出格式模板 */
const placeholderFor = computed(() => {
  const p = matchedProvider.value;
  if (p?.placeholder) return p.placeholder;
  return "https://…/v1";
});

const hasKey = computed(() => !!draft.value.api_key || props.config.has_key);
const keyPlaceholder = computed(() => {
  if (draft.value.api_key) return "已输入，留空则不修改";
  if (props.config.has_key) return `已保存（${props.config.key_masked}），留空不修改`;
  return "未配置，粘贴你的 API Key";
});

function onProviderChange(pid: string) {
  const p = props.providers.find((x) => x.id === pid);
  if (!p) return;
  // 专属域名 / 自建端点的 baseUrl 留空（需用户填自己的 WorkspaceId 或地址），
  // 清空而不是填入空串，让输入框回到 placeholder 提示态。
  draft.value.base_url = p.baseUrl || "";
  touched.value.base_url = true;
  testResult.value = null;
  // 切到有预设模型的 provider 时自动填推荐模型，减少一次输入
  if (p.models.length > 0) {
    draft.value.model = p.models[0];
    touched.value.model = true;
  }
}

function mark(field: "base_url" | "model" | "api_key") {
  touched.value[field] = true;
  testResult.value = null;
}

/** 清除某字段的模块覆盖（恢复继承全局） */
async function clearField(field: "base_url" | "model" | "api_key") {
  try {
    await settingsApi.saveAi({ [field]: "" }, props.module);
    ElMessage.success("已恢复为继承全局配置");
    await emitChanged();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  }
}

const emit = defineEmits<{ changed: [] }>();
async function emitChanged() {
  emit("changed");
}

async function test() {
  testing.value = true;
  testResult.value = null;
  try {
    const payload: Record<string, string> = {};
    if (draft.value.base_url) payload.base_url = draft.value.base_url;
    if (draft.value.model) payload.model = draft.value.model;
    if (draft.value.api_key) payload.api_key = draft.value.api_key;
    const r = await settingsApi.testAi(payload, props.module);
    testResult.value = { ok: r.ok, message: r.message };
    if (r.ok) ElMessage.success("连接成功，配置可用");
  } catch (e) {
    testResult.value = { ok: false, message: e instanceof Error ? e.message : String(e) };
  } finally {
    testing.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    // 只提交改动过的字段：模块层未改动的字段不写覆盖，保持继承
    const payload: Record<string, string> = {};
    if (touched.value.base_url) payload.base_url = draft.value.base_url;
    if (touched.value.model) payload.model = draft.value.model;
    if (touched.value.api_key) payload.api_key = draft.value.api_key;

    if (Object.keys(payload).length === 0) {
      ElMessage.info("没有需要保存的改动");
      return;
    }
    await settingsApi.saveAi(payload, props.module);
    ElMessage.success(isModule.value ? `${props.moduleName} 的 AI 配置已保存` : "全局 AI 配置已保存");
    await emitChanged();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="ai-block">
    <!-- 服务商选择 -->
    <el-form-item label="服务商">
      <el-select :model-value="providerId" placeholder="选择服务商" @change="onProviderChange">
        <el-option v-for="p in providers" :key="p.id" :label="p.label" :value="p.id" />
      </el-select>
      <el-button link type="primary" :loading="testing" @click="test">测试连接</el-button>
    </el-form-item>

    <el-alert v-if="activeNote" type="info" :closable="false" class="provider-note">
      {{ activeNote }}
    </el-alert>

    <el-form-item label="服务地址">
      <el-input
        v-model="draft.base_url"
        :placeholder="placeholderFor"
        clearable
        @input="mark('base_url')"
      />
      <el-tag v-if="isWorkspaceDomain" size="small" type="success" effect="plain" class="domain-tag">
        已识别为业务空间专属域名
      </el-tag>
      <div v-if="isModule && !inherited.base_url" class="field-actions">
        <el-tag size="small" type="success" effect="plain">本模块独立配置</el-tag>
        <el-button link size="small" @click="clearField('base_url')">恢复继承全局</el-button>
      </div>
      <div v-else-if="isModule" class="field-hint">继承全局：{{ props.config.base_url || "未配置" }}</div>
    </el-form-item>

    <el-form-item label="模型名称">
      <!-- 有预设清单时用带说明的下拉；否则（豆包 endpoint id / 自建端点）自由输入 -->
      <el-select
        v-if="modelOptions.length > 0"
        v-model="draft.model"
        filterable
        placeholder="选择模型"
        @change="mark('model')"
      >
        <el-option v-for="m in modelOptions" :key="m" :label="modelDetail(m)?.label ?? m" :value="m">
          <div class="model-opt">
            <span class="model-opt-name">
              {{ m }}
              <el-tag v-if="tierOf(m)" :type="tierOf(m)!.type" size="small" effect="plain">
                {{ tierOf(m)!.label }}
              </el-tag>
            </span>
            <span v-if="modelDetail(m)?.desc" class="model-opt-desc">{{ modelDetail(m)!.desc }}</span>
          </div>
        </el-option>
      </el-select>
      <el-input
        v-else
        v-model="draft.model"
        placeholder="如 ep-xxxx（豆包接入点）或模型名"
        clearable
        @input="mark('model')"
      />
      <div v-if="modelDetails.length > 0" class="field-hint">
        周报识别需要模型支持<b>图像输入 + JSON 结构化输出</b>。截图清晰可选 flash 省钱；版式复杂或文字模糊建议选 plus / 3.7-plus。
      </div>
      <div v-if="isModule && !inherited.model" class="field-actions">
        <el-tag size="small" type="success" effect="plain">本模块独立配置</el-tag>
        <el-button link size="small" @click="clearField('model')">恢复继承全局</el-button>
      </div>
      <div v-else-if="isModule" class="field-hint">继承全局：{{ props.config.model || "未配置" }}</div>
    </el-form-item>

    <el-form-item label="API Key">
      <el-input
        v-model="draft.api_key"
        type="password"
        show-password
        :placeholder="keyPlaceholder"
        autocomplete="off"
        @input="mark('api_key')"
      />
      <div class="field-hint">
        Key 仅保存在本 NAS，不会回传明文；识别费用由你的模型服务商按量计费
      </div>
      <div v-if="isModule && !inherited.api_key" class="field-actions">
        <el-tag size="small" type="success" effect="plain">本模块独立 Key</el-tag>
        <el-button link size="small" @click="clearField('api_key')">恢复继承全局</el-button>
      </div>
      <div v-else-if="isModule && props.config.has_key" class="field-hint">
        继承全局 Key（{{ props.config.key_masked }}）
      </div>
    </el-form-item>

    <el-alert
      v-if="testResult"
      :type="testResult.ok ? 'success' : 'error'"
      :title="testResult.message"
      :closable="true"
      show-icon
      class="test-result"
      @close="testResult = null"
    />

    <div class="ai-actions">
      <el-button type="primary" :loading="saving" :disabled="!hasKey" @click="save">
        {{ isModule ? `保存「${moduleName}」配置` : "保存全局配置" }}
      </el-button>
      <span v-if="!hasKey" class="ai-tip">需先填写 API Key 才能保存</span>
      <span v-else-if="isModule" class="ai-tip">留空/未改动的字段会继续继承全局配置</span>
    </div>
  </div>
</template>

<style scoped>
.ai-block {
  padding: var(--oo-space-1) 0 0;
}
.provider-note {
  margin-bottom: var(--oo-space-3);
  line-height: 1.6;
}
.domain-tag {
  margin-top: var(--oo-space-2);
}
/* 下拉内每个模型选项：名称 + 档位角标 + 场景说明 */
.model-opt {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--oo-space-1) 0;
  line-height: 1.45;
}
.model-opt-name {
  display: flex;
  align-items: center;
  gap: var(--oo-space-1);
  font-family: var(--oo-font-mono);
  font-size: var(--oo-text-sm);
}
.model-opt-desc {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  white-space: normal;
  line-height: 1.5;
}
.field-hint {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  line-height: 1.6;
  margin-top: var(--oo-space-1);
}
.field-actions {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  margin-top: var(--oo-space-1);
  flex-wrap: wrap;
}
.test-result {
  margin: var(--oo-space-2) 0;
}
.ai-actions {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  padding-top: var(--oo-space-2);
  flex-wrap: wrap;
}
.ai-tip {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}
</style>
