#!/bin/bash

set -e

echo "============================================"
echo "🚀 Building Vision Inspection EXE (Linux)"
echo "============================================"

rm -rf build
rm -rf dist
rm -f table.spec

pyinstaller --onedir \
    --console \
    --name="table" \
    --icon=fabvi.png \
    --hidden-import=pymysql \
    --hidden-import=reportlab.graphics.barcode.code39 \
    --hidden-import=reportlab.graphics.barcode.code93 \
    --hidden-import=reportlab.graphics.barcode.code128 \
    --hidden-import=reportlab.graphics.barcode.usps \
    --hidden-import=reportlab.graphics.barcode.usps4s \
    --hidden-import=reportlab.graphics.barcode.qr \
    --hidden-import=reportlab.graphics.barcode.eanbc \
    --hidden-import=reportlab.graphics.barcode.eanbc_european \
    --hidden-import=reportlab.graphics.barcode.ecc200datamatrix \
    --hidden-import=sklearn \
    --collect-submodules classes \
    --collect-all torch \
    --collect-all torchvision \
    --hidden-import=torchvision._C \
    --hidden-import=torchvision.ops \
    --hidden-import=torchvision.ops.boxes \
    --add-data "static:static" \
    --add-data "templates:templates" \
    --add-data "path.py:." \
    --specpath ./ \
    app.py

echo "============================================"
echo "✅ Build Completed Successfully!"
echo "============================================"