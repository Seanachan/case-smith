"""pytest root conftest:repo root 進 sys.path。

pipeline/ 沒有 __init__.py(test_seed_planner.py 用扁平 import,basedir 是
pipeline/),而 render/contract/E2E 測試用套件式 import(pipeline.x、
orchestrator.x,靠 namespace package)。root 進 path 讓兩種風格並存。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
