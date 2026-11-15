#!/bin/bash
# Builds dist/gestyq.app and installs it to /Applications. The launcher EMBEDS the python picked below
# (links its libpython, sets PYTHONHOME) so the bundle's own process runs app.py. It runs the source in
# this folder, so code edits need no rebuild; rebuild only if the folder or the python env moves.
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

PYHOME="$("$PY" -c 'import sys; print(sys.prefix)')"
LIBDIR="$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
LIBPY="libpython$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("py_version_short"))').dylib"
[ -f "$LIBDIR/$LIBPY" ] || { echo "error: $LIBDIR/$LIBPY not found (need a shared libpython)" >&2; exit 1; }
LIBNAME="$(basename "$LIBPY" .dylib)"; LIBNAME="${LIBNAME#lib}"
ARCH="$(lipo -archs "$LIBDIR/$LIBPY" | awk '{print $1}')"     # build for the dylib's arch

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
clang -O2 -Wall -mmacosx-version-min=12.0 -arch "$ARCH" \
  -L"$LIBDIR" -l"$LIBNAME" -Wl,-rpath,"$LIBDIR" \
  -o "$APP/Contents/MacOS/gestyq" "$ROOT/launcher/main.c"
"$PY" "$ROOT/scripts/make_icon.py" "$APP/Contents/Resources/AppIcon.icns"
printf '%s\n' "$ROOT" > "$APP/Contents/Resources/source_dir"
printf '%s\n' "$PYHOME" > "$APP/Contents/Resources/python_home"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>gestyq</string>
    <key>CFBundleDisplayName</key><string>gestyq</string>
    <key>CFBundleIdentifier</key><string>io.github.bassem-1.gestyq</string>
    <key>CFBundleExecutable</key><string>gestyq</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
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
