# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec do FT8SWX.

Gera uma pasta autossuficiente (dist/FT8SWX) com FT8SWX.exe. Quem recebe o
arquivo NAO precisa de Python instalado.

Uso (no Windows):
    build_exe.bat
ou manualmente:
    pyinstaller --noconfirm --clean ft8swx.spec
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821 - definido pelo PyInstaller

if sys.platform.startswith("win"):
    LIB = "ft8shim.dll"
elif sys.platform == "darwin":
    LIB = "libft8shim.dylib"
else:
    LIB = "libft8shim.so"

NATIVE = ROOT / "native" / LIB
if not NATIVE.exists():
    raise SystemExit(
        f"Biblioteca nativa ausente: {NATIVE}\n"
        "Rode primeiro:  python build_native.py"
    )

datas = [
    (str(NATIVE), "native"),
    (str(ROOT / "native" / "ft8swx.png"), "native"),
    (str(ROOT / "ft8swx" / "data" / "world.json"), "ft8swx/data"),
]
binaries = [(str(NATIVE), "native")]

# importados dinamicamente / por plugins
hiddenimports = [
    "serial.tools.list_ports",
    "serial.tools.list_ports_common",
    "sounddevice",
    "numpy",
    "ft8swx.ui.export_dialog",
    "ft8swx.ui.settings_dialog",
    "ft8swx.ui.waterfall",
    "ft8swx.ui.map_view",
    "ft8swx.ui.theme",
]

# enxuga o pacote: nada disso e' usado pelo app
excludes = [
    "tkinter", "matplotlib", "scipy", "pytest", "IPython", "PIL", "setuptools",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialBus",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtDBus", "PySide6.QtNetwork",
    "PySide6.QtPrintSupport", "PySide6.QtUiTools", "PySide6.QtXml",
]

a = Analysis(  # noqa: F821
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Traducoes do Qt pesam ~7 MB e a interface e' em portugues
a.datas = [d for d in a.datas if "translations" not in d[0].lower()]

pyz = PYZ(a.pure)  # noqa: F821

icon = ROOT / "ft8swx.ico"
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FT8SWX",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon) if icon.exists() else None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FT8SWX",
)
