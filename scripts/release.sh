#!/usr/bin/env bash
# Sestaví Docker obraz VidDown pro Synology (amd64) i ARM (arm64) a pošle ho do GitHub Container Registry.
# Bez GitHub Actions: spouští se ručně na tomto počítači.
#
#   scripts/release.sh            # sestaví a nahraje :<verze> a :latest
#   scripts/release.sh --dry-run  # jen sestaví (bez nahrání), vypíše co by udělal
#
# Jednorázově: docker login ghcr.io -u <GitHub uživatel>   (heslo = osobní token se scope write:packages)
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${VIDDOWN_IMAGE:-ghcr.io/iamjk78/viddown}"
PLATFORMS="${VIDDOWN_PLATFORMS:-linux/amd64,linux/arm64}"
VERSION="$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('src/viddown/__init__.py').read()).group(1))")"
REV="$(git rev-parse --short HEAD)"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

if [ -n "$(git status --porcelain)" ]; then
  echo "V repozitáři jsou necommitované změny – obraz by neodpovídal žádnému commitu. Nejdřív commitněte." >&2
  exit 1
fi
if [ "$DRY" = 0 ] && git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null && \
   [ "$(git rev-list -n1 "v$VERSION")" != "$(git rev-parse HEAD)" ]; then
  echo "Značka v$VERSION už existuje na jiném commitu. Zvyšte verzi v src/viddown/__init__.py." >&2
  exit 1
fi

echo "Obraz:      $IMAGE:$VERSION (+ :latest)"
echo "Platformy:  $PLATFORMS"
echo "Commit:     $REV"

docker buildx inspect viddown-builder >/dev/null 2>&1 || docker buildx create --name viddown-builder --driver docker-container >/dev/null
ARGS=(--builder viddown-builder --platform "$PLATFORMS" -t "$IMAGE:$VERSION" -t "$IMAGE:latest"
      --label "org.opencontainers.image.version=$VERSION" --label "org.opencontainers.image.revision=$REV"
      --label "org.opencontainers.image.source=https://github.com/iamjk78/VidDown")
if [ "$DRY" = 1 ]; then
  docker buildx build "${ARGS[@]}" .
  echo "Hotovo (zkušební sestavení, nic nenahráno)."
else
  docker buildx build "${ARGS[@]}" --push .
  git tag -f "v$VERSION" >/dev/null
  echo "Nahráno. Na Synology: docker compose pull && docker compose up -d"
  echo "Značku v$VERSION odešlete příkazem: git push origin v$VERSION"
fi
