# PyInstaller build definition for 班时钟.

from pathlib import Path


project_dir = Path(SPEC).parent
icon_path = project_dir / "assets" / "ban-clock.ico"
asset_dir = project_dir / "assets"


a = Analysis(
    [str(project_dir / "work_countdown.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[(str(asset_dir), "assets")],
    hiddenimports=["pystray._win32"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="班时钟",
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
    icon=str(icon_path),
)
