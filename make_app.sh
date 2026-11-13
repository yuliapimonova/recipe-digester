#!/bin/zsh
# macOS only: build "Recipe Digester.app" in this folder. Drag it to Applications or the Dock.
set -e
cd "$(dirname "$0")"
APP="$PWD/Recipe Digester.app"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script quoted form of \"$PWD/launch.sh\""
if [[ -f static/icon.png ]]; then
  ICONSET=$(mktemp -d)/icon.iconset
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z $size $size static/icon.png --out "$ICONSET/icon_${size}x${size}.png" > /dev/null
    sips -z $((size * 2)) $((size * 2)) static/icon.png --out "$ICONSET/icon_${size}x${size}@2x.png" > /dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/applet.icns"
  touch "$APP"
fi
echo "Built $APP"
