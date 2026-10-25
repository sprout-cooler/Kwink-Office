# Build the omnioffice Docker image and push it to Docker Hub.
#
# WHY THIS EXISTS
#   fnOS installs .fpk by running `docker compose up -d`. Before v1.0.28 the
#   compose file only had a `build:` section, so fnOS rebuilt the image from
#   scratch on every install/upgrade. A cold build takes ~9m15s (the apt step
#   that installs LibreOffice alone costs ~345s), which overruns fnOS' ~12.5min
#   upgrade budget -> the installer sits at 80% and then dies with
#   "failed to upgrade ... error=10266". v1.0.28 ships a prebuilt, versioned
#   image on Docker Hub and points compose at it, so the NAS only pulls
#   (measured: 2m44s).
#
# USAGE
#   bash tools/build-image.sh                 # build only (no push)
#   bash tools/build-image.sh --push          # build + push to Docker Hub
#   bash tools/build-image.sh --push --tag 1.0.28
#
# ORDER OF OPERATIONS (run packaging FIRST)
#   1) powershell -ExecutionPolicy Bypass -File tools\package-fpk.ps1
#      -> bumps omnioffice/manifest to the new version AND rewrites the
#         compose (APP_VERSION fallback + image tag) to the same version
#   2) bash tools/build-image.sh --push
#      -> builds that exact version and pushes it to Docker Hub
#   3) install the .fpk -> the NAS pulls the prebuilt image
#   The tag always comes from the manifest, so the image and the fpk can
#   never drift apart.
#
# PIPELINE (same shape as the verified KwinkGuide flow)
#   1. NAS builds the image (the NAS has registry mirrors configured in
#      /etc/docker/daemon.json, so `docker pull` of the base image works there).
#   2. Export to an OCI tar on the NAS, download it.
#   3. Locally: `docker load` + `docker push`.
#      `docker buildx --push` does NOT work here: the last step fails with
#      "failed to authorize: failed to fetch oauth token: Bad Gateway".
#
# PREREQS
#   · ssh access to the NAS (see NAS_HOST / NAS_SSH_KEY below)
#   · a local proxy that can reach registry-1.docker.io.
#     The registry endpoint is SNI-blocked on direct connections in CN networks
#     (measured: curl to registry-1.docker.io times out with HTTP=000).
#     Clash Verge exposes a mixed port (7897 by default) -- export HTTP_PROXY
#     and HTTPS_PROXY before running this script, or set PUSH_PROXY.
#   · `docker login` already done (docker login -u <user>)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="${OO_IMAGE:-kwink/omnioffice}"
NAS_HOST="${NAS_HOST:-192.168.31.204}"
NAS_SSH_KEY="${NAS_SSH_KEY:-$HOME/.ssh/id_ed25519_fn_nas}"
NAS_WORKDIR="${NAS_WORKDIR:-/vol2/omnioffice-build}"
# Local scratch dir for the downloaded OCI tar.
LOCAL_DIR="${LOCAL_DIR:-$ROOT/.tmp-image}"
# Proxy used only for the local push step (docker CLI reads HTTP_PROXY).
PUSH_PROXY="${PUSH_PROXY:-${HTTPS_PROXY:-${HTTP_PROXY:-}}}"

PUSH=0
TAG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --push) PUSH=1 ;;
    --tag) TAG="${2:-}"; shift ;;
    --image) IMAGE="${2:-}"; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
  shift
done

# ---- version tag: single source of truth = omnioffice/manifest ----
if [ -z "$TAG" ]; then
  TAG="$(sed -n 's/^version=//p' omnioffice/manifest | tr -d '[:space:]')"
fi
if ! [[ "$TAG" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: tag '$TAG' is not x.y.z (source: omnioffice/manifest)" >&2
  exit 1
fi

# The compose file must point at the very same version, otherwise the NAS
# pulls an older image than the one this fpk carries.
#
# ORDER OF OPERATIONS (important):
#   1. package-fpk.ps1  -> bumps manifest to 1.0.28 AND rewrites the compose
#                          (APP_VERSION fallback + image tag) to 1.0.28
#   2. build-image.sh   -> reads the bumped manifest, builds + pushes 1.0.28
#   3. install the fpk  -> the NAS pulls kwink/omnioffice:1.0.28
# So the tag always comes from the manifest AFTER packaging. When --tag is
# given explicitly it must match what packaging produced.
COMPOSE="$ROOT/omnioffice/app/docker/docker-compose.yaml"
COMPOSE_TAG="$(sed -n 's/.*image: kwink\/omnioffice:\${APP_VERSION:-\([0-9.]*\)}.*/\1/p' "$COMPOSE" | head -n1)"
if [ "$COMPOSE_TAG" != "$TAG" ]; then
  echo "ERROR: compose image tag ($COMPOSE_TAG) != tag ($TAG)." >&2
  echo "       Run package-fpk.ps1 FIRST (it bumps manifest and syncs the" >&2
  echo "       compose), then run this script to build that exact version." >&2
  exit 1
fi

echo "==> image: $IMAGE:$TAG"

# ---- build context ----
# The Docker build context is omnioffice/app (Dockerfile.api does
# `COPY server/ /srv/`, and the built frontend bundle lives in
# server/public). node_modules / __pycache__ / web/dist are excluded.
echo "==> staging build context"
rm -rf "$LOCAL_DIR/context"
mkdir -p "$LOCAL_DIR/context"
( cd omnioffice/app && tar -cf - \
    --exclude='web/node_modules' --exclude='web/dist' \
    --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='server/data' \
    server docker .dockerignore ) | ( cd "$LOCAL_DIR/context" && tar -xf - )

if [ ! -f "$LOCAL_DIR/context/server/public/index.html" ]; then
  echo "ERROR: server/public/index.html missing -- run the web build first." >&2
  exit 1
fi

( cd "$LOCAL_DIR" && tar -cf context.tar context )

# ---- upload to the NAS ----
echo "==> uploading context to $NAS_HOST"
ssh -i "$NAS_SSH_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=no "root@$NAS_HOST" \
  "mkdir -p '$NAS_WORKDIR'" </dev/null
scp -i "$NAS_SSH_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=no \
  "$LOCAL_DIR/context.tar" "root@$NAS_HOST:$NAS_WORKDIR/context.tar" </dev/null

# ---- build on the NAS (it has the registry mirrors) ----
# The builder "kgtest" was created with buildkitd.toml pointing at
# docker.fnnas.com / docker.1ms.run, so the base image pulls fine there.
# linux/amd64 only: fnOS hosts are x86 and LibreOffice is installed in the
# image at build time, so cross-building arm64 would need QEMU emulation.
echo "==> building on NAS (linux/amd64)"
ssh -i "$NAS_SSH_KEY" -o ConnectTimeout=20 -o StrictHostKeyChecking=no "root@$NAS_HOST" \
  "cd '$NAS_WORKDIR' && rm -rf context && tar -xf context.tar && cd context && \
   docker buildx build --builder kgtest --platform linux/amd64 \
     -f docker/Dockerfile.api -t '$IMAGE:$TAG' \
     --output type=oci,dest='$NAS_WORKDIR/$IMAGE-$TAG.oci.tar' ." </dev/null

# ---- download the OCI tar ----
echo "==> downloading OCI tar"
scp -i "$NAS_SSH_KEY" -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
  "root@$NAS_HOST:$NAS_WORKDIR/$IMAGE-$TAG.oci.tar" "$LOCAL_DIR/" </dev/null

# ---- load + push locally ----
echo "==> docker load"
docker load -i "$LOCAL_DIR/$IMAGE-$TAG.oci.tar"

if [ "$PUSH" != "1" ]; then
  echo "==> built (not pushed): $IMAGE:$TAG"
  exit 0
fi

if [ -z "$PUSH_PROXY" ]; then
  echo "ERROR: no proxy for the push step. registry-1.docker.io is SNI-blocked" >&2
  echo "       on direct connections. Set PUSH_PROXY (e.g. http://127.0.0.1:7897)" >&2
  echo "       or export HTTP_PROXY/HTTPS_PROXY first." >&2
  exit 1
fi
export HTTP_PROXY="$PUSH_PROXY" HTTPS_PROXY="$PUSH_PROXY"

echo "==> checking the remote tag is free (never overwrite a released version)"
if docker manifest inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
  echo "ERROR: $IMAGE:$TAG already exists on the registry. Bump the version instead." >&2
  exit 1
fi

echo "==> pushing $IMAGE:$TAG"
docker push "$IMAGE:$TAG"

echo "==> done: $IMAGE:$TAG"
echo "    pull:  docker pull $IMAGE:$TAG"
