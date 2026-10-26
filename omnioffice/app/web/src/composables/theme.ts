/**
 * 主题（深浅色）管理。
 *
 * 【为什么必须在首屏渲染前应用】
 * 深色模式靠 <html class="dark"> 切换 CSS 变量。若等 Vue 挂载后再加 class，
 * 首屏会先用浅色渲染一帧再切深色 —— 用户看到明显的「闪白」。
 * 所以本模块导出一个同步函数，在 main.ts 里于 createApp().mount() 之前调用。
 *
 * 【为什么用 localStorage 而不是 Pinia】
 * 主题需要在 Vue 初始化前就知道，Pinia 此时还没创建。
 * localStorage 同步读取，无异步延迟。
 */

// ⚠️ 循环依赖注意：chart-theme 不 import 本模块，故此处单向引用安全。
import { notifyChartThemeChange } from "@/composables/chart-theme";

/** 存储键 */
const STORAGE_KEY = "oo-theme";
/** 跟随系统的标记值 */
export const THEME_SYSTEM = "system";
export type ThemeMode = "light" | "dark" | typeof THEME_SYSTEM;

export interface ThemeState {
  /** 用户选择：light / dark / system */
  mode: ThemeMode;
  /** 实际生效的主题 */
  resolved: "light" | "dark";
}

function readStored(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === THEME_SYSTEM) return v;
  } catch {
    // 隐私模式/存储被禁：降级为跟随系统，不影响功能
  }
  return THEME_SYSTEM;
}

function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

/** 把主题写到 <html> 上（加/去 .dark 类 + 更新 color-scheme） */
function apply(el: HTMLElement, resolved: "light" | "dark"): void {
  el.classList.toggle("dark", resolved === "dark");
  // color-scheme 让浏览器把滚动条、表单控件、canvas 背景也切到深色
  el.style.colorScheme = resolved;
}

let currentMode: ThemeMode = THEME_SYSTEM;
let currentResolved: "light" | "dark" = "light";
const listeners = new Set<(s: ThemeState) => void>();

/**
 * 同步初始化主题 —— 必须在 mount() 之前调用。
 * 返回当前生效状态。
 */
export function initTheme(): ThemeState {
  currentMode = readStored();
  currentResolved = currentMode === THEME_SYSTEM ? (prefersDark() ? "dark" : "light") : currentMode;
  apply(document.documentElement, currentResolved);

  // 跟随系统时，系统主题变化要实时响应
  try {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (currentMode !== THEME_SYSTEM) return;
      currentResolved = mq.matches ? "dark" : "light";
      apply(document.documentElement, currentResolved);
      notify();
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  } catch {
    // 老浏览器无 matchMedia：忽略
  }

  return { mode: currentMode, resolved: currentResolved };
}

/** 设置主题模式并持久化 */
export function setThemeMode(mode: ThemeMode): ThemeState {
  currentMode = mode;
  currentResolved = mode === THEME_SYSTEM ? (prefersDark() ? "dark" : "light") : mode;
  apply(document.documentElement, currentResolved);
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // 存储不可用：本次会话内仍然生效，只是不持久
  }
  notify();
  return { mode: currentMode, resolved: currentResolved };
}

/** 读取当前状态 */
export function getTheme(): ThemeState {
  return { mode: currentMode, resolved: currentResolved };
}

/** 订阅主题变化（供 Vue 组件用） */
export function onThemeChange(fn: (s: ThemeState) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify(): void {
  const s = getTheme();
  listeners.forEach((fn) => fn(s));
  // 图表配色是 JS 对象（拿不到 CSS 变量），主题切换后需主动通知重绘
  notifyChartThemeChange();
}
