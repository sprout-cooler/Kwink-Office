/** 设置 API：应用级通用配置 + 全局默认 AI + 各模块独立 AI 覆盖。
 *
 * 分层语义（与后端 settings_service 一致）：
 *   全局默认 AI  →  所有模块继承的兜底配置
 *   模块独立 AI  →  留空表示继承全局；填值只影响该模块
 *
 * api_key 只写不读：后端永不回传明文，前端只保存用户本次输入的值用于提交。
 */
import { api, API_BASE } from "./client";

export interface AiConfig {
  base_url: string;
  model: string;
  has_key: boolean;
  key_masked: string;
  module: string | null;
  module_overrides: Record<"base_url" | "model" | "api_key", boolean>;
  inherited: Record<"base_url" | "model" | "api_key", boolean>;
}

/** 百炼模型档位说明（前端下拉按此渲染说明与角标） */
export type ModelTier =
  | "recommended"
  | "economy"
  | "stable"
  | "strong"
  | "special"
  | "legacy";

export interface ModelDetail {
  id: string;
  label: string;
  tier: ModelTier;
  desc: string;
}

export interface ProviderPreset {
  id: string;
  label: string;
  baseUrl: string;
  models: string[];
  /** 带说明的模型清单（存在时下拉展示 desc 与档位角标） */
  modelDetails?: ModelDetail[];
  /** 需用户填写的地址模板（如业务空间专属域名含个人 WorkspaceId） */
  placeholder?: string;
  /** 服务商说明（域名迁移提示、优势等） */
  note?: string;
}

export interface AppSettingMeta {
  value: number;
  label: string;
  type: string;
  min: number;
  max: number;
  desc: string;
}

export interface ModuleSettings {
  id: string;
  displayName: string;
  icon: string;
  route: string;
  tabCount: number;
  ai: AiConfig;
  overridden: boolean;
}

export interface SettingsPayload {
  ai_default: AiConfig;
  ai_modules: ModuleSettings[];
  providers: ProviderPreset[];
  app: Record<string, AppSettingMeta>;
}

export const settingsApi = {
  /** 一次性拉取设置页全部数据（聚合接口，避免多次往返） */
  async get(): Promise<SettingsPayload> {
    return api<SettingsPayload>("/settings");
  },

  /** 保存应用级通用配置 */
  async saveApp(payload: Record<string, number>): Promise<{ app: Record<string, AppSettingMeta> }> {
    return api("/settings/app", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  /** 保存 AI 配置；module 缺省 = 全局默认，传 module = 该模块覆盖层 */
  async saveAi(
    payload: { base_url?: string; model?: string; api_key?: string },
    module?: string,
  ): Promise<{ ai: AiConfig }> {
    const q = module ? `?module=${encodeURIComponent(module)}` : "";
    return api(`/settings/ai${q}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  /** 清除某模块全部 AI 覆盖，回到继承全局默认 */
  async resetModule(module: string): Promise<{ ai: AiConfig }> {
    return api(`/settings/ai/${encodeURIComponent(module)}`, { method: "DELETE" });
  },

  /** 测试连通性：不传 api_key 时用已保存的 Key；传了则用传入值（可先试再存） */
  async testAi(
    payload: { base_url?: string; model?: string; api_key?: string },
    module?: string,
  ): Promise<{ ok: boolean; message: string; model: string; baseUrl: string }> {
    const q = module ? `?module=${encodeURIComponent(module)}` : "";
    return api(`/settings/ai/test${q}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  /** 导出当前账号的应用配置为 JSON 文件下载（默认不含 API Key） */
  exportUrl(includeSecrets = false): string {
    return `${API_BASE}/settings/export${includeSecrets ? "?includeSecrets=1" : ""}`;
  },

  /** 导入配置文件恢复当前账号配置；空值字段表示「不改」，不会清空现有配置 */
  async importConfig(payload: unknown): Promise<{
    ok: boolean;
    applied: { app: string[]; ai_default: string[]; ai_modules: string[] };
    skipped: string[];
    settings: SettingsPayload;
  }> {
    return api("/settings/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
};

/** 触发配置文件下载（用隐藏 a 标签，链接点击即可带上 Cookie 会话） */
export function downloadSettingsFile(includeSecrets = false): void {
  const a = document.createElement("a");
  a.href = settingsApi.exportUrl(includeSecrets);
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
