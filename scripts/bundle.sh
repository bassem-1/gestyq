#!/bin/bash
# Builds dist/gestyq.app (a tiny launcher around app.py) and installs it to /Applications.
# The app runs the source in this folder with the python picked below, so code edits need no rebuild.
# Usage: scripts/bundle.sh [--no-install]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/config.py")"
APP="$ROOT/dist/gestyq.app"

# same interpreter choice as run.sh, resolved to an absolute path (Finder launches get a bare PATH)
PY=""
if command -v conda >/dev/null 2>&1 && conda env list | grep -q '^vision '; then
  PY="$(conda run -n vision python -c 'import sys; print(sys.executable)')"
fi
[ -n "$PY" ] || PY="$(python3 -c 'import sys; print(sys.executable)')"
"$PY" -c "import mediapipe, cv2, AppKit" || { echo "error: $PY is missing requirements.txt packages" >&2; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
clang -O2 -Wall -mmacosx-version-min=12.0 -arch arm64 -arch x86_64 \
  -o "$APP/Contents/MacOS/gestyq" "$ROOT/launcher/main.c"
printf '%s\n' "$ROOT" > "$APP/Contents/Resources/source_dir"
printf '%s\n' "$PY" > "$APP/Contents/Resources/python"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>gestyq</string>
    <key>CFBundleDisplayName</key><string>gestyq</string>
    <key>CFBundleIdentifier</key><string>io.github.bassem-1.gestyq</string>
    <key>CFBundleExecutable</key><string>gestyq</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSUIElement</key><true/>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSCameraUsageDescription</key><string>gestyq watches your hands and head to move the cursor and switch apps. video never leaves your mac.</string>
</dict>
</plist>
PLIST
codesign --force --sign - --identifier io.github.bassem-1.gestyq "$APP"
echo "built $APP (python: $PY)"

if [ "${1:-}" != "--no-install" ]; then
  # stop running copies: the installed app and any `python app.py` started from this folder
  pkill -f "gestyq.app/Contents/MacOS/gestyq" 2>/dev/null || true
  for pid in $(pgrep -f 'app\.py' || true); do
    [ "$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" = "$ROOT" ] && kill "$pid" || true
  done
  rm -rf /Applications/gestyq.app
  cp -R "$APP" /Applications/
  echo "installed /Applications/gestyq.app"
fi
