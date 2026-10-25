#!/usr/bin/env node
/**
 * build-fpk.js —— 用项目内便携 fnpack 打包 .fpk（跨平台，不依赖全局安装）
 *
 * 前提：把 fnpack 可执行文件放到项目根的 .tools/ 目录
 *   - Windows:        .tools/fnpack.exe      （约 3.9 MB）
 *   - macOS / Linux:  .tools/fnpack
 *
 * 用法：
 *   node scripts/build-fpk.js                                 # 默认打包 ./myapp，自动递增 patch 版本
 *   node scripts/build-fpk.js app/mypackage                   # 指定包目录
 *   node scripts/build-fpk.js --bump minor                    # 指定递增级别 major / minor / patch
 *   node scripts/build-fpk.js --set-version 1.2.0             # 显式指定新版本号（必须高于或等于当前）
 *   node scripts/build-fpk.js --message "修复登录态丢失"        # 写入构建记录的备注
 *   node scripts/build-fpk.js --tag                      # 构建成功后自动打 tag v<新版本号>
 *   node scripts/build-fpk.js --unpack dist/x.fpk            # 只解包检查，不构建
 *
 * 为什么不用全局 fnpack：
 *   fnpack 是单文件便携程序，放 .tools/ 可随项目走 —— 队友 clone 即用、
 *   多项目可锁不同版本、CI/Docker 直接随仓库带进镜像，无需 sudo 也无需改 PATH。
 *
 * ──────────────────────────────────────────────────────────────────────────
 * ⚠️ 强制约定：每次打包必须自动递增版本号，禁止覆盖 / 复用已有 fpk 安装包
 * ──────────────────────────────────────────────────────────────────────────
 * 1. 构建前，脚本会自动把 manifest 里的 version 递增（默认 patch，可用 --bump
 *    选 major/minor，或用 --set-version 显式指定），并写回 manifest，让打出来的
 *    .fpk 内部携带一个全新的、唯一的版本号。
 * 2. 构建后自动归档到 ../releases/，文件名为
 *    <appname>_<version>_<platform>_<YYYYMMDD>[_n].fpk，
 *    version 必然不同；极端同日同版本碰撞时只追加 _n，绝不覆盖旧包。
 * 3. 每次构建追加一条记录到 ../releases/build-log.json（时间、版本、平台、产物
 *    文件名、git commit、备注），旧版本包与构建记录一一对应，便于回溯/回滚/追溯。
 * 4. releases/ 下的版本化 fpk 与 build-log.json 必须「同步留档」进 Git：.gitignore
 *    用 *.fpk 挡掉全部构建产物，再用 ! 规则放行 releases/ 目录及其下的版本化 fpk
 *    与 build-log.json（写法见 templates/gitignore.fpk）；每次构建后
 *    git add releases/ 一并提交并推送 origin + mirror 双远端——盘上不覆盖、
 *    git 里也留档。
 * 5. 版本号与 Git tag 强绑定：构建前若仓库已存在 tag v<新版本号>（说明该版本发过），
 *    直接报错退出；加 --tag 时构建成功后自动打注解 tag v<新版本号>。发版 tag 与
 *    包内版本号永远一致，杜绝「包是 1.2.0、tag 却是 v1.1.9」。
 */

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.join(__dirname, "..");
const IS_WIN = process.platform === "win32";
const FNPACK = path.join(ROOT, ".tools", IS_WIN ? "fnpack.exe" : "fnpack");

/** 定位便携 fnpack，缺失时给出可操作的提示后退出 */
function requireFnpack() {
  if (!fs.existsSync(FNPACK)) {
    console.error(`❌ 找不到便携 fnpack：${FNPACK}`);
    console.error(`   请下载对应平台的 fnpack 可执行文件放到 .tools/ 目录：`);
    console.error(`     Windows        → .tools/fnpack.exe`);
    console.error(`     macOS / Linux  → .tools/fnpack   (首次需 chmod +x)`);
    process.exit(1);
  }
  // 非 Windows 下保证可执行位（zip / git 传输后经常丢）
  if (!IS_WIN) {
    try { fs.chmodSync(FNPACK, 0o755); } catch { /* 只读文件系统忽略 */ }
  }
  return FNPACK;
}

/**
 * 解包 .fpk 并打印目录树 —— .fpk 是两层 tar.gz：
 *   外层（.fpk）→ 内层 {appname}.tgz → 真正的应用目录树
 */
function unpack(fpkPath) {
  const fpk = path.resolve(ROOT, fpkPath);
  if (!fs.existsSync(fpk)) {
    console.error(`❌ 找不到 fpk：${fpk}`);
    process.exit(1);
  }
  const outDir = path.join(path.dirname(fpk), `${path.basename(fpk)}.unpacked`);
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });

  console.log(`📦 解外层: ${path.basename(fpk)}`);
  execFileSync("tar", ["-xzf", fpk, "-C", outDir], { stdio: "inherit" });

  // 找内层 {appname}.tgz，逐个解开
  const inner = fs.readdirSync(outDir).filter((f) => f.endsWith(".tgz"));
  if (!inner.length) {
    console.warn(`⚠️  外层未发现 .tgz（可能不是标准 fpk，或格式已变）`);
  }
  for (const name of inner) {
    const innerDir = path.join(outDir, name.replace(/\.tgz$/, ""));
    fs.mkdirSync(innerDir, { recursive: true });
    console.log(`📦 解内层: ${name}`);
    execFileSync("tar", ["-xzf", path.join(outDir, name), "-C", innerDir], { stdio: "inherit" });
  }

  console.log(`\n✅ 解包完成: ${outDir}`);
  console.log(`   下一步: 检查目录树里有没有漏文件 / 多打了 node_modules、.git`);
}

/** 从包目录的 manifest 里读 version（ini 风格，无扩展名） */
function readManifestVersion(packDir) {
  const mf = path.join(packDir, "manifest");
  if (!fs.existsSync(mf)) return null;
  for (const line of fs.readFileSync(mf, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*version\s*=\s*(.+?)\s*$/i);
    if (m) return m[1];
  }
  return null;
}

/** 从 *.fpk 文件名猜 platform（x86 / arm / all），拿不到就留空 */
function guessPlatform(fpkName) {
  const m = fpkName.match(/_(x86|arm|all)(?:_|\.)/i);
  return m ? m[1].toLowerCase() : "all";
}

/**
 * 解析语义化版本号的前三段（忽略预发布 / 构建元数据），失败返回 null。
 * 例："1.2.3-beta+build.5" → { major:1, minor:2, patch:3 }
 */
function parseVersion(v) {
  const m = String(v || "").match(/^v?(\d+)\.(\d+)\.(\d+)/);
  if (!m) return null;
  return { major: +m[1], minor: +m[2], patch: +m[3] };
}

function formatVersion({ major, minor, patch }) {
  return `${major}.${minor}.${patch}`;
}

/**
 * 计算递增后的版本（不写盘）：level: "patch" | "minor" | "major"。
 * 递增会丢弃预发布/构建元数据（一次构建 = 一个新的正式产物）。
 */
function planBump(manifestPath, level) {
  const lines = fs.readFileSync(manifestPath, "utf8").split(/\r?\n/);
  let idx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*version\s*=/i.test(lines[i])) { idx = i; break; }
  }
  if (idx === -1) {
    console.error("❌ manifest 缺少 version 字段，无法自动递增版本号");
    process.exit(1);
  }
  const oldV = lines[idx].match(/^\s*version\s*=\s*(.+?)\s*$/i)[1];
  const cur = parseVersion(oldV);
  if (!cur) {
    console.error(`❌ 无法解析 manifest.version: ${oldV}（应为 x.y.z 形式）`);
    process.exit(1);
  }
  let next;
  if (level === "major") next = { major: cur.major + 1, minor: 0, patch: 0 };
  else if (level === "minor") next = { major: cur.major, minor: cur.minor + 1, patch: 0 };
  else next = { major: cur.major, minor: cur.minor, patch: cur.patch + 1 };
  return { oldV, newV: formatVersion(next) };
}

/** 把计算好的版本号写回 manifest.version（兼容行尾注释） */
function writeManifestVersion(manifestPath, newV) {
  const lines = fs.readFileSync(manifestPath, "utf8").split(/\r?\n/);
  let idx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*version\s*=/i.test(lines[i])) { idx = i; break; }
  }
  if (idx === -1) {
    console.error("❌ manifest 缺少 version 字段，无法写回版本号");
    process.exit(1);
  }
  let replaced = false;
  lines[idx] = lines[idx].replace(
    /^(\s*version\s*=\s*)(.+?)(\s*)$/i,
    (_m, p1, _p2, p3) => { replaced = true; return p1 + newV + p3; }
  );
  if (!replaced) {
    // 兼容行尾带注释的情况：version = 1.0.0  # note
    lines[idx] = lines[idx].replace(
      /^(\s*version\s*=\s*)(.+?)(\s+#.*)?$/i,
      (_m, p1, _p2, p3) => { replaced = true; return p1 + newV + (p3 || ""); }
    );
  }
  if (!replaced) {
    console.error("❌ 无法将新版本号写入 manifest.version（请检查该字段格式）");
    process.exit(1);
  }
  fs.writeFileSync(manifestPath, lines.join("\n"));
}

/**
 * 把 compose 里的 APP_VERSION 兜底值同步为同一个版本号。
 *
 * 为什么必须做（2026-10-18 修）：`check-fpk.mjs` 有「版本号三处一致性」门禁，
 * 要求 manifest.version === compose 的 `APP_VERSION=${APP_VERSION:-X.Y.Z}`。
 * 但门禁在 package-fpk.ps1 里排在 fnpack **之前**，而版本号是在 fnpack 阶段
 * 由本脚本才递增的 —— 于是：
 *   1) 门禁校验的是**递增前**的 manifest 与上轮遗留的 compose 值；
 *   2) 本脚本递增 manifest 后从不同步 compose；
 *   3) 结果：每打完一版二者必然失配，**下一版打包必被门禁拦死**
 *      （实测报 `manifest=1.0.24，docker-compose APP_VERSION 兜底=1.0.23`）。
 *
 * 同理，递增后也要把 manifest 回滚成本轮起始值吗？不需要 —— 门禁只跑一次，
 * 且下轮开始时二者已被本函数同步过，天然一致。
 */
function syncComposeVersion(packDir, newV) {
  const p = path.join(packDir, "app", "docker", "docker-compose.yaml");
  if (!fs.existsSync(p)) {
    console.log(`ℹ️未找到 compose，跳过版本同步: ${p}`);
    return;
  }
  let text = fs.readFileSync(p, "utf8");
  // v1.0.28：除了 APP_VERSION 兜底值，**image 的 tag 也要一起同步**。
  // compose 里 api/worker 用 `image: kwink/kwinkoffice:${APP_VERSION:-X.Y.Z}`
  // 指向 Docker Hub 上预构建的版本化镜像（根治 fnOS 升级时现场构建导致的超时）。
  // 若只同步 APP_VERSION，manifest 变成 1.0.29 而 image 标签仍留在 1.0.28，
  // NAS 就会拉到**上一个版本**的镜像（前端产物与包内版本不匹配）。
  const patterns = [
    { re: /(APP_VERSION=\$\{APP_VERSION:-)([\d.]+)(\})/g, label: "APP_VERSION 兜底值" },
    { re: /(image:\s*kwink\/kwinkoffice:\$\{APP_VERSION:-)([\d.]+)(\})/g, label: "image tag" },
  ];
  for (const { re, label } of patterns) {
    const matches = [...text.matchAll(re)];
    if (matches.length === 0) {
      console.error(`❌ compose 中未找到${label}，无法同步版本号`);
      process.exit(1);
    }
    // ⚠️ 必须带 g 标志：api 与 worker **各有一处** image 标签，
    //    只替首个会让 worker 仍指向旧版本镜像（worker 跑旧代码，
    //    api 与 worker 版本不一致 → 队列消费行为错乱）。
    const stale = [...new Set(matches.map((m) => m[2]))].filter((v) => v !== newV);
    if (stale.length === 0) continue;
    text = text.replace(re, `$1${newV}$3`);
    console.log(`↻ compose ${label}同步: ${stale.join(", ")} → ${newV} (${matches.length} 处)`);
  }
  fs.writeFileSync(p, text, "utf8");
}

/**
 * 把 manifest 里的 version 递增后写回，并返回 { oldV, newV }。
 * level: "patch" | "minor" | "major"
 */
function bumpVersion(manifestPath, level) {
  const { oldV, newV } = planBump(manifestPath, level);
  writeManifestVersion(manifestPath, newV);
  return { oldV, newV };
}

/**
 * 计算 --set-version 的目标版本（不写盘）。
 * 要求目标版本合法；若低于当前版本则报错（禁止把版本号往回退导致与旧包冲突）。
 */
function planSetVersion(manifestPath, target) {
  const t = parseVersion(target);
  if (!t) {
    console.error(`❌ --set-version 非法：${target}（应为 x.y.z 形式）`);
    process.exit(1);
  }
  const lines = fs.readFileSync(manifestPath, "utf8").split(/\r?\n/);
  let idx = -1, oldV = null;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*version\s*=/i.test(lines[i])) { idx = i; break; }
  }
  if (idx === -1) {
    console.error("❌ manifest 缺少 version 字段，无法设置版本号");
    process.exit(1);
  }
  oldV = lines[idx].match(/^\s*version\s*=\s*(.+?)\s*$/i)[1];
  const cur = parseVersion(oldV);
  if (cur) {
    const cmp =
      t.major !== cur.major ? t.major - cur.major :
      t.minor !== cur.minor ? t.minor - cur.minor :
      t.patch - cur.patch;
    if (cmp < 0) {
      console.error(`❌ --set-version ${target} 低于当前版本 ${oldV}，禁止回退（会覆盖/复用旧包）`);
      process.exit(1);
    }
  }
  return { oldV, newV: formatVersion(t) };
}

/** 显式设置并写回 manifest.version */
function setManifestVersion(manifestPath, target) {
  const { oldV, newV } = planSetVersion(manifestPath, target);
  writeManifestVersion(manifestPath, newV);
  return { oldV, newV };
}

/**
 * 版本化归档：复制到 ../releases/，文件名带版本+平台+日期+序号，绝不覆盖旧版。
 * 返回最终写出的归档路径，供构建记录引用。
 *
 * 注意：releases/ 下的版本化 fpk 必须提交 Git 并推双远端留档（.gitignore 已用
 * ! 规则放行 releases/，详见文件头约定 4）。
 */
function archiveToReleases(packDir, fpkPath) {
  const releasesDir = path.join(packDir, "..", "releases");
  fs.mkdirSync(releasesDir, { recursive: true });

  const appname = path.basename(packDir);
  const version = readManifestVersion(packDir) || "0.0.0";
  const platform = guessPlatform(path.basename(fpkPath));
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");

  let dst = path.join(releasesDir, `${appname}_${version}_${platform}_${date}.fpk`);
  let n = 1;
  while (fs.existsSync(dst)) {
    dst = path.join(releasesDir, `${appname}_${version}_${platform}_${date}_${n++}.fpk`);
  }
  fs.copyFileSync(fpkPath, dst);
  console.log(`📦 已归档（不覆盖）: ${dst}`);
  return dst;
}

/**
 * 把本次构建追加到 ../releases/build-log.json，保证每一个 fpk 安装包可追溯。
 */
function appendBuildLog(packDir, { appname, version, platform, fpkFile, note }) {
  const releasesDir = path.join(packDir, "..", "releases");
  fs.mkdirSync(releasesDir, { recursive: true });
  const logPath = path.join(releasesDir, "build-log.json");

  let log = [];
  if (fs.existsSync(logPath)) {
    try { log = JSON.parse(fs.readFileSync(logPath, "utf8")); } catch { log = []; }
  }

  let commit = "";
  try {
    commit = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: path.join(packDir, ".."),
      stdio: ["ignore", "pipe", "ignore"],
    }).toString().trim();
  } catch { /* 非 git 仓库或命令不可用，忽略 */ }

  log.push({
    ts: new Date().toISOString(),
    appname,
    version,
    platform,
    fpk: path.basename(fpkFile),
    commit: commit || null,
    note: note || "",
  });

  fs.writeFileSync(logPath, JSON.stringify(log, null, 2));
  console.log(`📝 已写入构建记录: ${logPath}`);
}

/**
 * 检查 git tag 是否已存在（版本号与 tag 强绑定用）。
 * 非 git 仓库 / 没有 git 命令时返回 false，不阻塞构建。
 */
function gitTagExists(tag) {
  try {
    const out = execFileSync("git", ["tag", "--list", tag], {
      cwd: ROOT, stdio: ["ignore", "pipe", "ignore"],
    }).toString().trim();
    return out.length > 0;
  } catch {
    return false;
  }
}

/**
 * 打注解 tag（--tag 用）。已存在则跳过——构建前的碰撞检查会先拦一道。
 * 返回是否成功；打 tag 失败不影响已产出的 fpk，只警告。
 */
function createAnnotatedTag(tag, fpkName) {
  try {
    execFileSync("git", ["tag", "-a", tag, "-m", `release ${tag} (fpk: ${fpkName})`], {
      cwd: ROOT, stdio: ["ignore", "pipe", "ignore"],
    });
    console.log(`🏷️  已打 tag: ${tag}`);
    console.log(`   ⚠️ tag 指向当前 HEAD（尚未包含本次 manifest 递增改动）；`);
    console.log(`      若发版 commit 在此之后提交，执行 git tag -f ${tag} 可把 tag 移到最终提交。`);
    return true;
  } catch (e) {
    console.error(`⚠️  打 tag 失败（不影响已产出的 fpk，请手动 git tag -a ${tag}）: ${String(e.message).split("\n")[0]}`);
    return false;
  }
}

function build(packDir, opts) {
  const dir = path.resolve(ROOT, packDir);

  if (!fs.existsSync(dir)) {
    console.error(`❌ 包目录不存在：${dir}`);
    process.exit(1);
  }

  const manifestPath = path.join(dir, "manifest");
  if (!fs.existsSync(manifestPath)) {
    console.error("❌ 找不到 manifest，无法递增版本号（fpk 打包前必须先有 manifest）");
    process.exit(1);
  }

  // 1) 先计算并校验新版本（不写盘）
  const bump = opts.setVersion
    ? planSetVersion(manifestPath, opts.setVersion)
    : planBump(manifestPath, opts.bump);

  // 1b) 版本号与 Git tag 强绑定：v<新版本号> 已存在 = 该版本发过，禁止复用。
  //     放在写回 manifest 与 requireFnpack 之前：失败构建不消耗版本号。
  const tag = `v${bump.newV}`;
  if (gitTagExists(tag)) {
    console.error(`❌ Git 已存在 tag ${tag}——该版本已发版过，版本号禁止复用。`);
    console.error(`   请换更高版本重新构建：--bump minor / --bump major / --set-version X.Y.Z`);
    process.exit(1);
  }

  // 1c) 校验通过，写回 manifest —— 每个 fpk 都带唯一新版本
  writeManifestVersion(manifestPath, bump.newV);
  // 同步 compose 兜底值：否则下一版打包会被 check-fpk.mjs 的版本一致性门禁拦死
  // （门禁跑在 fnpack 之前，比较的是本轮递增后的 manifest 与上轮遗留的 compose 值）
  syncComposeVersion(dir, bump.newV);
  console.log(`🔖 版本号 ${bump.oldV} → ${bump.newV}（已写回 manifest，禁止复用旧版本号）`);

  // 2) 用便携 fnpack 打包
  const fnpack = requireFnpack();
  console.log(`🔨 用便携 fnpack 打包: ${dir}`);
  // 用 execFileSync（而非 execSync 拼字符串）：路径含空格/中文也不会被拆坏
  execFileSync(fnpack, ["build", "--directory", dir], { stdio: "inherit" });

  // 3) 找最新产出的 .fpk
  const produced = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".fpk"))
    .sort((a, b) => fs.statSync(path.join(dir, b)).mtimeMs - fs.statSync(path.join(dir, a)).mtimeMs);

  const fpk = produced[0] || fs
    .readdirSync(path.dirname(dir))
    .filter((f) => f.endsWith(".fpk"))[0];

  if (fpk) {
    const p = path.join(dir, fpk);
    const target = fs.existsSync(p) ? p : path.join(path.dirname(dir), fpk);
    const size = (fs.statSync(target).size / 1024).toFixed(1);
    console.log(`\n✅ 产物: ${target}  (${size} KB)`);
    console.log(`   查包内容: tar -tzf "${target}"`);
    console.log(`   解包断言: node scripts/build-fpk.js --unpack "${target}"`);

    // 4) 强制版本化归档，不覆盖历史
    const dst = archiveToReleases(dir, target);
    // 5) 写入可追溯构建记录
    appendBuildLog(dir, {
      appname: path.basename(dir),
      version: readManifestVersion(dir) || "0.0.0",
      platform: guessPlatform(path.basename(target)),
      fpkFile: dst,
      note: opts.note,
    });
    // 6) 同步留档提醒：版本化 fpk 与构建记录必须提交 Git 并推双远端（只提醒、不自动提交）
    const builtVersion = readManifestVersion(dir) || "0.0.0";
    console.log(`\n🗄️  版本化 fpk 同步留档（盘上不覆盖、git 里也留档）:`);
    console.log(`   git add releases/`);
    console.log(`   git commit -m "v${builtVersion}: <本次改动>"`);
    console.log(`   git tag -a v${builtVersion} -m "release v${builtVersion}"   # 版本号与 tag 强绑定，勿换号`);
    console.log(`   git push origin main --tags && git push mirror main --tags`);

    // 7) --tag：构建成功后自动打注解 tag，发版 tag 与包内版本号永远一致
    if (opts.tag) {
      createAnnotatedTag(tag, path.basename(dst));
      console.log(`   git push origin ${tag} && git push mirror ${tag}   # 推送 tag 到双远端`);
    }
  } else {
    console.error(`❌ 没找到构建产物 .fpk，请检查 fnpack build 是否成功`);
    process.exit(1);
  }
}

/** 极简参数解析：提取 --unpack / --bump / --set-version / --message / --tag 与位置参数 */
function parseArgs(argv) {
  const opts = { bump: "patch", setVersion: null, note: "", packDir: "myapp", unpack: null, tag: false };
  const consumed = new Set();
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--unpack") { opts.unpack = argv[i + 1]; consumed.add(i); consumed.add(i + 1); }
    else if (a === "--bump") { opts.bump = (argv[i + 1] || "patch").toLowerCase(); consumed.add(i); consumed.add(i + 1); }
    else if (a === "--set-version") { opts.setVersion = argv[i + 1]; consumed.add(i); consumed.add(i + 1); }
    else if (a === "--message") { opts.note = argv[i + 1] || ""; consumed.add(i); consumed.add(i + 1); }
    else if (a === "--tag") { opts.tag = true; }
  }
  const positional = argv.filter((_, i) => !consumed.has(i));
  if (opts.unpack === null && positional.length) opts.packDir = positional[0];
  if (!["major", "minor", "patch"].includes(opts.bump)) {
    console.error(`❌ --bump 取值非法：${opts.bump}（应为 major / minor / patch）`);
    process.exit(1);
  }
  return opts;
}

const opts = parseArgs(process.argv.slice(2));
if (opts.unpack !== null) {
  unpack(opts.unpack);
} else {
  build(opts.packDir, opts);
}
