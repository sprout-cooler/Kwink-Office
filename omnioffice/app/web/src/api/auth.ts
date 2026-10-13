/** 应用账号 API：注册 / 登录 / 登出 / 当前账号。
 *
 * 登录态是 HttpOnly Cookie，由服务端下发，前端**不存 token**——
 * 这样即使页面被注入脚本也偷不走会话；前端只关心「我是不是已登录」。
 */
import { api } from "./client";

export interface AppUser {
  id: number;
  username: string;
  displayName: string;
  isAdmin: boolean;
  createdAt: string | null;
  lastLoginAt: string | null;
}

export interface AuthStatus {
  /** 是否强制要求应用账号登录（mock 开发环境为 false） */
  required: boolean;
  /** 当前 NAS 账号下是否已创建过应用账号 */
  initialized: boolean;
  user: AppUser | null;
  nasUser: string;
  canRegister: boolean;
}

export const authApi = {
  /** 登录门探测：决定前端是否展示登录页（未登录也要能调，故不走 401 拦截） */
  async status(): Promise<AuthStatus> {
    return api<AuthStatus>("/auth/status");
  },

  /** 注册并直接登录；首个账号自动成为管理员 */
  async register(body: {
    username: string;
    password: string;
    confirm?: string;
    displayName?: string;
    remember?: boolean;
  }): Promise<{ ok: boolean; user: AppUser; isFirst: boolean }> {
    return api("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async login(body: {
    username: string;
    password: string;
    remember?: boolean;
  }): Promise<{ ok: boolean; user: AppUser }> {
    return api("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async logout(): Promise<{ ok: boolean }> {
    return api("/auth/logout", { method: "POST" });
  },

  async me(): Promise<{ user: AppUser; dataKey: string; nasUser: string }> {
    return api("/auth/me");
  },
};
