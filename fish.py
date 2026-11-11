# -*- coding: utf-8 -*-
from __future__ import annotations
import runpy
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LEGACY=ROOT/"legacy"/"fish_legacy_20261029.py"

if __name__=="__main__":
    if "--legacy" in sys.argv:
        sys.argv=[str(LEGACY), *[x for x in sys.argv[1:] if x!="--legacy"]]
        runpy.run_path(str(LEGACY),run_name="__main__")
    else:
        runpy.run_path(str(ROOT/"companion.py"),run_name="__main__")
