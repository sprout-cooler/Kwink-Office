#!/usr/bin/env node
/**
 * 服务端冒烟测试（验证矩阵第 2 层，Agent 指南 §7.1）。
 * 假设：后端已启动（TCP 8787，IDENTITY_MODE=gateway）、假网关已启动（8788）、前端已构建（可选）。
 * 运行：node tools/smoke.mjs   —— 零依赖，全部断言失败即退出码 1。
 */
const DIRECT = process.env.SMOKE_DIRECT || "http://127.0.0.1:8787";
const GATEWAY = process.env.SMOKE_GATEWAY || "http://127.0.0.1:8788";
const PREFIX = "/app/omnioffice";

let passed = 0;
let failed = 0;
const results = [];

async function check(name, fn) {
  try {
    await fn();
    passed += 1;
    results.push(`  PASS  ${name}`);
  } catch (e) {
    failed += 1;
    results.push(`  FAIL  ${name}\n        ${e.message}`);
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function jsonOf(url, headers = {}) {
  const res = await fetch(url, { headers: { accept: "application/json", ...headers } });
  const text = await res.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`HTTP ${res.status} 返回非 JSON：${text.slice(0, 120)}`);
  }
  return { status: res.status, body, text };
}

await check("health 直连 200 且 JSON（双前缀之一）", async () => {
  const { status, body } = await jsonOf(`${DIRECT}/api/health`);
  assert(status === 200, `status=${status}`);
  assert(body.status === "ok", `body=${JSON.stringify(body)}`);
});

await check("health 经网关前缀 200（双前缀之二，平台规则）", async () => {
  const { status, body } = await jsonOf(`${GATEWAY}${PREFIX}/api/health`);
  assert(status === 200 && body.status === "ok", `status=${status} body=${JSON.stringify(body)}`);
});

await check("session 带 X-Trim 头返回身份（身份提供者）", async () => {
  const { status, body } = await jsonOf(`${DIRECT}/api/session`, {
    "x-trim-userid": "1000",
    "x-trim-username": "devuser",
    "x-trim-isadmin": "true",
  });
  assert(status === 200, `status=${status}`);
  assert(body.uid === "1000" && body.isAdmin === true, `body=${JSON.stringify(body)}`);
});

await check("session 无身份头 401（不信任未鉴权请求）", async () => {
  const { status } = await jsonOf(`${DIRECT}/api/session`);
  assert(status === 401, `status=${status}`);
});

await check("modules 经网关返回注册表（B 层数据源 + 假网关注入身份）", async () => {
  const { status, body } = await jsonOf(`${GATEWAY}${PREFIX}/api/modules`);
  assert(status === 200, `status=${status}`);
  const ids = body.modules.map((m) => m.id);
  assert(ids.includes("weekly_report"), `modules=${ids}`);
  assert(body.modules[0].tabs.some((t) => t.id === "upload"), "C 层 Tab 缺失");
});

await check("周报业务接口经网关前缀可达（模块路由）", async () => {
  // 用稳定 DTO（state）断言业务路由可达 + 身份经网关注入（session 已单独断言 uid）
  const { status, body } = await jsonOf(`${GATEWAY}${PREFIX}/api/weekly-report/state`);
  assert(status === 200, `status=${status}`);
  assert(Array.isArray(body.partitions) && body.partitions.length === 3, `partitions=${JSON.stringify(body)}`);
  assert(typeof body.periodStart === "string" && body.periodStart.length === 10, "periodStart 缺失");
});

await check("index.html 注入 <base href>（前端已构建时，避坑指南 §1.2）", async () => {
  const res = await fetch(`${GATEWAY}${PREFIX}/`);
  const text = await res.text();
  if (res.status === 503) {
    results.push(`  SKIP  (前端未构建：${text.slice(0, 80)})`);
    return;
  }
  assert(res.status === 200, `status=${res.status}`);
  assert(text.includes(`<base href="${PREFIX}/">`), "未注入 base href");
});

await check("静态 .js 返回 JavaScript MIME（slim 镜像缺 mime.types 白屏坑，真机复现）", async () => {
  const res = await fetch(`${GATEWAY}${PREFIX}/`);
  const html = await res.text();
  if (res.status === 503) {
    results.push("  SKIP  (前端未构建)");
    return;
  }
  const m = html.match(/(?:src|href)="\.?\/(assets\/[^"]+\.js)"/);
  assert(m, "index.html 未找到 assets/*.js 引用");
  const js = await fetch(`${GATEWAY}${PREFIX}/${m[1]}`);
  const ct = js.headers.get("content-type") ?? "";
  assert(js.status === 200 && ct.includes("javascript"), `js content-type=${ct}（浏览器将拒绝执行 → 白屏）`);
  // 避坑指南 §1.6：必须真实取到 JS 文本体，否则 SPA 兜底返回 HTML 也会「200」
  const body = await js.text();
  assert(!body.trimStart().startsWith("<!DOCTYPE"), "assets/*.js 返回了 HTML（SPA 兜底吞掉静态资源 → 真机白屏）");
});

await check("静态 .css 返回 CSS MIME（与 §1.7 叠加的第二条白屏路径）", async () => {
  const res = await fetch(`${GATEWAY}${PREFIX}/`);
  const html = await res.text();
  if (res.status === 503) {
    results.push("  SKIP  (前端未构建)");
    return;
  }
  const m = html.match(/href="\.?\/(assets\/[^"]+\.css)"/);
  assert(m, "index.html 未找到 assets/*.css 引用");
  const css = await fetch(`${GATEWAY}${PREFIX}/${m[1]}`);
  const ct = css.headers.get("content-type") ?? "";
  assert(css.status === 200 && ct.includes("text/css"), `css content-type=${ct}`);
});

await check("带网关前缀的静态资源可直取（剥前缀逻辑生效，§1.6 核心）", async () => {
  const res = await fetch(`${GATEWAY}${PREFIX}/`);
  const html = await res.text();
  if (res.status === 503) {
    results.push("  SKIP  (前端未构建)");
    return;
  }
  const m = html.match(/(?:src|href)="\.?\/(assets\/[^"]+\.js)"/);
  assert(m, "index.html 未找到 assets/*.js 引用");
  // 完整带前缀路径（网关转发后的真实形态），确认不会被 SPA 兜底吞掉
  const js = await fetch(`${GATEWAY}${PREFIX}/${m[1]}`);
  const ct = js.headers.get("content-type") ?? "";
  assert(ct.includes("javascript"), `带前缀取 js 得到 content-type=${ct}（剥前缀失效）`);
});

await check("路径穿越被拒绝（V10 8.12 / §3.1 安全红线）", async () => {
  const res = await fetch(`${GATEWAY}${PREFIX}/assets/../../app/server/app/main.py`, { redirect: "manual" });
  const text = res.status === 200 ? await res.text() : "";
  assert(!text.includes("FastAPI"), "路径穿越成功读到了包内源码");
});

await check("设置聚合接口返回分类结构（应用配置页数据源）", async () => {
  const { status, body } = await jsonOf(`${GATEWAY}${PREFIX}/api/settings`);
  assert(status === 200, `status=${status}`);
  assert(body.ai_default && typeof body.ai_default.has_key === "boolean", "缺少 ai_default");
  assert(Array.isArray(body.ai_modules) && body.ai_modules.length >= 1, "缺少 ai_modules");
  assert(Array.isArray(body.providers) && body.providers.length >= 1, "缺少 providers");
  assert(body.app && typeof body.app === "object", "缺少 app 通用配置");
  const m = body.ai_modules.find((x) => x.id === "weekly_report");
  assert(m, "模块列表缺少 weekly_report");
  assert(typeof m.overridden === "boolean", "模块缺少 overridden 标记");
  // Key 只以 has_key/masked 形式出现，绝不回传明文
  assert(!("api_key" in m.ai), "ai 配置回传了 api_key 字段（明文泄露风险）");
});

await check("设置接口未鉴权时 401（不信任未鉴权请求，§3.1）", async () => {
  const res = await fetch(`${DIRECT}/api/settings`);
  assert(res.status === 401, `status=${res.status}（应为 401）`);
});

await check("AI 连通性测试接口可返回结构化结果（不抛未捕获异常）", async () => {
  const res = await fetch(`${DIRECT}/api/settings/ai/test`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-trim-userid": "1000" },
    body: JSON.stringify({ base_url: "http://127.0.0.1:9/none", model: "x", api_key: "sk-smoke" }),
  });
  assert(res.status === 200, `status=${res.status}`);
  const body = await res.json();
  assert(typeof body.ok === "boolean" && typeof body.message === "string", `body=${JSON.stringify(body)}`);
});

console.log(`\n冒烟结果：${passed} 通过 / ${failed} 失败`);
for (const r of results) console.log(r);
process.exit(failed > 0 ? 1 : 0);
