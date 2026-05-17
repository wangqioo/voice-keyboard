# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

root = Path.cwd()

a = Analysis(
    [str(root / "agent" / "windows_tray.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "config.yaml.example"), "."),
        (str(root / ".env.example"), "."),
    ],
    hiddenimports=[
        "agent.status_window_win",
        "agent.windows_tray",
        "agent.main",
        "agent.stt",
        "agent.llm_editor",
        "agent.ai_handler",
        "agent.audio_monitor",
        "agent.push_to_talk",
        "agent.typer",
        "pystray._win32",
        "PIL.Image",
        "PIL.ImageDraw",
        "sounddevice",
        "serial.tools.list_ports",
        "websocket",
        "zhipuai",
        "openai",
    ],
    hookspath=[],
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
