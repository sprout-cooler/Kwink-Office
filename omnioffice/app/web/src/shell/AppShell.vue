<script setup lang="ts">
/**
 * 四层外壳骨架（V10 2.1）：左侧通高竖栏（头像+设置+B 导航）+ 右侧（A 全局栏 / C Tab / D 面板）。
 *
 * 【本轮 UI 重构说明】
 * 只重构视觉与交互表现，信息架构完全不变：
 *   - 左侧通高竖栏（B 模块导航 + 头像/设置/退出口）
 *   - 顶部全局栏（A 层）
 *   - 二级 Tab 栏（C 层，随 B 整体替换）
 *   - 主操作面板（D 层）
 *
 * 视觉变化：
 *   - 侧栏从深蓝硬边改为浅色玻璃质感，选中态改为品牌渐变胶囊
 *   - 导航图标从「●」占位改为服务端注册表 icon 映射的真实 SVG
 *   - Tab 改为胶囊分段控件（滑动指示），不再用下划线
 *   - 顶栏加毛玻璃与主题切换
 */
import { computed, ref } from "vue";
import { useAppStore } from "@/stores/app";
import WeeklyReportPanel from "@/modules/weekly_report/WeeklyReportPanel.vue";
import ImageToolPanel from "@/modules/image_tool/ImageToolPanel.vue";
import BizDashboardPanel from "@/modules/biz_dashboard/BizDashboardPanel.vue";
import FinancePanel from "@/modules/finance/FinancePanel.vue";
import SettingsDrawer from "./SettingsDrawer.vue";
import { OOEmptyState, OOIcon, OOThemeToggle } from "@/components/ui";

const store = useAppStore();
const collapsed = ref(false);
const settingsOpen = ref(false);

const panels: Record<string, unknown> = {
  weekly_report: WeeklyReportPanel,
  image_tool: ImageToolPanel,
  biz_dashboard: BizDashboardPanel,
  finance: FinancePanel,
};
const activePanel = computed(() => panels[store.activeModuleId] ?? null);

// A 层通用功能候选（V10 2.4 待定）：占位入口，不影响 B/C/D 结构
const aActions = [
  { label: "搜索", icon: "search" },
  { label: "消息", icon: "bell" },
  { label: "新建", icon: "plus" },
  { label: "帮助", icon: "help" },
];

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
          <div class="oo-avatar" :class="{ 'is-collapsed': collapsed }">
            <span class="oo-avatar-text">{{ store.displayName.slice(0, 1) }}</span>
          </div>
        </el-tooltip>
        <div v-if="!collapsed" class="oo-side-user">
          <p class="oo-side-name oo-truncate">{{ store.displayName }}</p>
          <p class="oo-side-role">工作空间</p>
        </div>
      </div>

      <!-- B 模块导航栏：数据来自模块注册表 -->
      <nav class="oo-nav" aria-label="模块导航">
        <button
          v-for="m in store.modules"
          :key="m.id"
          class="oo-nav-item"
          :class="{ active: m.id === store.activeModuleId }"
          :title="collapsed ? m.displayName : undefined"
          :aria-current="m.id === store.activeModuleId ? 'page' : undefined"
          @click="store.switchModule(m.id)"
        >
          <span class="oo-nav-icon">
            <OOIcon :name="m.icon" :size="19" />
          </span>
          <span v-if="!collapsed" class="oo-nav-label">{{ m.displayName }}</span>
        </button>
      </nav>

      <div class="oo-side-foot">
        <el-tooltip v-if="collapsed" content="设置" placement="right">
          <button class="oo-icon-btn" aria-label="设置" @click="settingsOpen = true">
            <OOIcon name="settings" :size="18" />
          </button>
        </el-tooltip>
        <el-tooltip v-if="!collapsed" content="设置" placement="right">
          <button class="oo-icon-btn" aria-label="设置" @click="settingsOpen = true">
            <OOIcon name="settings" :size="18" />
          </button>
        </el-tooltip>
        <el-tooltip v-if="collapsed" content="退出当前账号" placement="right">
          <button class="oo-icon-btn" aria-label="退出当前账号" :disabled="loggingOut" @click="onLogout">
            <OOIcon name="logout" :size="18" />
          </button>
        </el-tooltip>
        <el-tooltip v-if="!collapsed" content="退出当前账号" placement="right">
          <button class="oo-icon-btn" aria-label="退出当前账号" :disabled="loggingOut" @click="onLogout">
            <OOIcon name="logout" :size="18" />
          </button>
        </el-tooltip>
        <button
          class="oo-icon-btn oo-collapse-btn"
          :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
          @click="collapsed = !collapsed"
        >
          <OOIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="18" />
        </button>
      </div>
    </aside>

    <!-- 右侧内容区：A 层仅覆盖右侧（V10 2.3 A 层不可变） -->
    <div class="oo-main">
      <header class="oo-topbar">
        <div class="oo-topbar-lead">
          <span class="oo-title">{{ store.activeModule?.displayName || "全能办公室" }}</span>
          <span class="oo-topbar-sub oo-truncate">{{ store.displayName }} 的工作空间</span>
        </div>
        <span class="oo-spacer" />
        <div class="oo-topbar-actions">
          <button
            v-for="a in aActions"
            :key="a.label"
            class="oo-top-action"
            :aria-label="a.label"
          >
            <OOIcon :name="a.icon" :size="17" />
            <span class="oo-top-action-text">{{ a.label }}</span>
          </button>
          <OOThemeToggle />
        </div>
      </header>

      <!-- C 二级功能栏：随 B 切换整体替换 -->
      <div class="oo-tabs-bar">
        <div class="oo-tabs" role="tablist" aria-label="二级功能">
          <button
            v-for="t in store.activeModule?.tabs ?? []"
            :key="t.id"
            class="oo-tab"
            :class="{ active: t.id === store.activeTabId }"
            role="tab"
            :aria-selected="t.id === store.activeTabId"
            @click="store.switchTab(t.id)"
          >
            {{ t.name }}
          </button>
        </div>
      </div>

      <!-- D 主操作面板 -->
      <main class="oo-panel">
        <component
          :is="activePanel"
          v-if="activePanel"
          :key="`${store.activeModuleId}-${store.activeTabId}`"
          :tab="store.activeTabId"
        />
        <OOEmptyState v-else title="该模块面板开发中" description="功能正在建设中，敬请期待" />
      </main>
    </div>

    <!-- 设置抽屉：用户手册 + 应用信息 -->
    <SettingsDrawer v-model="settingsOpen" />
  </div>
</template>

<style scoped>
.oo-shell {
  display: flex;
  height: 100%;
  background: var(--oo-bg-app);
}

/* ------------------------------------------------------------
 * 左侧通高竖栏
 * ------------------------------------------------------------ */
.oo-side {
  width: 216px;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: var(--oo-bg-surface);
  border-right: 1px solid var(--oo-border-subtle);
  transition: width var(--oo-dur-slow) var(--oo-ease-out);
  position: relative;
  z-index: 2;
}

.oo-side.collapsed {
  width: 68px;
}

.oo-side-top {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  padding: 18px 16px 14px;
  min-height: 68px;
}

.oo-avatar {
  width: 38px;
  height: 38px;
  border-radius: var(--oo-radius-md);
  background: var(--oo-gradient-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--oo-shadow-brand);
  flex-shrink: 0;
  transition: all var(--oo-dur-base) var(--oo-ease-out);
}

.oo-avatar:hover {
  transform: scale(1.05);
}

.oo-avatar.is-collapsed {
  margin: 0 auto;
}

.oo-avatar-text {
  color: #fff;
  font-weight: var(--oo-weight-semibold);
  font-size: var(--oo-text-lg);
  line-height: 1;
}

.oo-side-user {
  min-width: 0;
  flex: 1;
}

.oo-side-name {
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
  line-height: var(--oo-line-tight);
}

.oo-side-role {
  font-size: var(--oo-text-2xs);
  color: var(--oo-text-tertiary);
  margin-top: 2px;
}

/* —— 导航 —— */
.oo-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--oo-space-2) 12px;
  overflow-y: auto;
}

.oo-nav-item {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  padding: 10px 12px;
  background: none;
  border: none;
  border-radius: var(--oo-radius-md);
  color: var(--oo-text-secondary);
  cursor: pointer;
  text-align: left;
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-medium);
  width: 100%;
  position: relative;
  transition: all var(--oo-dur-base) var(--oo-ease-out);
}

.oo-nav-item:hover {
  background: var(--oo-bg-hover);
  color: var(--oo-text-primary);
}

.oo-nav-item.active {
  background: var(--oo-gradient-brand);
  color: var(--oo-brand-on);
  box-shadow: var(--oo-shadow-brand);
}

.oo-nav-item.active:hover {
  background: var(--oo-gradient-brand);
  filter: brightness(1.05);
}

.oo-nav-item:focus-visible {
  outline: none;
  box-shadow: var(--oo-focus-ring), var(--oo-focus-ring-offset);
}

.oo-nav-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  flex-shrink: 0;
}

.oo-nav-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* —— 侧栏底部 —— */
.oo-side-foot {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px;
  border-top: 1px solid var(--oo-border-subtle);
  flex-wrap: wrap;
}

.oo-side.collapsed .oo-side-foot {
  flex-direction: column;
}

.oo-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--oo-radius-md);
  background: none;
  border: none;
  color: var(--oo-text-secondary);
  cursor: pointer;
  transition: all var(--oo-dur-base) var(--oo-ease-out);
}

.oo-icon-btn:hover:not(:disabled) {
  background: var(--oo-bg-hover);
  color: var(--oo-text-brand);
}

.oo-icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.oo-icon-btn:focus-visible {
  outline: none;
  box-shadow: var(--oo-focus-ring), var(--oo-focus-ring-offset);
}

.oo-collapse-btn {
  margin-left: auto;
}

.oo-side.collapsed .oo-collapse-btn {
  margin-left: 0;
}

/* ------------------------------------------------------------
 * 右侧主区
 * ------------------------------------------------------------ */
.oo-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.oo-topbar {
  height: 60px;
  display: flex;
  align-items: center;
  gap: var(--oo-space-4);
  padding: 0 var(--oo-space-6);
  background: color-mix(in srgb, var(--oo-bg-surface) 82%, transparent);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--oo-border-subtle);
  flex-shrink: 0;
  z-index: 3;
}

.oo-topbar-lead {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex-shrink: 0;
  gap: 1px;
}

.oo-title {
  font-size: var(--oo-text-lg);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
  line-height: var(--oo-line-tight);
  /* 不换行：窄屏下 flex 收缩会把中文标题挤成竖排 */
  white-space: nowrap;
}

.oo-topbar-sub {
  font-size: var(--oo-text-2xs);
  color: var(--oo-text-tertiary);
}

.oo-spacer {
  flex: 1;
}

.oo-topbar-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.oo-top-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border-radius: var(--oo-radius-pill);
  background: none;
  border: none;
  color: var(--oo-text-secondary);
  cursor: pointer;
  font-size: var(--oo-text-sm);
  transition: all var(--oo-dur-base) var(--oo-ease-out);
}

.oo-top-action:hover {
  background: var(--oo-bg-hover);
  color: var(--oo-text-brand);
}

.oo-top-action:focus-visible {
  outline: none;
  box-shadow: var(--oo-focus-ring), var(--oo-focus-ring-offset);
}

/* —— Tab 栏：胶囊分段 —— */
.oo-tabs-bar {
  padding: var(--oo-space-3) var(--oo-space-6) 0;
  background: var(--oo-bg-app);
  flex-shrink: 0;
}

.oo-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border-radius: var(--oo-radius-pill);
  background: var(--oo-bg-surface-2);
  border: 1px solid var(--oo-border-subtle);
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}

.oo-tabs::-webkit-scrollbar {
  display: none;
}

.oo-tab {
  background: none;
  border: none;
  border-radius: var(--oo-radius-pill);
  color: var(--oo-text-secondary);
  padding: 7px 16px;
  cursor: pointer;
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-medium);
  white-space: nowrap;
  transition: all var(--oo-dur-base) var(--oo-ease-out);
}

.oo-tab:hover:not(.active) {
  color: var(--oo-text-primary);
  background: var(--oo-bg-hover);
}

.oo-tab.active {
  background: var(--oo-bg-surface);
  color: var(--oo-text-brand);
  box-shadow: var(--oo-shadow-sm);
}

.oo-tab:focus-visible {
  outline: none;
  box-shadow: var(--oo-focus-ring), var(--oo-focus-ring-offset);
}

/* —— 内容区 —— */
.oo-panel {
  flex: 1;
  overflow: auto;
  padding: var(--oo-space-5) var(--oo-space-6) var(--oo-space-8);
  animation: oo-fade-up var(--oo-dur-slow) var(--oo-ease-out) both;
}

/* ------------------------------------------------------------
 * 响应式
 * ------------------------------------------------------------ */
@media (max-width: 1024px) {
  .oo-top-action-text {
    display: none;
  }
  .oo-top-action {
    padding: 0 9px;
  }
}

@media (max-width: 768px) {
  .oo-side {
    width: 68px;
  }
  .oo-side-user {
    display: none;
  }
  .oo-topbar {
    padding: 0 var(--oo-space-4);
    height: 56px;
    gap: var(--oo-space-2);
  }
  .oo-topbar-sub {
    display: none;
  }
  .oo-title {
    font-size: var(--oo-text-base);
  }
  /* 窄屏空间有限：隐藏次要操作（搜索/消息/新建/帮助），
     只保留主题切换 —— 这些入口是 A 层占位项，不影响 B/C/D 结构 */
  .oo-top-action {
    display: none;
  }
  .oo-tabs-bar {
    padding: var(--oo-space-2) var(--oo-space-4) 0;
  }
  .oo-panel {
    padding: var(--oo-space-4) var(--oo-space-4) var(--oo-space-7);
  }
}

/* 超窄屏（≤ 420px）：连模块名也让位，保证内容区不被挤压 */
@media (max-width: 420px) {
  .oo-topbar-lead {
    display: none;
  }
}
</style>
