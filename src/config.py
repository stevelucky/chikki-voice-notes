import os
import yaml

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config.yaml")
_ENV_PATH = os.path.join(_BASE_DIR, ".env")

# Load .env file into environment
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            # Support optional `export ` prefix.
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            value = value.strip()
            # Strip inline comments only on unquoted values.
            if value and value[0] not in "'\"" and "#" in value:
                value = value.split("#", 1)[0].strip()
            os.environ.setdefault(key.strip(), value.strip("'\""))

def load_config():
    with open(_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    if cfg is None:
        raise ValueError(f"Config file is empty or invalid: {_CONFIG_PATH}")
    # Resolve relative dirs to absolute
    for key in ("recordings_dir",):
        if key in cfg.get("recording", {}):
            cfg["recording"][key] = os.path.join(_BASE_DIR, cfg["recording"][key])
    for key in ("notes_dir",):
        if key in cfg.get("output", {}):
            cfg["output"][key] = os.path.join(_BASE_DIR, cfg["output"][key])
    return cfg

CONFIG = load_config()
