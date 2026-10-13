"""服务端单元测试入口（兼容便携 embeddable Python：不依赖 PYTHONPATH/-m 发现）。

用法：python run_tests.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 本文件位于 server/ 根目录，确保其在 sys.path 以便 import app.*
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(ROOT / "app" / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
