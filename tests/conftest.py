import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["ASTRBOT_ROOT"] = str(ROOT.parent / "work/test-astrbot")
spec = importlib.util.spec_from_file_location(
    "nanami_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
package = importlib.util.module_from_spec(spec)
sys.modules["nanami_plugin"] = package
spec.loader.exec_module(package)
