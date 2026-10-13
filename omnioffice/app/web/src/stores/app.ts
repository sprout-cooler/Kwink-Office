import { defineStore } from "pinia";
import { sessionApi, type Identity, type ModuleMeta } from "@/api/session";

/** 全局状态：登录身份 + 模块注册表（B/C 层数据源，V10 2.3「B 层为准」规则）。 */
export const useAppStore = defineStore("app", {
  state: () => ({
    identity: null as Identity | null,
    modules: [] as ModuleMeta[],
    activeModuleId: "" as string,
    activeTabId: "" as string,
    loaded: false,
    error: "" as string,
  }),
  getters: {
    activeModule(state): ModuleMeta | undefined {
      return state.modules.find((m) => m.id === state.activeModuleId);
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
    async bootstrap() {
      try {
        const [identity, { modules }] = await Promise.all([sessionApi.get(), sessionApi.modules()]);
        this.identity = identity;
        this.modules = modules;
        if (modules.length > 0) this.switchModule(modules[0].id);
        this.error = "";
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
      } finally {
        this.loaded = true;
      }
    },
  },
});
