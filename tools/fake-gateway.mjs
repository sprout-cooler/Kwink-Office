#!/usr/bin/env node
/**
 * 本地假网关（平台规则：本地必须经「只转发前缀内请求」的假网关才能暴露前缀类问题，避坑指南 §1.2）。
 * 行为对齐飞牛统一网关：
 *  - 仅转发 /app/omnioffice/* 前缀内请求，其余 404；
 *  - 保留完整前缀原样转发（不重写路径）；
 *  - 注入 X-Trim-* 身份头（模拟 NAS 登录态），可用环境变量覆盖。
 * 用法：node tools/fake-gateway.mjs   （网关 :8788 → 后端 :8787）
 * 零第三方依赖（Node 22 内置模块）。
 */
import http from "node:http";
import net from "node:net";

const GATEWAY_PORT = Number(process.env.FAKE_GW_PORT || 8788);
const BACKEND_HOST = process.env.FAKE_GW_TARGET_HOST || "127.0.0.1";
const BACKEND_PORT = Number(process.env.FAKE_GW_TARGET_PORT || 8787);
const PREFIX = process.env.GATEWAY_PREFIX || "/app/omnioffice";

const IDENTITY = {
  "x-trim-userid": process.env.FAKE_UID || "1000",
  "x-trim-username": process.env.FAKE_USERNAME || "devuser",
  "x-trim-isadmin": process.env.FAKE_ISADMIN || "true",
};

const server = http.createServer((req, res) => {
  if (!req.url || !req.url.startsWith(`${PREFIX}/`)) {
    res.writeHead(404, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ error: "NOT_IN_PREFIX", message: `假网关仅转发 ${PREFIX}/* 请求` }));
    return;
  }
  const headers = { ...req.headers, ...IDENTITY };
  const proxy = http.request(
    { host: BACKEND_HOST, port: BACKEND_PORT, method: req.method, path: req.url, headers },
    (up) => {
      res.writeHead(up.statusCode || 502, up.headers);
      up.pipe(res);
    },
  );
  proxy.on("error", () => {
    res.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ error: "BACKEND_DOWN", message: `后端 ${BACKEND_HOST}:${BACKEND_PORT} 未启动` }));
  });
  req.pipe(proxy);
});

// WebSocket 升级透传（保留前缀，注入身份头）
server.on("upgrade", (req, socket) => {
  if (!req.url || !req.url.startsWith(`${PREFIX}/`)) {
    socket.destroy();
    return;
  }
  const lines = [`${req.method} ${req.url} HTTP/1.1`];
  for (const [k, v] of Object.entries(req.headers)) {
    if (k === "connection" || k === "upgrade") continue;
    lines.push(`${k}: ${v}`);
  }
  lines.push(`connection: ${req.headers.connection}`);
  lines.push(`upgrade: ${req.headers.upgrade}`);
  for (const [k, v] of Object.entries(IDENTITY)) lines.push(`${k}: ${v}`);
  const upstream = net.connect(BACKEND_PORT, BACKEND_HOST, () => {
    upstream.write(lines.join("\r\n") + "\r\n\r\n");
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on("error", () => socket.destroy());
});

server.listen(GATEWAY_PORT, () => {
  console.log(`[fake-gateway] http://127.0.0.1:${GATEWAY_PORT}${PREFIX}/ -> ${BACKEND_HOST}:${BACKEND_PORT}`);
  console.log(`[fake-gateway] identity uid=${IDENTITY["x-trim-userid"]} admin=${IDENTITY["x-trim-isadmin"]}`);
});
