#!/usr/bin/env bash
# Vydání VidDown: (1) archiv kódu aplikace + manifest pro aktualizace zevnitř, (2) Docker obraz pro Synology (amd64)
# i ARM (arm64) do GitHub Container Registry, (3) GitHub Release s archivem a manifestem.
# Bez GitHub Actions: spouští se ručně na tomto počítači.
#
# Postup vydání: zvyšte verzi v src/viddown/__init__.py, commitněte, pushněte (a až potom spusťte tento skript).
#
#   scripts/release.sh            # archiv + obraz (:<verze>, :latest) + GitHub Release v<verze>
#   scripts/release.sh --dry-run  # sestaví archiv i obraz, nic nenahraje a nevytvoří vydání
#   scripts/release.sh --app-only # jen archiv a manifest do dist/release/ (rychlé, bez Dockeru; pro zkoušky)
#
# Jednorázově: docker login ghcr.io -u <GitHub uživatel>   (heslo = osobní token se scope write:packages)
#              gh auth login                              (GitHub CLI, kvůli vytvoření vydání)
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${VIDDOWN_IMAGE:-ghcr.io/iamjk78/viddown}"
PLATFORMS="${VIDDOWN_PLATFORMS:-linux/amd64,linux/arm64}"
PY="${VIDDOWN_PYTHON:-.venv/bin/python}"
VERSION="$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('src/viddown/__init__.py').read()).group(1))")"
REV="$(git rev-parse --short HEAD)"
DRY=0; APP_ONLY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  --app-only) APP_ONLY=1 ;;
  "") ;;
  *) echo "Neznámý přepínač: $1" >&2; exit 2 ;;
esac

if [ -n "$(git status --porcelain)" ]; then
  echo "V repozitáři jsou necommitované změny – vydání by neodpovídalo žádnému commitu. Nejdřív commitněte." >&2
  exit 1
fi
PREV="$(git describe --tags --abbrev=0 --match 'v*' HEAD 2>/dev/null || true)"

if [ "$DRY" = 0 ] && [ "$APP_ONLY" = 0 ]; then
  # Co se musí splnit dřív, než se začne dlouhé sestavování a nahrávání.
  if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null && \
     [ "$(git rev-list -n1 "v$VERSION")" != "$(git rev-parse HEAD)" ]; then
    echo "Značka v$VERSION už existuje na jiném commitu. Zvyšte verzi v src/viddown/__init__.py." >&2
    exit 1
  fi
  if ! command -v gh >/dev/null || ! gh auth status >/dev/null 2>&1; then
    echo "Chybí přihlášené GitHub CLI (gh auth login), bez něj nejde vytvořit vydání." >&2
    exit 1
  fi
  if ! git fetch -q origin 2>/dev/null || ! git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "Commit $REV není na GitHubu (origin/main). Nejdřív proveďte push." >&2
    exit 1
  fi
  if gh release view "v$VERSION" >/dev/null 2>&1; then
    echo "Vydání v$VERSION na GitHubu už existuje. Zvyšte verzi v src/viddown/__init__.py." >&2
    exit 1
  fi
fi

# Změnily se závislosti nebo Dockerfile? Pak je potřeba zvýšit IMAGE_API (src/viddown/bootstrap.py), jinak by se
# vydání nainstalovalo do obrazu, který ho neunese.
if [ -n "$PREV" ] && [ -n "$(git diff --name-only "$PREV"..HEAD -- pyproject.toml Dockerfile docker/)" ] && \
   [ -z "$(git diff "$PREV"..HEAD -- src/viddown/bootstrap.py | grep '^[+-]IMAGE_API' || true)" ]; then
  echo "POZOR: od $PREV se změnil pyproject.toml/Dockerfile, ale IMAGE_API v src/viddown/bootstrap.py zůstalo stejné." >&2
  echo "       Pokud přibyly nebo se změnily závislosti, zvyšte IMAGE_API (jinak se vydání nainstaluje do starého obrazu)." >&2
fi

echo "Verze:      $VERSION"
echo "Commit:     $REV"

# 1) archiv kódu aplikace a manifest (sha256, schéma databáze, požadované IMAGE_API) – pro aktualizace zevnitř
OUT="dist/release"
rm -rf "$OUT" && mkdir -p "$OUT"
"$PY" -m viddown.cli app pack "$OUT/viddown-$VERSION.zip" --commit "$REV" --json "$OUT/manifest.json"
if [ "$APP_ONLY" = 1 ]; then
  echo "Hotovo (jen archiv a manifest v $OUT/, nic nenahráno)."
  exit 0
fi

# 2) Docker obraz
echo "Obraz:      $IMAGE:$VERSION (+ :latest)"
echo "Platformy:  $PLATFORMS"
docker buildx inspect viddown-builder >/dev/null 2>&1 || docker buildx create --name viddown-builder --driver docker-container >/dev/null
ARGS=(--builder viddown-builder --platform "$PLATFORMS" -t "$IMAGE:$VERSION" -t "$IMAGE:latest"
      --label "org.opencontainers.image.version=$VERSION" --label "org.opencontainers.image.revision=$REV"
      --label "org.opencontainers.image.source=https://github.com/iamjk78/VidDown")
if [ "$DRY" = 1 ]; then
  docker buildx build "${ARGS[@]}" .
  echo "Hotovo (zkušební sestavení, nic nenahráno ani nevytvořeno)."
  exit 0
fi
docker buildx build "${ARGS[@]}" --push .

# 3) GitHub Release (vytvoří i značku v<verze> na odeslaném commitu)
if [ -n "$PREV" ]; then NOTES="$(git log --pretty='- %s' "$PREV"..HEAD)"; else NOTES="$(git log --pretty='- %s' -n 20)"; fi
gh release create "v$VERSION" "$OUT/viddown-$VERSION.zip" "$OUT/manifest.json" \
  --target "$(git rev-parse HEAD)" --title "VidDown $VERSION" --notes "$NOTES"
git fetch -q --tags origin || true
echo "Vydáno. Aplikace si novou verzi najde sama (viddown app check / update); obraz na Synology:"
echo "  docker compose pull && docker compose up -d"
