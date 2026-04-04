# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['smart_video_splitter.py'],
    pathex=[],
    binaries=[('/opt/homebrew/bin/ffmpeg', '.'), ('/opt/homebrew/bin/ffprobe', '.')],
    datas=[],
    hiddenimports=[],
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
    name='SmartVideoSplitter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartVideoSplitter',
)
app = BUNDLE(
    coll,
    name='SmartVideoSplitter.app',
    icon=None,
    bundle_identifier=None,
)
