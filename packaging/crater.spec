# PyInstaller build recipe: pyinstaller --noconfirm packaging/crater.spec
import sys
from pathlib import Path

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from crater_app import __version__  # noqa: E402

icon = str(root / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns"))

a = Analysis(
    [str(root / "run_desktop.py")],
    pathex=[str(root)],
    datas=[(str(root / "crater_app" / "desktop" / "assets"), "crater_app/desktop/assets")],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Crater",
    console=False,
    icon=icon,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Crater", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Crater.app",
        icon=icon,
        bundle_identifier="io.github.braydenherzberg.crater",
        version=__version__,
        info_plist={
            "CFBundleName": "Crater",
            "CFBundleDisplayName": "Crater",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Video",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["public.movie", "public.mpeg-4", "com.apple.quicktime-movie"],
                }
            ],
        },
    )
