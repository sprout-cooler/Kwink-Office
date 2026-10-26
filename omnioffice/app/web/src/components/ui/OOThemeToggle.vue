<script setup lang="ts">
/**
 * OOThemeToggle —— 深浅色切换按钮。
 *
 * 三档循环：跟随系统 → 浅色 → 深色 → 跟随系统。
 * 之所以不做成纯两态开关：「跟随系统」是多数用户期望的默认行为，
 * 单独一档比藏在设置里更省心。
 *
 * 无障碍：aria-label 随状态变化，键盘可达，焦点环可见。
 */
import { onMounted, onUnmounted, ref } from "vue";
import {
  THEME_SYSTEM,
  getTheme,
  onThemeChange,
  setThemeMode,
  type ThemeMode,
} from "@/composables/theme";

const mode = ref<ThemeMode>(THEME_SYSTEM);
const resolved = ref<"light" | "dark">("light");

const LABEL: Record<ThemeMode, string> = {
  system: "跟随系统主题，点击切换为浅色",
  light: "当前浅色主题，点击切换为深色",
  dark: "当前深色主题，点击切换为跟随系统",
};

const NEXT: Record<ThemeMode, ThemeMode> = {
  system: "light",
  light: "dark",
  dark: THEME_SYSTEM,
};

function sync() {
  const s = getTheme();
  mode.value = s.mode;
  resolved.value = s.resolved;
}

function toggle() {
  setThemeMode(NEXT[mode.value]);
  sync();
}

onMounted(() => {
  sync();
  const off = onThemeChange(sync);
  onUnmounted(off);
});
</script>

<template>
  <button
    class="oo-theme-toggle"
    type="button"
    :aria-label="LABEL[mode]"
    :title="LABEL[mode]"
    @click="toggle"
  >
    <svg v-if="resolved === 'dark'" viewBox="0 0 24 24" width="17" height="17" fill="none">
      <path
        d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linejoin="round"
      />
    </svg>
    <svg v-else viewBox="0 0 24 24" width="17" height="17" fill="none">
      <circle cx="12" cy="12" r="4.2" stroke="currentColor" stroke-width="1.8" />
      <path
        d="M12 2.6v2.2M12 19.2v2.2M4.2 12H2M22 12h-2.2M6.3 6.3L4.8 4.8M19.2 19.2l-1.5-1.5M17.7 6.3l1.5-1.5M4.8 19.2l1.5-1.5"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
      />
    </svg>
    <span v-if="mode === THEME_SYSTEM" class="oo-theme-badge" aria-hidden="true">自动</span>
  </button>
</template>

<style scoped>
.oo-theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 34px;
  padding: 0 11px;
  border-radius: var(--oo-radius-pill);
  border: 1px solid var(--oo-border-default);
  background: var(--oo-bg-surface);
  color: var(--oo-text-secondary);
  cursor: pointer;
  transition: all var(--oo-dur-base) var(--oo-ease-out);
}

.oo-theme-toggle:hover {
  background: var(--oo-bg-hover);
  color: var(--oo-text-brand);
  border-color: var(--oo-border-brand);
  transform: translateY(-1px);
}

.oo-theme-toggle:focus-visible {
  outline: none;
  box-shadow: var(--oo-focus-ring), var(--oo-focus-ring-offset);
}

.oo-theme-badge {
  font-size: var(--oo-text-2xs);
  font-weight: var(--oo-weight-medium);
  padding: 1px 5px;
  border-radius: var(--oo-radius-pill);
  background: var(--oo-brand-soft);
  color: var(--oo-text-brand);
}
</style>
