#!/usr/bin/env bash
# 把 NAS 上构建好的 OCI tar 推到 Docker Hub（**不依赖本机 docker daemon**）。
#
# 什么时候用这个脚本（而不是 build-image.sh --push）：
#   本机 Docker Desktop 的 Linux 引擎依赖 wsl.exe，若 wsl.exe 被安全策略禁止，
#   daemon 就起不来，docker load / docker push 都用不了。
#   此时本脚本直接走 Registry HTTP API 推送（见 tools/push-oci-tar.py）。
#
# 用法：
#   bash tools/push-oci-tar.sh <版本号>
#   例：bash tools/push-oci-tar.sh 1.0.39
#
# 前置条件：
#   1) 本机有可用代理（默认 http://127.0.0.1:7897，可用 PUSH_PROXY 覆盖）
#   2) NAS 上已构建好 /vol2/omnioffice-build/kwink-kwinkoffice-<版本>.oci.tar
set -euo pipefail

VER="${1:?用法: bash tools/push-oci-tar.sh <版本号>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAS="${NAS_HOST:-192.168.31.204}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_fn_nas}"
REMOTE_TAR="/vol2/omnioffice-build/kwink-kwinkoffice-${VER}.oci.tar"
LOCAL_DIR="${TMPDIR:-/tmp}/omnioffice-image-build"
PY="${PY:-$ROOT/.tools/python/python.exe}"

echo "==> 下载 $REMOTE_TAR"
mkdir -p "$LOCAL_DIR"
scp -i "$SSH_KEY" -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
    "root@${NAS}:${REMOTE_TAR}" "$LOCAL_DIR/"

WIN_TAR="$(cygpath -w "$LOCAL_DIR/kwink-kwinkoffice-${VER}.oci.tar")"

# 凭据由 python 脚本**在进程内**从 Docker 凭据助手读取，不写任何临时文件。
# （早前版本写临时 JSON 文件，结果 rm 被安全策略拦截，凭据残留在磁盘上 —— 已废弃。）

echo "==> 直推 Docker Hub（走 Registry API，不经 docker daemon）"
PUSH_TAG="$VER" PUSH_PROXY="${PUSH_PROXY:-http://127.0.0.1:7897}" \
    "$PY" "$ROOT/tools/push-oci-tar.py" "$WIN_TAR"

echo "==> 回远端核对平台列表"
TOKEN=$(curl -s --max-time 20 \
    "https://auth.docker.io/token?service=registry.docker.io&scope=repository:kwink/kwinkoffice:pull" \
    | "$PY" -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -sL --max-time 30 -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.oci.image.index.v1+json" \
    "https://registry-1.docker.io/v2/kwink/kwinkoffice/manifests/${VER}" \
    | "$PY" -c "
import sys,json
d=json.load(sys.stdin)
mt=d.get('mediaType','')
print('mediaType:',mt)
if 'index' in mt or 'list' in mt:
    for p in d.get('manifests',[]):
        pl=p.get('platform',{}); print('  platform:',pl.get('os'),pl.get('architecture'))
else:
    print('  单架构 | config:',d['config']['digest'][:26],'| 层数:',len(d['layers']))
"
