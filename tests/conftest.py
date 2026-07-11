import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def import_root_dashboard():
    """Import Dashboard with root dependencies after legacy-suite collection."""
    def load_root_module(module_name, expected_path):
        spec = importlib.util.spec_from_file_location(module_name, expected_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        assert Path(module.__file__).resolve() == expected_path
        return module

    for module_name in ("config", "financials", "macro_data"):
        expected_path = (PROJECT_ROOT / f"{module_name}.py").resolve()
        loaded = sys.modules.get(module_name)
        loaded_path = Path(getattr(loaded, "__file__", "")).resolve() if loaded else None
        if loaded is None or loaded_path != expected_path:
            load_root_module(module_name, expected_path)

    loaded_dashboard = sys.modules.get("dashboard")
    expected_dashboard_path = (PROJECT_ROOT / "dashboard.py").resolve()
    loaded_dashboard_path = (
        Path(getattr(loaded_dashboard, "__file__", "")).resolve()
        if loaded_dashboard
        else None
    )
    if loaded_dashboard is None or loaded_dashboard_path != expected_dashboard_path:
        return load_root_module("dashboard", expected_dashboard_path)
    return loaded_dashboard
