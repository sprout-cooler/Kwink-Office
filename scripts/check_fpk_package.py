#!/usr/bin/env python3
"""
check_fpk_package.py —— 飞牛 fnOS 应用包（.fpk 源目录）结构自检

在 `fnpack build` 之前跑一遍，避免打包到一半才发现缺文件 / JSON 非法 / 入口对不上。

用法:
    python3 check_fpk_package.py <app-dir> [--json]

检查项:
  1. fnpack 打包必需文件/目录是否存在
  2. manifest 必填字段与常见取值合法性
  3. config/privilege、config/resource 是否合法 JSON 且字段合理
  4. app/ui/config 是否合法 JSON，入口 ID 前缀与 desktop_applaunchname 是否一致
  5. 统一网关入口的 gatewayPrefix / gatewaySocket 规则
  6. 端口入口的 port 与 manifest.service_port 是否一致
  7. cmd/main 是否存在、可执行、退出码规范（status: 0 运行 / 3 未运行）
  8. 脚本里是否有硬编码 /var/apps 路径（应用 TRIM_* 环境变量）
  9. releases/ 的版本化 fpk 是否已提交 Git 留档（同步留档、双远端）
"""

import sys
import os
import re
import json
import subprocess
from pathlib import Path

errors, warnings, infos = [], [], []


def err(msg):
    errors.append(f"[ERROR] {msg}")


def warn(msg):
    warnings.append(f"[WARN ] {msg}")


def info(msg):
    infos.append(f"[INFO ] {msg}")


def _git(args, cwd):
    """在 cwd 跑 git 命令；非 git 仓库 / 没有 git 命令时返回 None。"""
    try:
        return subprocess.run(
            ["git"] + args, cwd=str(cwd),
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def parse_manifest(path: Path):
    """manifest 是 ini 风格的 key=value，没有扩展名。"""
    data = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def check_required_structure(app_dir: Path):
    must_files = ["manifest", "config/privilege", "config/resource", "ICON.PNG", "ICON_256.PNG"]
    must_dirs = ["app", "cmd", "wizard"]

    for rel in must_files:
        if not (app_dir / rel).exists():
            err(f"缺少必需文件: {rel}")
    for rel in must_dirs:
        if not (app_dir / rel).is_dir():
            err(f"缺少必需目录: {rel}/")


def check_manifest(app_dir: Path):
    mf = app_dir / "manifest"
    if not mf.exists():
        return None

    data = parse_manifest(mf)

    for field in ("appname", "version", "display_name", "source"):
        if not data.get(field):
            err(f"manifest 缺少必填字段: {field}")

    appname = data.get("appname", "")
    if appname and not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", appname):
        err(f"manifest.appname 含非法字符: {appname}（建议只使用字母数字、下划线、连字符）")

    if data.get("source") and data["source"] != "thirdparty":
        warn(f"manifest.source={data['source']}，第三方应用通常为 thirdparty")

    platform = data.get("platform", "")
    if platform and platform not in ("x86", "arm", "all"):
        err(f"manifest.platform 取值非法: {platform}（应为 x86 / arm / all）")
    if not platform:
        warn("manifest 未声明 platform，建议显式声明 x86 / arm / all")

    version = data.get("version", "")
    if version and not re.match(r"^\d+\.\d+\.\d+", version):
        warn(f"manifest.version 不像语义化版本: {version}")

    ctl_stop = data.get("ctl_stop", "")
    if ctl_stop and ctl_stop not in ("true", "false"):
        err(f"manifest.ctl_stop 应为 true / false，当前: {ctl_stop}")

    return data


def check_privilege(app_dir: Path):
    p = app_dir / "config" / "privilege"
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(f"config/privilege 不是合法 JSON: {e}")
        return

    run_as = (data.get("defaults") or {}).get("run-as", "")
    if not run_as:
        err("config/privilege 缺少 defaults.run-as")
    elif run_as == "root":
        warn(
            "config/privilege 使用 run-as=root。仅在生命周期脚本确有必要时使用，"
            "长期运行的对外服务请 runuser 降权到包用户"
        )
    elif run_as != "package":
        err(f"config/privilege.defaults.run-as 取值非法: {run_as}（应为 package / root）")

    if run_as == "package" and not data.get("username"):
        info("config/privilege 未指定 username，系统将按 manifest.appname 生成")

    if data.get("join-groups"):
        warn(f"声明了附加用户组 {data['join-groups']}，请确认每一项都是必需的")


def check_resource(app_dir: Path, manifest):
    p = app_dir / "config" / "resource"
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(f"config/resource 不是合法 JSON: {e}")
        return

    valid_scopes = {
        "trim.file.sharedAccess",
        "trim.file.userAccess",
        "trim.file.userAcl",
        "trim.file.path",
        "trim.system.getPlatformConfig",
    }
    scopes = data.get("api-scope", [])
    unknown = [s for s in scopes if s not in valid_scopes]
    if unknown:
        err(f"config/resource.api-scope 含未知 Scope: {unknown}")
    if len(scopes) >= 4:
        warn(f"api-scope 声明了 {len(scopes)} 项，请确认全部实际用到（Scope 应克制）")

    for sh in (data.get("data-share") or {}).get("shares", []):
        name = sh.get("name", "")
        if not name:
            err("data-share.shares 中存在缺少 name 的条目")
        elif name and "/" not in name:
            warn(f"共享目录 '{name}' 未使用应用名顶级目录，建议形如 myapp/data 以减少命名冲突")

    for pr in (data.get("docker-project") or {}).get("projects", []):
        rel = app_dir / "app" / pr.get("path", "")
        if pr.get("path") and not (rel / "docker-compose.yaml").exists():
            err(f"docker-project '{pr.get('name')}' 指向 {rel}，但找不到 docker-compose.yaml")


def check_ui_config(app_dir: Path, manifest):
    desktop_uidir = (manifest or {}).get("desktop_uidir", "ui")
    cfg_path = app_dir / "app" / desktop_uidir / "config"
    if not cfg_path.exists():
        if (manifest or {}).get("desktop_uidir"):
            err(f"manifest 声明 desktop_uidir={desktop_uidir}，但 {cfg_path} 不存在")
        else:
            info("未找到 app/ui/config（无桌面入口的应用可忽略）")
        return

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(f"app/{desktop_uidir}/config 不是合法 JSON: {e}")
        return

    entries = data.get(".url") or {}
    if not entries:
        err(f"app/{desktop_uidir}/config 中没有 .url 入口定义")
        return

    appname = (manifest or {}).get("appname", "")
    launch = (manifest or {}).get("desktop_applaunchname", "")
    service_port = (manifest or {}).get("service_port", "")

    if launch and launch not in entries:
        err(f"manifest.desktop_applaunchname='{launch}' 在入口配置中不存在")

    for eid, e in entries.items():
        if appname and not eid.startswith(appname):
            warn(f"入口 ID '{eid}' 未以 appname '{appname}' 作为前缀")
        if not e.get("title"):
            err(f"入口 '{eid}' 缺少 title")
        if not e.get("icon"):
            err(f"入口 '{eid}' 缺少 icon")

        is_gateway = bool(e.get("gatewayPrefix"))
        is_cgi = "index.cgi" in (e.get("url") or "")

        if is_gateway:
            prefix = e["gatewayPrefix"]
            if not prefix.startswith("/app/"):
                err(f"入口 '{eid}' 的 gatewayPrefix 应以 /app/ 开头: {prefix}")
            if "." in prefix.rsplit("/", 1)[-1]:
                warn(f"入口 '{eid}' 的 gatewayPrefix 含点号，公开路径建议避免: {prefix}")
            if not e.get("gatewaySocket"):
                err(f"入口 '{eid}' 声明了 gatewayPrefix 但缺少 gatewaySocket")
            elif "/" in e["gatewaySocket"]:
                err(f"入口 '{eid}' 的 gatewaySocket 只应填文件名，不应含路径: {e['gatewaySocket']}")
            if e.get("protocol") or e.get("port"):
                warn(f"入口 '{eid}' 是统一网关入口，protocol/port 会被忽略")
        elif is_cgi:
            if e.get("protocol") or e.get("port"):
                warn(f"入口 '{eid}' 是 CGI 入口，protocol/port 不参与路由")
            cgi_file = app_dir / "app" / desktop_uidir / "index.cgi"
            if not cgi_file.exists():
                err(f"入口 '{eid}' 使用 index.cgi，但 app/{desktop_uidir}/index.cgi 不存在")
        else:
            port = str(e.get("port", ""))
            if service_port and port and port != service_port:
                err(
                    f"入口 '{eid}' 的 port={port} 与 manifest.service_port={service_port} 不一致"
                )
            if not port and not (e.get("protocol") == ""):
                warn(f"入口 '{eid}' 看起来是端口服务入口，但未声明 port")

        if e.get("allUsers") is False and not (e.get("control") or {}).get("accessPerm"):
            info(f"入口 '{eid}' 仅管理员可见，建议同时配置 control.accessPerm=readonly")


def check_release_no_reuse(app_dir: Path, manifest):
    """版本化归档冲突检查：禁止复用/覆盖已有 fpk 安装包。

    build-fpk.js 每次构建会自动递增 manifest.version，因此正常情况下
    releases/ 里不会再次出现同一版本。若当前 manifest.version 已经存在于
    releases/（例如手工改回旧版本号、或没走 build-fpk.js），这里给出警告，
    提醒先递增版本号再打包，避免覆盖/复用历史包。
    """
    if not manifest:
        return
    version = manifest.get("version", "")
    appname = manifest.get("appname", "")
    if not version or not appname:
        return

    releases_dir = app_dir.parent / "releases"
    if not releases_dir.is_dir():
        return

    existing = [
        f.name for f in releases_dir.glob(f"{appname}_{version}_*.fpk")
    ]
    if existing:
        warn(
            f"releases/ 已存在版本 {version} 的包（{existing[0]} 等）。"
            f"每次打包应通过 build-fpk.js 自动递增版本号，禁止复用/覆盖已有 fpk 安装包；"
            f"若确实需要该版本，请先递增 manifest.version 再构建。"
        )

    # 版本号与 Git tag 强绑定：v<version> 已存在 = 该版本发过，同样禁止复用
    r = _git(["tag", "--list", f"v{version}"], app_dir.parent)
    if r is not None and r.returncode == 0 and r.stdout.strip():
        warn(
            f"Git 已存在 tag v{version}——版本号与 tag 强绑定，该版本已发版过，禁止复用。"
            "请用 build-fpk.js 递增版本（--bump minor/major 或 --set-version X.Y.Z）后再构建。"
        )


def check_release_git_archival(app_dir: Path):
    """版本化 fpk 同步留档检查：releases/ 里的版本化包与构建记录必须进 Git。

    规则：版本化 fpk「盘上不覆盖、git 里也留档」——.gitignore 虽然用 *.fpk
    挡掉全部构建产物，但必须用 !releases/ + !releases/**/*.fpk +
    !releases/build-log.json 放行 releases/ 下的版本化产物。这里检查两件事：
      1) .gitignore 是否误把 releases/ 的版本化包挡在库外（check-ignore）；
      2) releases/ 是否有未提交留档的版本化 fpk / build-log.json（status）。
    均为警告；非 git 仓库或没有 git 命令时自动跳过。
    """
    releases_dir = app_dir.parent / "releases"
    if not releases_dir.is_dir():
        return

    fpk_files = sorted(releases_dir.glob("*.fpk"))
    log_file = releases_dir / "build-log.json"
    if not fpk_files and not log_file.exists():
        return

    repo_root = app_dir.parent

    def git(args):
        return _git(args, repo_root)

    # 1) .gitignore 必须放行 releases/ 下的版本化产物
    probes = [f"releases/{p.name}" for p in fpk_files[:1]]
    if log_file.exists():
        probes.append("releases/build-log.json")
    ignored = []
    for probe in probes:
        r = git(["check-ignore", probe])
        if r is not None and r.returncode == 0:
            ignored.append(probe)
    if ignored:
        warn(
            f".gitignore 把版本化产物挡在库外了（{', '.join(ignored)}）。"
            "版本化 fpk 必须「盘上不覆盖、git 里也留档」：请在 .gitignore 加 "
            "!releases/ + !releases/**/*.fpk + !releases/build-log.json 放行 releases/。"
        )
        return

    # 2) 未提交留档提醒（ignored 文件不会出现在 status 里，能列出来就是漏提交）
    r = git(["status", "--porcelain", "--", "releases"])
    if r is not None and r.returncode == 0:
        pending = [ln for ln in r.stdout.splitlines() if ln.strip()]
        if pending:
            warn(
                f"releases/ 有 {len(pending)} 项未提交留档的版本化 fpk / build-log.json。"
                "版本化安装包必须随发版 commit 提交并推送双远端："
                "git add releases/ && git commit -m \"v<x.y.z>: ...\" "
                "&& git push origin main && git push mirror main"
            )


def check_cmd_scripts(app_dir: Path, manifest):
    main = app_dir / "cmd" / "main"
    if not main.exists():
        err("缺少 cmd/main（应用运行控制脚本）")
        return

    if not os.access(main, os.X_OK):
        warn("cmd/main 没有可执行权限（fnpack 通常会处理，手动部署时需 chmod +x）")

    text = main.read_text(encoding="utf-8", errors="ignore")

    if 'status)' not in text:
        err("cmd/main 未处理 status 命令")
    if "exit 3" not in text:
        warn("cmd/main 的 status 分支未返回 3（未运行），应用中心可能一直显示运行中")

    if (manifest or {}).get("ctl_stop") == "true" and "start)" not in text:
        err("manifest.ctl_stop=true 但 cmd/main 未处理 start 命令")

    # 硬编码路径检查
    hardcoded = re.findall(r"/var/apps/[A-Za-z0-9_-]+", text)
    hardcoded = [h for h in hardcoded if h != "/var/apps/nodejs_v22"]
    if hardcoded:
        warn(
            f"cmd/main 硬编码了应用路径 {sorted(set(hardcoded))}，"
            "应使用 TRIM_APPDEST / TRIM_PKGVAR / TRIM_PKGETC 等环境变量"
        )

    for script in ("install_init", "install_callback", "upgrade_init", "upgrade_callback",
                   "uninstall_init", "uninstall_callback", "config_init", "config_callback"):
        if (app_dir / "cmd" / script).exists() and not os.access(app_dir / "cmd" / script, os.X_OK):
            warn(f"cmd/{script} 没有可执行权限")


def check_hardcoded_paths(app_dir: Path):
    """扫描 cmd/ 与 app/ui/ 下脚本里的硬编码路径。"""
    targets = []
    cmd_dir = app_dir / "cmd"
    if cmd_dir.is_dir():
        targets += list(cmd_dir.glob("*"))
    for uidir in ("ui",):
        cgi = app_dir / "app" / uidir / "index.cgi"
        if cgi.exists():
            targets.append(cgi)

    for f in targets:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in re.findall(r"/var/apps/([A-Za-z0-9_-]+)", text):
            if m.startswith("nodejs") or m.startswith("python") or m.startswith("java"):
                continue
            warn(f"{f.name} 硬编码 /var/apps/{m}，建议改用 TRIM_* 环境变量")


def check_cgi_security(app_dir: Path, manifest):
    desktop_uidir = (manifest or {}).get("desktop_uidir", "ui")
    cgi = app_dir / "app" / desktop_uidir / "index.cgi"
    if not cgi.exists():
        return
    text = cgi.read_text(encoding="utf-8", errors="ignore")

    if "\\.\\." not in text and ".." not in text:
        err("index.cgi 未做目录穿越（..）防护，静态文件服务必须拒绝含 .. 的路径")
    if "Content-Type" not in text:
        warn("index.cgi 未输出 Content-Type 响应头")
    if "404" not in text:
        warn("index.cgi 未处理文件不存在的 404 分支")
    if re.search(r"\$\{?REQUEST_URI\}?.*`", text) or "eval " in text:
        err("index.cgi 疑似把请求路径拼进 shell 执行，这是高危写法，必须禁止")


def main():
    if len(sys.argv) < 2:
        print("用法: python3 check_fpk_package.py <app-dir> [--json]")
        sys.exit(2)

    app_dir = Path(sys.argv[1]).resolve()
    as_json = "--json" in sys.argv

    if not app_dir.is_dir():
        print(f"目录不存在: {app_dir}")
        sys.exit(2)

    check_required_structure(app_dir)
    manifest = check_manifest(app_dir)
    check_release_no_reuse(app_dir, manifest)
    check_release_git_archival(app_dir)
    check_privilege(app_dir)
    check_resource(app_dir, manifest)
    check_ui_config(app_dir, manifest)
    check_cmd_scripts(app_dir, manifest)
    check_hardcoded_paths(app_dir)
    check_cgi_security(app_dir, manifest)

    if as_json:
        print(json.dumps({"errors": errors, "warnings": warnings, "infos": infos},
                         ensure_ascii=False, indent=2))
        sys.exit(1 if errors else 0)

    print(f"🔍 检查应用包: {app_dir}\n")
    for line in infos:
        print(line)
    for line in warnings:
        print(line)
    for line in errors:
        print(line)

    print()
    if errors:
        print(f"❌ {len(errors)} 个错误，{len(warnings)} 个警告 —— 修复错误后再 fnpack build")
        sys.exit(1)
    if warnings:
        print(f"✅ 无阻塞错误，{len(warnings)} 个警告需要确认")
        sys.exit(0)
    print("✅ 应用包结构检查通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
