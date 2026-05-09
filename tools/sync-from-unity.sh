#!/usr/bin/env bash
# Refresh unity-dsp/ from the upstream Unity reference app.
#
# The .cs files in unity-dsp/ are copies of the canonical source in
# yennster/ei-vr-explorer-unity. They live in this repo for deterministic
# Docker builds — but stay edited upstream. Run this script when you've
# changed something there and want the deploy block to ship the update.
#
# Usage:  ./tools/sync-from-unity.sh [ref]
#         ref defaults to "main"; pass a commit SHA / branch / tag to pin.

set -euo pipefail

REPO="${UNITY_REPO:-yennster/ei-vr-explorer-unity}"
REF="${1:-main}"
RAW="https://raw.githubusercontent.com/${REPO}/${REF}/Assets/Scripts"
DEST="$(cd "$(dirname "$0")/.." && pwd)/unity-dsp"

mkdir -p "$DEST"

declare -a FILES=(Fft.cs SpectralAnalysisExtractor.cs MFEExtractor.cs MFCCExtractor.cs)
for f in "${FILES[@]}"; do
  echo "  • $f"
  curl -fsSL --retry 3 "$RAW/$f" -o "$DEST/$f.tmp" && mv "$DEST/$f.tmp" "$DEST/$f"
done

echo
echo "Done. Review changes:"
echo "  git -C $(dirname "$DEST") diff --stat unity-dsp/"
echo
echo "If happy, commit:"
echo "  git -C $(dirname "$DEST") add unity-dsp/ && git commit -m \"Sync unity-dsp from ${REPO}@${REF}\""
