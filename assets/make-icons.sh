#!/usr/bin/env bash
# Regenerate the packaged app icons from the master SVG.
#
#   assets/wombat-appicon.svg  ->  assets/wombat.icns  (macOS)
#                              ->  assets/wombat.ico   (Windows)
#
# Requires: rsvg-convert, iconutil (macOS), magick (ImageMagick).
# Run from anywhere: ./assets/make-icons.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
svg="$here/wombat-appicon.svg"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

png() { rsvg-convert -w "$1" -h "$1" "$svg" -o "$2"; }

# --- macOS .icns: build an .iconset then let iconutil assemble it ------------
set="$tmp/wombat.iconset"
mkdir -p "$set"
for sz in 16 32 128 256 512; do
  png "$sz"          "$set/icon_${sz}x${sz}.png"
  png "$((sz * 2))"  "$set/icon_${sz}x${sz}@2x.png"
done
iconutil -c icns "$set" -o "$here/wombat.icns"

# --- Windows .ico: multi-resolution, largest sizes at PNG compression --------
ico_pngs=()
for sz in 16 24 32 48 64 128 256; do
  png "$sz" "$tmp/ico_${sz}.png"
  ico_pngs+=("$tmp/ico_${sz}.png")
done
magick "${ico_pngs[@]}" "$here/wombat.ico"

echo "Wrote:"
echo "  $here/wombat.icns"
echo "  $here/wombat.ico"
