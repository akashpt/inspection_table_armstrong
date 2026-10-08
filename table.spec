# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('static', 'static'), ('templates', 'templates'), ('path.py', '.')]
binaries = []
hiddenimports = ['pymysql', 'reportlab.graphics.barcode.code39', 'reportlab.graphics.barcode.code93', 'reportlab.graphics.barcode.code128', 'reportlab.graphics.barcode.usps', 'reportlab.graphics.barcode.usps4s', 'reportlab.graphics.barcode.qr', 'reportlab.graphics.barcode.eanbc', 'reportlab.graphics.barcode.eanbc_european', 'reportlab.graphics.barcode.ecc200datamatrix', 'sklearn', 'torchvision._C', 'torchvision.ops', 'torchvision.ops.boxes']
hiddenimports += collect_submodules('classes')
tmp_ret = collect_all('torch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('torchvision')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='table',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['fabvi.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='table',
)
