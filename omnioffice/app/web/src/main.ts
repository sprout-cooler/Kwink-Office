import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
// 样式层顺序不能乱：
//   1) element-plus 基础样式（必须最先，被后面覆盖）
//   2) tokens.css        —— 设计 token + Element Plus 变量覆写
//   3) element-theme.css —— EP 组件级样式覆写
//   4) base.css          —— 重置与通用类
import "./styles/tokens.css";
import "./styles/element-theme.css";
import "./styles/base.css";
import { initTheme } from "./composables/theme";

// ⚠️ 主题必须在 mount() 之前同步应用：晚一步会先渲染一帧浅色再切深色（闪白）。
initTheme();

// SPA 初始数据必须在 App.vue onMounted 显式加载（避坑指南：watch immediate 依赖 null 时会被跳过）
createApp(App).use(createPinia()).use(ElementPlus).mount("#app");
