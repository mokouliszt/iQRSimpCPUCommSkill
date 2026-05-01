# -*- coding: utf-8 -*-
"""
pytestテスト用の共通設定。

- リポジトリ内の `skills/melsec-iqr-simple-cpu-comm-csv/scripts/` を import path に追加
- フォルダ名が `pytest` だと pytest 本体パッケージと衝突するため、
  rootdir をこのフォルダに固定し、ここから import する。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "melsec-iqr-simple-cpu-comm-csv" / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
