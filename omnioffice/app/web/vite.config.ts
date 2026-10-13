import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";

export default defineConfig({
  // base 用相对路径：真机经网关子路径访问，配合服务端注入的 <base href>（避坑指南 §1.2）
  base: "./",
  plugins: [vue()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      // 本地开发直连后端 TCP（IDENTITY_MODE=mock）；网关形态联调走 tools/fake-gateway.mjs
      "/api": "http://127.0.0.1:8787",
      "/ws": { target: "ws://127.0.0.1:8787", ws: true },
    },
  },
  build: {
    // 产物直接落到服务端静态目录，Docker 构建时随 server 一起拷入镜像
    outDir: path.resolve(__dirname, "../server/public"),
    // 不清空输出目录：vite 默认会递归删除 outDir，本机受删除保护拦截易失败；
    // 产物带内容哈希，旧文件不会被引用，多余文件随 .gitignore 忽略即可。
    emptyOutDir: false,
  },
});
