"""Local application launch discovery and execution."""

from __future__ import annotations

from dataclasses import dataclass
import os
import plistlib
from pathlib import Path
import subprocess
import time

from agent.app_launch_presets import MACOS_APP_LAUNCH_PRESETS


@dataclass(frozen=True)
class ApplicationLaunchSpec:
    bundle_id: str = ""
    app_name: str = ""
    path: str = ""
    windows: str = ""
    linux: str = ""


CUSTOM_APP_LAUNCHES: dict[str, ApplicationLaunchSpec] = {}
MACOS_APP_SEARCH_DIRS = (
    "/Applications",
    os.path.expanduser("~/Applications"),
    "/System/Applications",
    "/System/Applications/Utilities",
)
DYNAMIC_APP_LAUNCH_CACHE: tuple[float, dict[str, ApplicationLaunchSpec]] | None = None
DYNAMIC_APP_LAUNCH_CACHE_SECONDS = 60.0
COMMON_APP_LAUNCH_ALIASES = {
    "Google Chrome": ("谷歌浏览器", "Chrome", "谷歌"),
    "Lark": ("飞书",),
    "WeChat": ("微信",),
    "NeteaseMusic": ("网易云音乐", "网易云"),
    "NetEaseMusic": ("网易云音乐", "网易云"),
    "TencentMeeting": ("腾讯会议",),
    "wpsoffice": ("WPS",),
    "iTerm": ("终端",),
    "iTerm2": ("终端",),
    "Terminal": ("终端",),
}


def load_app_launches(app_launches) -> None:
    CUSTOM_APP_LAUNCHES.clear()
    if not isinstance(app_launches, dict):
        return
    for name, spec in app_launches.items():
        if not isinstance(name, str) or not name.strip():
            continue
        parsed = parse_app_launch_spec(spec)
        if parsed is None:
            print(f"[typer] 忽略应用启动动作 {name!r}: 必须是字符串或映射")
            continue
        CUSTOM_APP_LAUNCHES[name.strip()] = parsed


def app_launch(name: str, os_name: str, blocked_names: set[str] | None = None) -> ApplicationLaunchSpec | None:
    if blocked_names and name in blocked_names:
        return None
    return app_launches_for_system(os_name).get(name)


def app_launches_for_system(os_name: str) -> dict[str, ApplicationLaunchSpec]:
    launches: dict[str, ApplicationLaunchSpec] = {}
    if os_name == "Darwin":
        for name, spec in MACOS_APP_LAUNCH_PRESETS.items():
            parsed = parse_app_launch_spec(spec)
            if parsed is not None:
                launches[name] = parsed
        for name, spec in discover_macos_app_launches().items():
            launches.setdefault(name, spec)
    launches.update(CUSTOM_APP_LAUNCHES)
    return launches


def launch_application(spec: ApplicationLaunchSpec, os_name: str) -> bool:
    if os_name == "Darwin":
        if spec.bundle_id:
            subprocess.Popen(["open", "-b", spec.bundle_id])
            return True
        if spec.path:
            subprocess.Popen(["open", spec.path])
            return True
        if spec.app_name:
            subprocess.Popen(["open", "-a", spec.app_name])
            return True
        return False
    if os_name == "Windows":
        target = spec.windows or spec.app_name
        if target:
            subprocess.Popen(["cmd", "/c", "start", "", target])
            return True
        return False
    target = spec.linux or spec.app_name
    if target:
        subprocess.Popen(target, shell=True)
        return True
    return False


def discover_macos_app_launches() -> dict[str, ApplicationLaunchSpec]:
    global DYNAMIC_APP_LAUNCH_CACHE
    now = time.monotonic()
    if (
        DYNAMIC_APP_LAUNCH_CACHE is not None
        and now - DYNAMIC_APP_LAUNCH_CACHE[0] < DYNAMIC_APP_LAUNCH_CACHE_SECONDS
    ):
        return dict(DYNAMIC_APP_LAUNCH_CACHE[1])

    launches: dict[str, ApplicationLaunchSpec] = {}
    for directory in MACOS_APP_SEARCH_DIRS:
        root = Path(directory).expanduser()
        for app_path in iter_macos_app_bundles(root):
            spec = macos_app_launch_spec_from_bundle(app_path)
            for label in macos_app_launch_labels(spec, app_path):
                action = f"打开{label}"
                launches.setdefault(action, spec)
    DYNAMIC_APP_LAUNCH_CACHE = (now, launches)
    return dict(launches)


def iter_macos_app_bundles(root: Path):
    if not root.exists():
        return
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name.endswith(".app") and child.is_dir():
                yield child
                continue
            if depth < 2 and child.is_dir():
                stack.append((child, depth + 1))


def macos_app_launch_spec_from_bundle(app_path: Path) -> ApplicationLaunchSpec:
    bundle_id = ""
    app_name = app_path.stem
    info_path = app_path / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as f:
            info = plistlib.load(f)
        bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
        app_name = str(
            info.get("CFBundleDisplayName")
            or info.get("CFBundleName")
            or app_name
        ).strip()
    except Exception:
        pass
    return ApplicationLaunchSpec(
        bundle_id=bundle_id,
        app_name=app_name or app_path.stem,
        path=str(app_path),
    )


def macos_app_launch_labels(
    spec: ApplicationLaunchSpec,
    app_path: Path,
) -> tuple[str, ...]:
    labels: list[str] = []
    for label in (spec.app_name, app_path.stem):
        if label and label not in labels:
            labels.append(label)
    for alias in COMMON_APP_LAUNCH_ALIASES.get(spec.app_name, ()):
        if alias not in labels:
            labels.append(alias)
    return tuple(labels)


def parse_app_launch_spec(spec) -> ApplicationLaunchSpec | None:
    if isinstance(spec, str):
        value = spec.strip()
        if not value:
            return None
        if "." in value and " " not in value and "/" not in value:
            return ApplicationLaunchSpec(bundle_id=value)
        return ApplicationLaunchSpec(app_name=value, windows=value, linux=value)
    if not isinstance(spec, dict):
        return None
    bundle_id = string_config_value(
        spec,
        "macos_bundle_id",
        "bundle_id",
        "bundle",
    )
    app_name = string_config_value(
        spec,
        "macos_name",
        "app_name",
        "name",
    )
    windows = string_config_value(spec, "windows", "windows_command")
    linux = string_config_value(spec, "linux", "linux_command")
    path = string_config_value(spec, "macos_path", "path")
    parsed = ApplicationLaunchSpec(
        bundle_id=bundle_id,
        app_name=app_name,
        path=path,
        windows=windows,
        linux=linux,
    )
    return parsed if any((bundle_id, app_name, path, windows, linux)) else None


def string_config_value(config: dict, *keys: str) -> str:
    for key in keys:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
