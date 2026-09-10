# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    ['main.py'],
    pathex=[],
    # Speech SDK uses ctypes with computed filenames, invisible to Analysis.
    binaries=collect_dynamic_libs('azure.cognitiveservices.speech'),
    datas=[],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on', 'pydub', 'pydub.utils', 'pydub.generators', 'edge_tts', 'dashscope', 'google.genai', 'azure.cognitiveservices.speech', 'aiohttp', 'sqlite3'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The desktop client calls local model servers; it does not bundle model
    # training runtimes or Python GUI stacks. Do not collect these from a
    # developer's global environment (notably the broken Tcl runtime hook).
    excludes=['tkinter', '_tkinter', 'PySide6', 'PyQt5', 'PyQt6', 'torch', 'torchvision', 'torchaudio', 'ChatTTS', 'faster_whisper', 'transformers', 'gradio', 'scipy', 'matplotlib', 'pandas', 'pygame', 'sympy', 'IPython', 'jedi', 'parso', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='voicespirit-backend',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='voicespirit-backend',
)
