#!/usr/bin/env bash
set -euo pipefail

NAME=pyforge
VERSION=0.1.0
ARCH=$(dpkg --print-architecture)

# system libs (Qt xcb plugin deps)
sudo apt install -y python3-venv python3-dev binutils \
  libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libdbus-1-3 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-shape0 libxcb-xinerama0

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install PySide6 pyinstaller      # plus your own requirements

rm -rf build dist

pyinstaller --noconfirm --clean --windowed \
  --name "$NAME" \
  --add-data "dark.qss:." \
  --add-data "assets:assets" \
  --exclude-module tkinter \
  --exclude-module PySide6.QtWebEngineCore \
  --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.QtWebEngineQuick \
  --exclude-module PySide6.QtQml \
  --exclude-module PySide6.QtQuick \
  --exclude-module PySide6.QtQuickWidgets \
  --exclude-module PySide6.QtMultimedia \
  --exclude-module PySide6.QtMultimediaWidgets \
  --exclude-module PySide6.Qt3DCore \
  --exclude-module PySide6.Qt3DRender \
  --exclude-module PySide6.QtCharts \
  --exclude-module PySide6.QtDataVisualization \
  --exclude-module PySide6.QtPdf \
  --exclude-module PySide6.QtPdfWidgets \
  main.py

# ---- package as .deb ----
PKG="pkg/${NAME}_${VERSION}_${ARCH}"
rm -rf pkg
mkdir -p "$PKG/DEBIAN" "$PKG/opt/$NAME" "$PKG/usr/bin" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"

cp -r "dist/$NAME/." "$PKG/opt/$NAME/"
ln -s "/opt/$NAME/$NAME" "$PKG/usr/bin/$NAME"
cp assets/icon.png "$PKG/usr/share/icons/hicolor/256x256/apps/$NAME.png"

cat > "$PKG/usr/share/applications/$NAME.desktop" << EOF
[Desktop Entry]
Type=Application
Name=PyForge
Comment=Lightweight Python IDE
Exec=/opt/$NAME/$NAME
Icon=$NAME
Categories=Development;IDE;
Terminal=false
EOF

cat > "$PKG/DEBIAN/control" << EOF
Package: $NAME
Version: $VERSION
Architecture: $ARCH
Maintainer: Ahil <you@example.com>
Depends: libegl1, libgl1, libxkbcommon-x11-0, libxcb-cursor0, libdbus-1-3
Section: devel
Priority: optional
Description: PyForge - lightweight Python IDE
EOF

dpkg-deb --build --root-owner-group "$PKG"
echo "Built: pkg/${NAME}_${VERSION}_${ARCH}.deb"