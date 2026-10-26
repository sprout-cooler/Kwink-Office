/**
 * 图表配色 —— 与设计 token 对齐。
 *
 * 【为什么集中管理】
 * ECharts 的 option 是 JS 对象，拿不到 CSS 变量。
 * 若每个图表各写各的 hex，改主题色时要逐个找，且深色模式下必然失配。
 * 这里把图表色板与 tokens.css 保持同一套值，并提供深浅色感知。
 *
 * 【深色模式如何生效】
 * ECharts option 在组件里是 computed，依赖一个响应式的「主题版本号」。
 * 主题切换时该版本号变化 → computed 重算 → setOption 重新渲染。
 */

/** 主题版本号：主题切换时自增，触发所有图表重算。 */
let themeVersion = 0;
const themeListeners = new Set<(v: number) => void>();

/** 订阅主题变化，返回取消订阅函数 */
export function onChartThemeChange(fn: (v: number) => void): () => void {
  themeListeners.add(fn);
  return () => themeListeners.delete(fn);
}

/** 手动通知图表主题变更（切换主题时调用） */
export function notifyChartThemeChange(): void {
  themeVersion += 1;
  themeListeners.forEach((fn) => fn(themeVersion));
}

export function getChartThemeVersion(): number {
  return themeVersion;
}

/** 是否处于深色模式 */
export function isDarkTheme(): boolean {
  try {
    return document.documentElement.classList.contains("dark");
  } catch {
    return false;
  }
}

/**
 * 图表调色板。
 *
 * 取自 tokens.css 的语义色：
 *   品牌蓝 #4C6FFF / 青 #14B8A6 / 紫 #7C5CF0 / 粉 #E8638F
 *   琥珀 #D99114 / 绿 #639922 / 天蓝 #378ADD
 * 深色模式下整体提亮（暗底上原色偏暗），保证图形可辨。
 */
export function chartPalette(): string[] {
  const dark = isDarkTheme();
  if (dark) {
    return ["#8AA0FF", "#5FD6C6", "#B9A7F5", "#F5A8C0", "#F5C777", "#A8D07A", "#85B7EB"];
  }
  return ["#4C6FFF", "#14B8A6", "#7C5CF0", "#E8638F", "#D99114", "#639922", "#378ADD"];
}

/** 依次取色（超出长度时循环） */
export function chartColor(index: number): string {
  const p = chartPalette();
  return p[index % p.length];
}

/** 坐标轴/文字颜色（随主题） */
export function chartTextColor(): string {
  return isDarkTheme() ? "#9BA3B4" : "#5A6478";
}

/** 网格线颜色（随主题） */
export function chartSplitLineColor(): string {
  return isDarkTheme() ? "rgba(255,255,255,0.08)" : "rgba(21,26,38,0.06)";
}

/** 提示框背景（随主题） */
export function chartTooltipBg(): string {
  return isDarkTheme() ? "rgba(31,35,45,0.96)" : "rgba(255,255,255,0.98)";
}

/** 提示框文字色（随主题） */
export function chartTooltipTextColor(): string {
  return isDarkTheme() ? "#E8EBF2" : "#1A2033";
}

/** 提示框边框色（随主题） */
export function chartTooltipBorder(): string {
  return isDarkTheme() ? "#333A49" : "#E3E8F0";
}
