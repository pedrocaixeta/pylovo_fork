from pathlib import Path
import yaml

# Configuration lives next to this module
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config_validation.yaml"


def load_config() -> tuple[Path, str, str]:
    """Load local test-data configuration.

    Returns:
        tuple[Path, str, str]: (data_dir, net_name, projection)
    Raises:
        FileNotFoundError: if the config file or data_dir is missing.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config_validation.yaml.template to config_validation.yaml "
            "and set data_dir (and optionally net_name, projection)."
        )

    # Read YAML config (empty file -> empty dict)
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}

    data_dir_raw = cfg.get("data_dir", "")
    if not data_dir_raw:
        raise FileNotFoundError(
            f"'data_dir' is empty in {CONFIG_PATH}. Please set an absolute path to your validation folder."
        )

    data_dir = Path(data_dir_raw).expanduser().resolve()
    if not data_dir.exists():
        raise FileNotFoundError(
            f"Configured data_dir does not exist: '{data_dir}'. Please set a valid path in {CONFIG_PATH}."
        )

    net_name = (cfg.get("net_name") or "").strip()
    projection = (cfg.get("projection") or "epsg:3035").strip()

    return data_dir, net_name, projection
