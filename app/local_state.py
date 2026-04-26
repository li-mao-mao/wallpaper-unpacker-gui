import json
import os
from pathlib import Path
from typing import Any, Dict

APP_DIR_NAME = ".Wallpaper-Unpacker-GUI"
SETTINGS_FILE_NAME = "settings.json"
RUNS_DIR_NAME = "runs"


def get_app_dir() -> Path:
    env_dir = os.environ.get("WALLPAPER_UNPACKER_GUI_APP_DIR", "").strip()
    if env_dir:
        base = Path(env_dir).expanduser()
    else:
        base = Path.home() / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base



def get_runs_dir() -> Path:
    path = get_app_dir() / RUNS_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path



def get_settings_path() -> Path:
    return get_app_dir() / SETTINGS_FILE_NAME



def load_settings() -> Dict[str, Any]:
    path = get_settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}



def save_settings(data: Dict[str, Any]) -> Path:
    path = get_settings_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
