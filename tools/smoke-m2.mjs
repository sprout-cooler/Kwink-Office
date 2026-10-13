#!/usr/bin/env node
/**
 * M2 上传链路冒烟（经假网关，含身份头）：
 * state 初始 0 → 上传 → 列表/去重 → 原图回显 → 跨分区移动 → 非法分区 400 → 删除 → state 归零
 * 零依赖：Node 22 内置 fetch/FormData/Blob。
 */
import fs from "node:fs";

const GATEWAY = process.env.SMOKE_GATEWAY || "http://127.0.0.1:8788";
const BASE = `${GATEWAY}/app/omnioffice/api/weekly-report`;
const PNG = "e:/Project/FN/All-in-OneOffice/omnioffice/app/ui/images/icon_64.png";

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
async function json(url, init) {
  const res = await fetch(url, init);
  const text = await res.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`HTTP ${res.status} 非 JSON：${text.slice(0, 100)}`);
  }
  return { status: res.status, body, headers: res.headers };
}

let shotId = 0;

await check("state 初始：三分区结构且 total=0", async () => {
  const { status, body } = await json(`${BASE}/state`);
  assert(status === 200, `status=${status}`);
  assert(body.partitions.length === 3, `分区数=${body.partitions.length}`);
  assert(body.partitions.every((p) => p.total === 0), "存在残留数据（冒烟假设全新数据目录）");
});

await check("上传 1 张到 offline_done：accepted=1", async () => {
  const form = new FormData();
  form.append("partition", "offline_done");
  form.append("files", new Blob([fs.readFileSync(PNG)], { type: "image/png" }), "smoke.png");
  const { status, body } = await json(`${BASE}/screenshots`, { method: "POST", body: form });
  assert(status === 200, `status=${status} body=${JSON.stringify(body).slice(0, 160)}`);
  assert(body.accepted.length === 1, `accepted=${body.accepted.length}`);
  assert(body.accepted[0].recognizeStatus === "pending", "新图应为 pending");
  shotId = body.accepted[0].id;
});

await check("重复上传同图：duplicates=1、accepted=0（md5 去重）", async () => {
  const form = new FormData();
  form.append("partition", "offline_done");
  form.append("files", new Blob([fs.readFileSync(PNG)], { type: "image/png" }), "smoke2.png");
  const { body } = await json(`${BASE}/screenshots`, { method: "POST", body: form });
  assert(body.accepted.length === 0 && body.duplicates.length === 1, JSON.stringify(body));
});

await check("列表按分区过滤：offline_done=1，online_done=0", async () => {
  const a = await json(`${BASE}/screenshots?partition=offline_done`);
  const b = await json(`${BASE}/screenshots?partition=online_done`);
  assert(a.body.items.length === 1, `offline=${a.body.items.length}`);
  assert(b.body.items.length === 0, `online=${b.body.items.length}`);
});

await check("原图回显 200 且 content-type=image/png", async () => {
  const res = await fetch(`${BASE}/screenshots/${shotId}/raw`);
  assert(res.status === 200, `status=${res.status}`);
  assert((res.headers.get("content-type") || "").includes("image/png"), `ct=${res.headers.get("content-type")}`);
  await res.arrayBuffer();
});

await check("跨分区移动 offline_done → plan", async () => {
  const { status, body } = await json(`${BASE}/screenshots/${shotId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ partition: "plan" }),
  });
  assert(status === 200 && body.partition === "plan", `status=${status} body=${JSON.stringify(body)}`);
  const after = await json(`${BASE}/screenshots?partition=plan`);
  assert(after.body.items.length === 1, "移动后 plan 分区应=1");
});

await check("移动到非法分区 → 400", async () => {
  const { status } = await json(`${BASE}/screenshots/${shotId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ partition: "evil_zone" }),
  });
  assert(status === 400, `status=${status}`);
});

await check("上传到非法分区 → 400", async () => {
  const form = new FormData();
  form.append("partition", "evil_zone");
  form.append("files", new Blob([fs.readFileSync(PNG)], { type: "image/png" }), "x.png");
  const { status } = await json(`${BASE}/screenshots`, { method: "POST", body: form });
  assert(status === 400, `status=${status}`);
});

await check("删除后 state 归零", async () => {
  const { status } = await json(`${BASE}/screenshots/${shotId}`, { method: "DELETE" });
  assert(status === 200, `status=${status}`);
  const state = await json(`${BASE}/state`);
  assert(state.body.partitions.every((p) => p.total === 0), JSON.stringify(state.body.partitions));
});

console.log(`\nM2 冒烟结果：${passed} 通过 / ${failed} 失败`);
for (const r of results) console.log(r);
process.exit(failed > 0 ? 1 : 0);
