"""把 OCI tar 直接推到 Docker Hub（不依赖 docker daemon）。

为什么需要它：本机 Docker Desktop 的 Linux 引擎依赖 wsl.exe，而 wsl.exe 被
安全策略禁止启动 → daemon 起不来；NAS 上直连 registry-1.docker.io 会被
connection reset。于是改用最底层的 Registry HTTP API 手动推送：

  1. 取 token：auth.docker.io/token?scope=repository:<repo>:push,pull
  2. 逐个上传 blob：POST /v2/<repo>/blobs/uploads/ 拿 Location
                   → PUT <Location>&digest=sha256:<hash> 带内容
  3. 上传 manifest：PUT /v2/<repo>/manifests/<tag>

内容与 `docker push` 完全等价（同一份 OCI manifest + 同一批层）。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request

REPO = os.environ.get("PUSH_REPO", "kwink/kwinkoffice")
TAG = os.environ.get("PUSH_TAG", "1.0.39")
PROXY = os.environ.get("PUSH_PROXY", "http://127.0.0.1:7897")
AUTH = "https://auth.docker.io"
REG = "https://registry-1.docker.io"

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
)


def api(method: str, url: str, data=None, headers=None, expect=(200, 201, 202, 204)):
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=300) as resp:
            body = resp.read()
            if resp.status not in expect:
                raise RuntimeError(f"{method} {url} -> {resp.status}: {body[:300]!r}")
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url} -> {e.code}: {e.read()[:400]!r}") from None


def get_token() -> str:
    """取一个带 push 权限的 registry token。

    匿名 token 只有 **pull** 权限（实测：access.actions == ["pull"]），
    POST /blobs/uploads/ 会 401。所以必须带 Docker Hub 账号认证。

    凭据来源：直接调用 Docker 的凭据助手（`docker-credential-desktop get`）
    读取 Docker Desktop credsStore，**在进程内解析，不写任何临时文件**
    （写文件有被安全策略拦截 rm 的风险，凭据会残留在磁盘上）。

    可用环境变量覆盖：
      DOCKER_CRED_HELPER — 凭据助手可执行文件路径
      DOCKER_USERNAME / DOCKER_PASSWORD — 直接给账号密码（PAT）
    """
    q = urllib.parse.urlencode(
        {
            "service": "registry.docker.io",
            "scope": f"repository:{REPO}:push,pull",
        }
    )

    user = os.environ.get("DOCKER_USERNAME", "").strip()
    secret = os.environ.get("DOCKER_PASSWORD", "").strip()

    if not (user and secret):
        user, secret = _read_cred_helper()
    if not (user and secret):
        raise RuntimeError(
            "取不到 Docker Hub 凭据：既没有 DOCKER_USERNAME/DOCKER_PASSWORD，"
            "也读不到凭据助手。请先 docker login。"
        )

    basic = base64.b64encode(f"{user}:{secret}".encode()).decode()
    _, body, _ = api(
        "GET",
        f"{AUTH}/token?{q}",
        headers={"Authorization": f"Basic {basic}"},
    )
    tok = json.loads(body)["token"]
    print(f"账号 {user} 认证成功")
    return tok


def _read_cred_helper() -> tuple[str, str]:
    """调用 docker-credential-desktop（或 docker-credential-pass）取凭据。

    只在内存里解析，返回 (username, secret)；**不落盘**。
    """
    candidates = [
        os.environ.get("DOCKER_CRED_HELPER", "").strip(),
        r"C:\Users\kwink\AppData\Local\Programs\DockerDesktop\resources\bin\docker-credential-desktop.exe",
        "docker-credential-desktop.exe",
        "docker-credential-desktop",
    ]
    for path in candidates:
        if not path:
            continue
        exe = path if os.path.isfile(path) else shutil.which(path)
        if not exe:
            continue
        try:
            proc = subprocess.run(
                [exe, "get"],
                input="https://index.docker.io/v1/\n",
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                continue
            cred = json.loads(proc.stdout)
        except Exception as e:  # noqa: BLE001 —— 换下一个候选
            print(f"  凭据助手 {path} 读取失败：{e}")
            continue
        u = cred.get("Username") or ""
        s = cred.get("Secret") or ""
        if u and s:
            return u, s
    return "", ""


def blob_path(digest: str) -> str:
    return "blobs/sha256/" + digest.split(":", 1)[1]


def upload_blob(tar: tarfile.TarFile, digest: str, size: int, token: str) -> bool:
    """上传单个 blob；已存在（HEAD 200）则跳过。"""
    url = f"{REG}/v2/{REPO}/blobs/{digest}"
    try:
        opener.open(urllib.request.Request(url, method="HEAD", headers={"Authorization": f"Bearer {token}"}), timeout=60)
        print(f"  ✓ 已存在 {digest[:19]}")
        return False
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise RuntimeError(f"HEAD {url} -> {e.code}") from None

    _, _, headers = api(
        "POST",
        f"{REG}/v2/{REPO}/blobs/uploads/",
        headers={"Authorization": f"Bearer {token}"},
        expect=(202,),
    )
    location = headers.get("Location") or headers.get("location")
    if not location:
        raise RuntimeError("未拿到上传 Location")
    if location.startswith("/"):
        location = REG + location

    src = tar.extractfile(blob_path(digest))
    if src is None:
        raise RuntimeError(f"tar 内缺少 {blob_path(digest)}")
    data = src.read()
    sep = "&" if "?" in location else "?"
    api(
        "PUT",
        f"{location}{sep}digest={urllib.parse.quote(digest, safe='')}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
        },
        expect=(201,),
    )
    print(f"  ↑ 已上传 {digest[:19]}  {size / 1024 / 1024:.1f} MB")
    return True


def main() -> int:
    tar_path = sys.argv[1]
    token = get_token()
    print("token 获取成功")
    tar = tarfile.open(tar_path)

    idx = json.loads(tar.extractfile("index.json").read())
    desc = idx["manifests"][0]
    manifest_digest = desc["digest"]
    manifest_bytes = tar.extractfile(blob_path(manifest_digest)).read()
    manifest = json.loads(manifest_bytes)
    print(f"manifest {manifest_digest[:19]}  mediaType={manifest.get('mediaType')}")

    targets = [(manifest["config"]["digest"], manifest["config"]["size"])]
    for layer in manifest["layers"]:
        targets.append((layer["digest"], layer["size"]))

    print(f"需上传 {len(targets)} 个 blob")
    for digest, size in targets:
        upload_blob(tar, digest, size, token)

    status, _, _ = api(
        "PUT",
        f"{REG}/v2/{REPO}/manifests/{TAG}",
        data=manifest_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": manifest.get(
                "mediaType", "application/vnd.oci.image.manifest.v1+json"
            ),
        },
        expect=(201, 200),
    )
    print(f"manifest 已上传（HTTP {status}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
