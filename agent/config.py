"""加载项目根目录的 config.yaml，缺失时返回空 dict。"""

import pathlib
import yaml

_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.yaml"


def load() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
