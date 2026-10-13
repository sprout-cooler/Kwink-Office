#!/usr/bin/env node
/**
 * 编码规范化（防复发固化，Agent 指南 案例 1）：给 Linux 的文本文件统一 UTF-8 无 BOM + LF。
 * 覆盖：omnioffice/ 下全部包内文本文件（cmd/、manifest、config/、wizard/、ui、docker、server、web 源码）。
 * 运行：node build/normalize-encoding.mjs   （fnpack build 前必须执行）
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..", "omnioffice");
const TEXT_EXT = new Set([".yaml", ".yml", ".json", ".py", ".ts", ".vue", ".css", ".html", ".txt", ".md"]);
const TEXT_NAME = new Set(["manifest", "privilege", "resource", "Dockerfile.api"]);
// cmd/ 下脚本无扩展名，整个目录按文本处理
const TEXT_DIR = "cmd";
// 排除：第三方依赖与构建产物（绝不修改 node_modules 等，避免破坏 npm 生成物）
const SKIP_DIRS = new Set(["node_modules", "__pycache__", ".venv", "public", "dist"]);

let fixed = 0;
let scanned = 0;

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) walk(p);
      continue;
    }
    const isText = TEXT_NAME.has(entry.name) || TEXT_EXT.has(path.extname(entry.name)) || p.includes(TEXT_DIR);
    if (!isText) continue;
    scanned += 1;
    const buf = fs.readFileSync(p);
    let text = buf.toString("utf-8");
    let changed = false;
    if (buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) {
      text = text.replace(/^\uFEFF/, "");
      changed = true;
    }
    if (text.includes("\r\n")) {
      text = text.replaceAll("\r\n", "\n");
      changed = true;
    }
    if (changed) {
      fs.writeFileSync(p, text, "utf-8");
      fixed += 1;
      console.log(`  fixed: ${path.relative(ROOT, p)}`);
    }
  }
}

walk(ROOT);
console.log(`编码规范化完成：扫描 ${scanned} 个文本文件，修复 ${fixed} 个（UTF-8 无 BOM + LF）`);
