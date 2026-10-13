#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$BASH_SOURCE")/../.." && pwd)"
PYTHON_BIN="$(printenv PYFORGE_PYTHON || true)"
VENV_PATH="$(printenv VIRTUAL_ENV || true)"

if [[ -z "$PYTHON_BIN" && -n "$VENV_PATH" && -x "$VENV_PATH/bin/python" ]]; then
    PYTHON_BIN="$VENV_PATH/bin/python"
fi
if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "Could not find the Python interpreter used to run PyForge." >&2
    echo "Set PYFORGE_PYTHON to the correct interpreter and retry." >&2
    exit 1
fi

DATA_HOME="$(printenv XDG_DATA_HOME || true)"
if [[ -z "$DATA_HOME" ]]; then
    DATA_HOME="$HOME/.local/share"
fi
APP_DIR_ESCAPED="$(printf '%s' "$APP_DIR" | sed 's/\\/\\\\/g; s/"/\\"/g')"
PYTHON_ESCAPED="$(printf '%s' "$PYTHON_BIN" | sed 's/\\/\\\\/g; s/"/\\"/g')"
mkdir -p "$DATA_HOME/applications" "$DATA_HOME/mime/packages"

cat > "$DATA_HOME/applications/pyforge.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PyForge
Comment=Python project editor
Exec="$PYTHON_ESCAPED" "$APP_DIR_ESCAPED/PyForge.py" %f
Terminal=false
Categories=Development;IDE;
MimeType=application/x-pyforge-project;
EOF

cp "$APP_DIR/packaging/linux/forproj.xml" "$DATA_HOME/mime/packages/pyforge-forproj.xml"
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database "$DATA_HOME/mime"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DATA_HOME/applications"
fi
if command -v xdg-mime >/dev/null 2>&1; then
    xdg-mime default pyforge.desktop application/x-pyforge-project
fi

echo "Registered .forproj files to open with PyForge."
echo "If the file manager does not update immediately, sign out and back in."
