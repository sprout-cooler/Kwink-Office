import { defineStore } from "pinia";
import { authApi, type AppUser, type AuthStatus } from "@/api/auth";
import { sessionApi, type Identity, type ModuleMeta } from "@/api/session";

/** 全局状态：登录身份 + 模块注册表（B/C 层数据源，V10 2.3「B 层为准」规则）。
 *
 * 两级登录态：
 *   1. NAS 网关身份（-/api/session）——证明「是这台 NAS 的哪个系统用户」；
 *   2. 应用账号（-/auth/me）——决定数据归属，未登录时一律不加载业务数据。
 */
export const useAppStore = defineStore("app", {
  state: () => ({
    identity: null as Identity | null,
    modules: [] as ModuleMeta[],
    activeModuleId: "" as string,
    activeTabId: "" as string,
    loaded: false,
    error: "" as string,
    // ---- 应用账号登录态 ----
    authRequired: false as boolean,
    authInitialized: false as boolean,
    nasUser: "" as string,
    user: null as AppUser | null,
  }),
  getters: {
    activeModule(state): ModuleMeta | undefined {
      return state.modules.find((m) => m.id === state.activeModuleId);
    },
    /** 是否已进入可用状态（必要时先过应用账号登录这一层） */
    authed(state): boolean {
      return !state.authRequired || state.user !== null;
    },
    displayName(state): string {
      return state.user?.displayName || state.identity?.username || "?";
    },
  },
  actions: {
    /** 切换模块：C 层整体替换，D 层重置为默认 Tab（V10 2.3 关键规则） */
    switchModule(moduleId: string) {
      const m = this.modules.find((x) => x.id === moduleId);
      if (!m) return;
      this.activeModuleId = moduleId;
      this.activeTabId = m.tabs[0]?.id ?? "";
    },
    switchTab(tabId: string) {
      this.activeTabId = tabId;
    },
    /**
     * 启动引导：先探登录门，再决定是否拉业务数据。
     *
     * 顺序不能反：应用账号未登录时 /api/session 会 401，
     * 先调它会把「需要登录」误判成「会话过期 / 服务异常」，给用户错误指引。
     */
    async bootstrap() {
      try {
        const status: AuthStatus = await authApi.status();
        this.authRequired = status.required;
        this.authInitialized = status.initialized;
        this.nasUser = status.nasUser;
        this.user = status.user;
        if (status.required && !status.user) {
          this.error = "";
          return; // 停在登录页
        }
        await this.loadWorkspace();
        this.error = "";
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
      } finally {
        this.loaded = true;
      }
    },
    /** 加载业务工作区（模块注册表 + 当前身份） */
    async loadWorkspace() {
      const [identity, { modules }] = await Promise.all([sessionApi.get(), sessionApi.modules()]);
      this.identity = identity;
      this.modules = modules;
      if (modules.length > 0) this.switchModule(modules[0].id);
    },
    /** 登录/注册成功后回调：补拉业务数据，避免整页刷新导致周报批次状态丢失 */
    async onAuthed(user: AppUser) {
      this.user = user;
      this.authInitialized = true;
      this.error = "";
      try {
        await this.loadWorkspace();
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
      } finally {
        this.loaded = true;
      }
    },
    async logout() {
      try {
        await authApi.logout();
      } finally {
        // 退出后清空内存态：否则下一次登录前的短暂空窗会看到上一个账号的数据
        this.user = null;
        this.identity = null;
        this.modules = [];
        this.activeModuleId = "";
        this.activeTabId = "";
      }
    },
  },
});
