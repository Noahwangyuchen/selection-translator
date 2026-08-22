#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UUID="selection-translator@noahwangyuchen.local"
APP_DIR="$HOME/.local/share/selection-translator"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$UUID"
UNIT_DIR="$HOME/.config/systemd/user"
CONFIG_DIR="$HOME/.config/selection-translator"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"

if [[ "${XDG_CURRENT_DESKTOP:-}" != *GNOME* ]]; then
  echo "warning: GNOME was not detected in XDG_CURRENT_DESKTOP" >&2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "error: python3 was not found; set PYTHON_BIN to a compatible interpreter" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c "import dbus, gi" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN needs the dbus and PyGObject modules" >&2
  echo "Debian/Ubuntu: sudo apt install python3-dbus python3-gi" >&2
  exit 1
fi
if [[ ! -f "$ROOT/package/contents/data/ecdict.sqlite3" ]]; then
  echo "error: missing package/contents/data/ecdict.sqlite3" >&2
  exit 1
fi

mkdir -p "$APP_DIR" "$EXT_DIR" "$UNIT_DIR" "$CONFIG_DIR"
install -m755 "$ROOT/package/contents/tools/selection_translator.py" "$APP_DIR/selection_translator.py"
install -m644 "$ROOT/package/contents/data/ecdict.sqlite3" "$APP_DIR/ecdict.sqlite3"
install -m644 "$ROOT/gnome-extension/metadata.json" "$EXT_DIR/metadata.json"
install -m644 "$ROOT/gnome-extension/extension.js" "$EXT_DIR/extension.js"
install -m644 "$ROOT/gnome-extension/stylesheet.css" "$EXT_DIR/stylesheet.css"
cat >"$EXT_DIR/paths.json" <<EOF
{"python":"$PYTHON_BIN","script":"$APP_DIR/selection_translator.py","database":"$APP_DIR/ecdict.sqlite3"}
EOF

if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  cat >"$CONFIG_DIR/config.json" <<EOF
{
  "clipboard_auto_translate": true,
  "service_order": ["deepseek", "openai", "google"],
  "deepseek_api_key": "",
  "deepseek_model": "deepseek-v4-flash",
  "deepseek_base_url": "https://api.deepseek.com",
  "openai_api_key": "",
  "openai_model": "gpt-5-nano",
  "openai_base_url": "https://api.openai.com/v1"
}
EOF
  chmod 600 "$CONFIG_DIR/config.json"
fi

cat >"$UNIT_DIR/selection-translator.service" <<EOF
[Unit]
Description=Selection Translator service for GNOME
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart="$PYTHON_BIN" "$APP_DIR/selection_translator.py" --daemon --db "$APP_DIR/ecdict.sqlite3"
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload
systemctl --user enable selection-translator.service
systemctl --user restart selection-translator.service

echo "Installed Selection Translator GNOME files."
echo "Extension UUID: $UUID"
echo "Enable it with: gnome-extensions enable $UUID"
echo "Online translation config: $CONFIG_DIR/config.json"
