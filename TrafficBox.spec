# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'test',
        'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf',
        'PySide6.QtNetwork', 'PySide6.QtOpenGL', 'PySide6.QtVirtualKeyboard',
        'PySide6.QtWebEngine', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtSvg', 'PySide6.QtXml', 'PySide6.QtSql', 'PySide6.QtMultimedia'
    ],
    noarchive=False,
    optimize=2,
)

# Strip unused heavy DLLs and software renderers
excluded_binaries = {
    'opengl32sw.dll',
    'qt6quick.dll',
    'qt6pdf.dll',
    'qt6qml.dll',
    'qt6qmlmodels.dll',
    'qt6qmlmeta.dll',
    'qt6qmlworkerscript.dll',
    'qt6network.dll',
    'qt6virtualkeyboard.dll',
    'qt6opengl.dll',
    'qt6svg.dll',
    'qtvirtualkeyboardplugin.dll',
    'qdirect2d.dll',
    'qoffscreen.dll',
    'qminimal.dll',
    'qnetworklistmanager.dll',
    'qcertonlybackend.dll',
    'qopensslbackend.dll',
    'qschannelbackend.dll',
}

a.binaries = [x for x in a.binaries if not any(ex in x[0].lower() for ex in excluded_binaries)]

# Strip unused language files from Qt (we only need German and English)
a.datas = [x for x in a.datas if not (x[0].startswith('PySide6/translations') and not any(k in x[0] for k in ['_de.', '_en.']))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TrafficBox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['local/app_icon.ico'],
)
