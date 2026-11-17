"""XiaoYu implementation package.

This package is intentionally side-effect free on import. Runtime composition lives
behind explicit builders so importing contracts or persistence helpers never starts
providers, opens the identity database, or performs network access.
"""
from __future__ import annotations

__all__ = ["__version__"]
__version__ = "1.0.0-dev1"
