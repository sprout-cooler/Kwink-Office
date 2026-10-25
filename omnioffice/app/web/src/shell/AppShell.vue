<script setup lang="ts">
// 四层外壳骨架（V10 2.1）：左侧通高竖栏（头像+设置+B 导航）+ 右侧（A 全局栏 / C Tab / D 面板）。
// 平台约束：非安全上下文（HTTP+局域网 iframe）禁止直接用 crypto.randomUUID 与 navigator.clipboard。
import { computed, ref } from "vue";
import { useAppStore } from "@/stores/app";
import WeeklyReportPanel from "@/modules/weekly_report/WeeklyReportPanel.vue";
import ImageToolPanel from "@/modules/image_tool/ImageToolPanel.vue";
import BizDashboardPanel from "@/modules/biz_dashboard/BizDashboardPanel.vue";
import SettingsDrawer from "./SettingsDrawer.vue";

const store = useAppStore();
const collapsed = ref(false);
const settingsOpen = ref(false);

const panels: Record<string, unknown> = {
  weekly_report: WeeklyReportPanel,
  image_tool: ImageToolPanel,
  biz_dashboard: BizDashboardPanel,
};
const activePanel = computed(() => panels[store.activeModuleId] ?? null);

// A 层通用功能候选（V10 2.4 待定）：占位入口，不影响 B/C/D 结构
const aActions = ["搜索", "消息", "新建", "帮助"];

/** 退出应用账号（NAS 登录态不动，退回选账号界面） */
const loggingOut = ref(false);
async function onLogout() {
  if (loggingOut.value) return;
  loggingOut.value = true;
  try {
    await store.logout();
  } finally {
    loggingOut.value = false;
  }
}
</script>

<template>
  <div class="oo-shell">
    <!-- 左侧通高竖栏：自顶到底，与 A 层不重叠（V10 2.3 竖栏通高） -->
    <aside class="oo-side" :class="{ collapsed }">
      <div class="oo-side-top">
        <el-tooltip :content="store.displayName" placement="right">
          <el-avatar :size="36">{{ store.displayName.slice(0, 1) }}</el-avatar>
        </el-tooltip>
        <el-tooltip v-if="!collapsed" content="设置" placement="right">
          <button class="oo-settings" aria-label="设置" @click="settingsOpen = true">⚙</button>
        </el-tooltip>
        <el-tooltip v-if="!collapsed" content="退出当前账号" placement="right">
          <button class="oo-settings" aria-label="退出" @click="onLogout">⏻</button>
        </el-tooltip>
      </div>
      <!-- B 模块导航栏：数据来自模块注册表 -->
      <nav class="oo-nav">
        <button
          v-for="m in store.modules"
          :key="m.id"
          class="oo-nav-item"
          :class="{ active: m.id === store.activeModuleId }"
          :title="m.displayName"
          @click="store.switchModule(m.id)"
        >
          <span class="oo-nav-icon">●</span>
          <span v-if="!collapsed" class="oo-nav-label">{{ m.displayName }}</span>
        </button>
      </nav>
      <button class="oo-collapse" @click="collapsed = !collapsed">{{ collapsed ? "»" : "«" }}</button>
    </aside>

    <!-- 右侧内容区：A 层仅覆盖右侧（V10 2.3 A 层不可变） -->
    <div class="oo-main">
      <header class="oo-topbar">
        <span class="oo-title">全能办公室</span>
        <span class="oo-spacer" />
        <button v-for="a in aActions" :key="a" class="oo-top-action">{{ a }}</button>
      </header>
      <!-- C 二级功能栏：随 B 切换整体替换 -->
      <div class="oo-tabs">
        <button
          v-for="t in store.activeModule?.tabs ?? []"
          :key="t.id"
          class="oo-tab"
          :class="{ active: t.id === store.activeTabId }"
          @click="store.switchTab(t.id)"
        >
          {{ t.name }}
        </button>
      </div>
      <!-- D 主操作面板 -->
      <main class="oo-panel">
        <component :is="activePanel" v-if="activePanel" :tab="store.activeTabId" />
        <el-empty v-else description="该模块面板开发中" />
      </main>
    </div>
    <!-- 设置抽屉：用户手册 + 应用信息 -->
    <SettingsDrawer v-model="settingsOpen" />
  </div>
</template>
