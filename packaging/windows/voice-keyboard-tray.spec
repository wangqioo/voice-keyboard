# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

root = Path.cwd()
python_root = Path(sys.base_prefix)
tcl_dir = python_root / "tcl"
tkinter_dir = python_root / "Lib" / "tkinter"
dll_dir = python_root / "DLLs"

a = Analysis(
    [str(root / "agent" / "windows_tray.py")],
    pathex=[str(root)],
    binaries=[
        (str(dll_dir / "_tkinter.pyd"), "."),
        (str(dll_dir / "tcl86t.dll"), "."),
        (str(dll_dir / "tk86t.dll"), "."),
    ],
    datas=[
        (str(root / "config.yaml.example"), "."),
        (str(root / ".env.example"), "."),
        (str(tcl_dir), "tcl"),
        (str(tkinter_dir), "tkinter"),
    ],
    hiddenimports=[
        "agent.status_window_win",
        "agent.windows_tray",
        "agent.windows_main_window",
        "agent.main",
        "agent.stt",
        "agent.llm_editor",
        "agent.ai_handler",
        "agent.audio_monitor",
        "agent.push_to_talk",
        "agent.typer",
        "tkinter",
        "tkinter.messagebox",
        "tkinter.ttk",
        "pystray._win32",
        "PIL.Image",
        "PIL.ImageDraw",
        "sounddevice",
        "serial.tools.list_ports",
        "websocket",
        "zhipuai",
        "openai",
    ],
    hookspath=[str(root / "packaging" / "windows" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "AppKit",
        "Foundation",
        "Quartz",
        "objc",
        "PyObjCTools",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceKeyboard",
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
    name="VoiceKeyboard",
)
