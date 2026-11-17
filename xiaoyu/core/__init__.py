"""XiaoYu Semantic Core package.

Import concrete services from their modules (for example
`xiaoyu.core.temporal`). The package root deliberately avoids eager imports so
persistence repositories can depend on narrow Core value types without creating
initialization cycles or starting services as a side effect.
"""

__all__ = []
