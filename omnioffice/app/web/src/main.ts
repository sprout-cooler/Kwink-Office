import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import "./styles/theme.css";

// SPA 初始数据必须在 App.vue onMounted 显式加载（避坑指南：watch immediate 依赖 null 时会被跳过）
createApp(App).use(createPinia()).use(ElementPlus).mount("#app");
