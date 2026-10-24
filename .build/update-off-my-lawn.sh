#!/usr/bin/env sh
# Rebuild the Off My Lawn game from its repository and copy it into PyOS.
#
#   sh .build/update-off-my-lawn.sh            # latest main
#   sh .build/update-off-my-lawn.sh v1.2.0     # a tag, branch or commit
#
# Needs git and Node 20+. The game is served from src/frontend/games/off-my-lawn/.
set -eu

REF="${1:-main}"
REPO="https://github.com/elijahthinks/off-my-lawn.git"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/src/frontend/games/off-my-lawn"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --quiet "$REPO" "$WORK/game"
git -C "$WORK/game" checkout --quiet "$REF"
COMMIT="$(git -C "$WORK/game" rev-parse HEAD)"

(cd "$WORK/game" && npm ci --no-audit --no-fund && npm run build)

rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$WORK/game/dist/." "$DEST/"
find "$DEST" -name "*.map" -delete
cp "$WORK/game/LICENSE" "$DEST/LICENSE"
printf '%s\n' "Built from $REPO at $COMMIT" > "$DEST/SOURCE"

echo "Off My Lawn updated to $COMMIT"
