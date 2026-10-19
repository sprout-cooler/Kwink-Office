#!/usr/bin/env node
/**
 * FPK 打包体检（验证矩阵：打包体检层，Agent 指南 §7.1）。
 * 运行：node build/check-fpk.mjs  —— 硬性项失败退出码 1，阻断 fnpack build。
 */
import fs from "node:fs";
import path from "node:path";

const PKG = path.resolve(import.meta.dirname, "..", "omnioffice");
const problems = [];
const warns = [];

function must(cond, msg) {
  if (!cond) problems.push(msg);
}
function warn(cond, msg) {
  if (!cond) warns.push(msg);
}
function readJson(rel) {
  const p = path.join(PKG, rel);
  must(fs.existsSync(p), `缺少 ${rel}`);
  try {
    return JSON.parse(fs.readFileSync(p, "utf-8"));
  } catch (e) {
    problems.push(`${rel} 不是合法 JSON：${e.message}`);
    return null;
  }
}

// 1. manifest：存在、版本递增语义、必备字段
const manifestPath = path.join(PKG, "manifest");
must(fs.existsSync(manifestPath), "缺少 manifest");
let manifest = {};
if (fs.existsSync(manifestPath)) {
  manifest = Object.fromEntries(
    fs.readFileSync(manifestPath, "utf-8").split("\n").filter(Boolean).map((l) => l.split("=", 2)),
  );
  must(/^\d+\.\d+\.\d+$/.test(manifest.version ?? ""), `manifest 版本号非法：${manifest.version}`);
  must(manifest.appname === "omnioffice", "appname 必须为 omnioffice");
  must((manifest.os_min_version ?? "") >= "1.1.3100", "使用统一网关必须 os_min_version>=1.1.3100");
  must(manifest.ctl_stop === "true", "ctl_stop 必须为 true（具备启停状态逻辑）");
  must(manifest.checkport === "false", "走网关 Socket 转发，checkport 必须为 false");
  warn(manifest.maintainer !== "Your Name", "maintainer 仍为占位值，发布前需替换");
}

// 2. 生命周期脚本：fnpack 强制要求全套 6 个（逆向自 fnpack.exe 校验串）+ 无 BOM + LF（避坑指南 §1.3）
for (const script of ["main", "install_init", "install_callback", "uninstall_init", "uninstall_callback", "upgrade_init", "upgrade_callback"]) {
  const p = path.join(PKG, "cmd", script);
  must(fs.existsSync(p), `缺少 cmd/${script}（fnpack 强制要求）`);
}
const mainScript = path.join(PKG, "cmd", "main");
must(fs.existsSync(mainScript), "缺少 cmd/main");
if (fs.existsSync(mainScript)) {
  const buf = fs.readFileSync(mainScript);
  const noBom = !(buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf);
  const lfOnly = !buf.includes(Buffer.from("\r\n"));
  must(noBom, "cmd/main 带 BOM（Linux bash 无法识别 shebang）");
  must(lfOnly, "cmd/main 含 CRLF 换行");
  must(buf.toString("utf-8").includes("case \"$1\" in"), "cmd/main 缺少 start/stop/status 分支");
}

// 2.1 版本号三处一致性：manifest / compose APP_VERSION 兜底值 / 前端关于页
// 不一致的真机后果：应用中心显示 1.0.9 但接口自报 1.0.8，排查时极易误判「装错包」
if (manifest.version) {
  const composePath = path.join(PKG, "app", "docker", "docker-compose.yaml");
  if (fs.existsSync(composePath)) {
    const composeText = fs.readFileSync(composePath, "utf-8");
    const m = composeText.match(/APP_VERSION=\$\{APP_VERSION:-([\d.]+)\}/);
    must(
      !!m && m[1] === manifest.version,
      `版本号不一致：manifest=${manifest.version}，docker-compose APP_VERSION 兜底=${m ? m[1] : "未找到"}`,
    );
  }
}

// 3. config：privilege / resource / ui
const privilege = readJson("config/privilege");
if (privilege) {
  must(privilege.defaults?.["run-as"] === "package", "run-as 必须 package（最小权限红线）");
}
const resource = readJson("config/resource");
if (resource) {
  must(Array.isArray(resource["docker-project"]?.projects), "resource 缺 docker-project 声明");
}
const ui = readJson(`app/${manifest.desktop_uidir ?? "ui"}/config`);
if (ui) {
  const entry = ui[".url"]?.[manifest.desktop_applaunchname ?? ""];
  must(entry, "ui/config 缺少与 desktop_applaunchname 对应的入口");
  if (entry) {
    must(entry.gatewaySocket === "app.sock", "gatewaySocket 必须为 app.sock");
    must(entry.gatewayPrefix === "/app/omnioffice", "gatewayPrefix 与 GATEWAY_PREFIX 不一致");
  }
}

// 4. 图标：包根 ICON* + ui/images
for (const rel of ["ICON.PNG", "ICON_256.PNG", `app/${manifest.desktop_uidir ?? "ui"}/images/icon_64.png`, `app/${manifest.desktop_uidir ?? "ui"}/images/icon_256.png`]) {
  warn(fs.existsSync(path.join(PKG, rel)), `缺少图标 ${rel}`);
}

// 5. 服务端入口与前端产物
must(fs.existsSync(path.join(PKG, "app", "server", "app", "main.py")), "缺少 server/app/main.py");
warn(fs.existsSync(path.join(PKG, "app", "server", "public", "index.html")), "前端未构建（app/server/public/index.html 缺失）：先执行 web 构建");
must(fs.existsSync(path.join(PKG, "app", "docker", "docker-compose.yaml")), "缺少 docker-compose.yaml");
must(fs.existsSync(path.join(PKG, "app", "docker", "Dockerfile.api")), "缺少 Dockerfile.api");

// 5.0 陈旧前端产物：vite emptyOutDir=false（本机删除受保护）会让旧哈希包残留，
// 每次打包都随 COPY server/ /srv/ 进 Docker 镜像，白白撑大 FPK 且真机安装变慢。
const publicDir = path.join(PKG, "app", "server", "public");
const indexHtml = path.join(publicDir, "index.html");
if (fs.existsSync(indexHtml) && fs.existsSync(path.join(publicDir, "assets"))) {
  const html = fs.readFileSync(indexHtml, "utf-8");
  const referenced = new Set();
  for (const m of html.matchAll(/[\w.-]+\.(?:js|css|woff2?|ttf|png|jpe?g|svg|webp)/g)) referenced.add(m[0]);
  const stale = fs
    .readdirSync(path.join(publicDir, "assets"))
    .filter((n) => /^index-[\w-]+\.(js|css)$/.test(n) && !referenced.has(n));
  must(
    stale.length === 0,
    `存在陈旧前端产物（不会被引用但会打进镜像，浪费 ${(stale.length / 1).toFixed(0)} 个文件）：${stale.join(", ")} —— 先执行 node build/clean-web-assets.mjs`,
  );
  // 硬性：index.html 引用的资源必须真实存在，否则真机白屏
  for (const name of referenced) {
    if (!/^index-[\w-]+\.(js|css)$/.test(name)) continue;
    must(fs.existsSync(path.join(publicDir, "assets", name)), `index.html 引用了不存在的产物：assets/${name}`);
  }
}

// 5.05 AI 配置链路（设置页 → DB → 识别器）必须完整：
// 这是 1.0.9 的核心改动，链路任一环缺失都会导致「设置页能填但识别不生效」或「白屏」
const cfgModulePath = path.join(PKG, "app", "server", "app", "core", "settings_service.py");
must(fs.existsSync(cfgModulePath), "缺少 core/settings_service.py（设置页配置后端）");
if (fs.existsSync(cfgModulePath)) {
  const cfgText = fs.readFileSync(cfgModulePath, "utf-8");
  must(cfgText.includes("def resolve_ai"), "settings_service 缺少 resolve_ai（识别器必须经此读 DB 配置）");
  must(cfgText.includes("def reset_module_ai"), "settings_service 缺少 reset_module_ai（模块覆盖清除能力）");
}
if (fs.existsSync(path.join(PKG, "app", "server", "app", "main.py"))) {
  const mainText = fs.readFileSync(path.join(PKG, "app", "server", "app", "main.py"), "utf-8");
  must(mainText.includes('@router.get("/settings")'), "main.py 缺少 GET /settings（设置页聚合接口）");
  must(mainText.includes('@router.put("/settings/ai")'), "main.py 缺少 PUT /settings/ai（AI 配置保存）");
  must(mainText.includes("inject_wizard"), "main.py 缺少 wizard 注入（安装向导配置需落库）");
}
must(
  fs.existsSync(path.join(PKG, "app", "server", "app", "modules", "weekly_report", "recognize_queue.py")),
  "缺少 weekly_report/recognize_queue.py",
);

// 5.1 PG 驱动红线：SQLAlchemy 2.0 的 postgresql:// 默认要 psycopg3（模块名 psycopg），
// 装 psycopg2-binary 真机必崩 ModuleNotFoundError: No module named 'psycopg' → Bad Gateway（v1.0.5 真机坑）
const reqPath = path.join(PKG, "app", "server", "requirements.txt");
if (fs.existsSync(reqPath)) {
  const reqText = fs.readFileSync(reqPath, "utf-8");
  must(/^psycopg(?:\[binary\])?[><=!~]/m.test(reqText), "requirements 必须使用 psycopg[binary]（psycopg3），SQLAlchemy 2.0 默认驱动不是 psycopg2");
  must(!/^psycopg2-binary/m.test(reqText), "requirements 含 psycopg2-binary：SQLAlchemy 2.0 不会自动使用它（真机 Bad Gateway 坑）");
}

// 6. wizard：fnpack schema（逆向）：数组页 + stepTitle/items + 项 field/label/type（T13）
const wizard = readJson("wizard/config");
if (Array.isArray(wizard)) {
  for (const page of wizard) {
    must(page.stepTitle, "wizard 页缺少 stepTitle");
    must(Array.isArray(page.items) && page.items.length > 0, "wizard 页缺少 items");
    for (const item of page.items ?? []) {
      must(item.field && item.label && item.type, `wizard 项缺少 field/label/type：${JSON.stringify(item).slice(0, 60)}`);
    }
  }
  must(JSON.stringify(wizard).includes("llm_api_key"), "wizard 缺少 llm_api_key 配置项");
}
// 6.1 wizard 目录残留备份：.bak* 会被 fnpack 打进包体，且造成配置来源歧义
if (fs.existsSync(path.join(PKG, "wizard"))) {
  const backups = fs.readdirSync(path.join(PKG, "wizard")).filter((n) => /\.bak\d*$/i.test(n));
  must(backups.length === 0, `wizard 目录存在备份残留（会被打进包体）：${backups.join(", ")} —— 请删除`);
}

// 6.2 打包瘦身门禁：.dockerignore 只作用于 docker build，fnpack 打包不读它。
// node_modules（1.2 万文件）与 __pycache__ 若在包内，app.tgz 会膨胀到 26MB+，
// 真机 appcenter-cli 安装需解压上万文件。先执行 python build/slim_package.py。
//
// ⚠️ __pycache__ 必须**递归发现**而非硬编码清单：v1.0.26 新增 image_tool 模块时，
// 其目录下的字节码既没被 slim 移走、也没被这道门禁发现，一路打进 FPK。
// 硬编码清单的固有缺陷是「新增目录必然漏」，新增模块时才会暴露。
{
  const heavy = [["app/web/node_modules", "前端依赖（产物已构建进 server/public）"]];
  const present = heavy.filter(([rel]) => fs.existsSync(path.join(PKG, rel)));

  const walkPycache = (dir, out) => {
    if (!fs.existsSync(dir)) return out;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (!e.isDirectory()) continue;
      if (e.name === "node_modules" || e.name === ".git") continue;
      if (e.name === "__pycache__") out.push(path.relative(PKG, p).replace(/\\/g, "/"));
      else walkPycache(p, out);
    }
    return out;
  };
  for (const rel of walkPycache(path.join(PKG, "app", "server"), [])) {
    present.push([rel, "Python 字节码（容器内自动重建）"]);
  }

  must(
    present.length === 0,
    `以下目录会被打进 FPK：${present.map(([r, why]) => `${r} —— ${why}`).join("；")} —— 打包前请执行 python build/slim_package.py`,
  );
}

// 6.3 前端产物新鲜度（v1.0.19 真机事故固化的硬门禁）
// 事故：前端源码 10/13 00:27 改过，但打包产物仍是 10/12 22:39 的旧 bundle。
// 后果：真机加载旧前端（index-DHKYvK7t.js），不认识后端新增的 fileMissing 字段，
// 仍然直接请求 screenshots/{id}/raw → 连续 410，而服务端改动完全没生效。
// 根因：打包脚本不构建前端，靠人肉记住先 npm run build。
// 这里做兜底断言：源码比产物新，一律阻断打包。
{
  const webSrc = path.join(PKG, "app", "web", "src");
  const assetsDir = path.join(PKG, "app", "server", "public", "assets");

  const newestUnder = (dir, filter) => {
    let newest = 0;
    let hit = null;
    const walk = (d) => {
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) {
          if (e.name === "node_modules" || e.name === ".git") continue;
          walk(p);
        } else if (filter(e.name)) {
          const m = fs.statSync(p).mtimeMs;
          if (m > newest) {
            newest = m;
            hit = p;
          }
        }
      }
    };
    if (fs.existsSync(dir)) walk(dir);
    return { mtime: newest, file: hit };
  };

  if (fs.existsSync(webSrc)) {
    const src = newestUnder(webSrc, () => true);
    const out = newestUnder(assetsDir, (n) => /^index-[\w-]+\.(js|css)$/.test(n));
    must(
      out.mtime > 0,
      "server/public/assets 下没有 index-*.js|css 产物 —— 先在 omnioffice/app/web 执行 npm run build",
    );
    if (src.mtime > 0 && out.mtime > 0) {
      const staleByMin = (src.mtime - out.mtime) / 60000;
      must(
        staleByMin <= 0,
        `前端产物陈旧：源码最新改动 ${new Date(src.mtime).toISOString()}（${path
          .relative(PKG, src.file)
          .replace(/\\/g, "/")}）晚于产物 ${new Date(out.mtime).toISOString()} 约 ${staleByMin.toFixed(
          1,
        )} 分钟 —— 真机会加载旧 bundle。先在 omnioffice/app/web 执行 npm run build（或直接用 tools/package-fpk.ps1，它会自动构建）`,
      );
    }

    // index.html 必须引用 assets 里最新的那个 bundle。
    // vite 的 emptyOutDir=false 会留下旧 bundle，若 index.html 指向旧的，
    // 构建再新也没用 —— 真机加载的仍是旧文件。
    const htmlPath = path.join(PKG, "app", "server", "public", "index.html");
    if (fs.existsSync(htmlPath) && fs.existsSync(assetsDir)) {
      const html = fs.readFileSync(htmlPath, "utf-8");
      const referenced = [...html.matchAll(/(?:src|href)="[^"]*?\/?(index-[\w-]+\.(?:js|css))"/g)].map(
        (m) => m[1],
      );
      const newestJs = newestUnder(assetsDir, (n) => /^index-[\w-]+\.js$/.test(n));
      const newestCss = newestUnder(assetsDir, (n) => /^index-[\w-]+\.css$/.test(n));
      for (const [kind, newest] of [
        ["js", newestJs],
        ["css", newestCss],
      ]) {
        if (!newest.file) continue;
        const base = path.basename(newest.file);
        must(
          referenced.includes(base),
          `index.html 未引用最新 ${kind} 产物 ${base}（当前引用：${referenced.join(", ") || "无"}）` +
            ` —— 真机会加载旧 bundle。执行 node build/clean_web_assets.py 清理陈旧产物后重新构建`,
        );
      }
    }
  }
}

console.log(`打包体检：${problems.length} 硬性失败 / ${warns.length} 警告`);
for (const p of problems) console.log(`  [必须修复] ${p}`);
for (const w of warns) console.log(`  [警告] ${w}`);
process.exit(problems.length > 0 ? 1 : 0);
