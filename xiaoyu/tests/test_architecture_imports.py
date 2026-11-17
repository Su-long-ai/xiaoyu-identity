from __future__ import annotations

import importlib
import sys
import unittest


MODULES = (
    "xiaoyu",
    "xiaoyu.contracts",
    "xiaoyu.core",
    "xiaoyu.persistence",
    "xiaoyu.runtime",
    "xiaoyu.providers",
    "xiaoyu.tools",
    "xiaoyu.surfaces",
    "xiaoyu.release",
    "xiaoyu.guardian",
)


class ArchitectureImportTests(unittest.TestCase):
    def test_namespaces_import_without_optional_runtime_dependencies(self):
        before = set(sys.modules)
        for name in MODULES:
            module = importlib.import_module(name)
            self.assertIsNotNone(module)
        loaded = set(sys.modules) - before
        self.assertFalse(any(name.startswith("sqlite3.dbapi2") for name in loaded))

    def test_import_does_not_create_global_runtime_objects(self):
        module = importlib.import_module("xiaoyu")
        forbidden = {"app", "runtime", "database", "provider", "client"}
        public_names = {name.lower() for name in vars(module) if not name.startswith("_")}
        self.assertTrue(forbidden.isdisjoint(public_names))


if __name__ == "__main__":
    unittest.main()
