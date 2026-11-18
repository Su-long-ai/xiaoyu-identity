from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import model_adapter
from xiaoyu.runtime.credentials import (
    KeyringCredentialRef,
    SystemKeyringCredentialStore,
)


class _FakeKeyringModule:
    def __init__(self, value=None):
        self.value = value
        self.calls = []

    def get_password(self, service, username):
        self.calls.append((service, username))
        return self.value


class ReuseFirstCredentialTests(unittest.TestCase):
    def test_system_keyring_adapter_reads_only_requested_reference(self):
        fake = _FakeKeyringModule("  vault-secret  ")
        store = SystemKeyringCredentialStore(fake)
        value = store.get(
            KeyringCredentialRef(
                service="XiaoYu Provider API",
                username="qwen",
            )
        )
        self.assertEqual(value, "vault-secret")
        self.assertEqual(
            fake.calls,
            [("XiaoYu Provider API", "qwen")],
        )

    def test_environment_override_remains_first_for_deployment(self):
        config = {
            "provider": "qwen",
            "key_env": "XIAOYU_TEST_PROVIDER_KEY",
        }
        with patch.dict(
            os.environ,
            {"XIAOYU_TEST_PROVIDER_KEY": "env-secret"},
            clear=False,
        ), patch.object(
            model_adapter,
            "_keyring_provider_key",
            return_value="vault-secret",
        ):
            self.assertEqual(
                model_adapter._provider_key(config),
                "env-secret",
            )

    def test_windows_keyring_precedes_legacy_plaintext_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy-key.txt"
            path.write_text("legacy-secret\n", encoding="utf-8")
            config = {
                "provider": "qwen",
                "key_env": "",
                "key_file": str(path),
            }
            with patch.object(
                model_adapter,
                "_keyring_provider_key",
                return_value="vault-secret",
            ):
                self.assertEqual(
                    model_adapter._provider_key(config),
                    "vault-secret",
                )

    def test_custom_provider_can_remain_explicitly_unauthenticated(self):
        config = {
            "provider": "custom",
            "key_env": "",
        }
        self.assertIsNone(model_adapter._keyring_ref(config))
        self.assertEqual(model_adapter._provider_key(config), "")

    def test_legacy_key_file_remains_compatible_when_keyring_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy-key.txt"
            path.write_text("legacy-secret\n", encoding="utf-8")
            config = {
                "provider": "deepseek_web",
                "key_env": "",
                "key_file": str(path),
            }
            with patch.object(
                model_adapter,
                "_keyring_provider_key",
                return_value="",
            ):
                self.assertEqual(
                    model_adapter._provider_key(config),
                    "legacy-secret",
                )

    def test_provider_config_preserves_explicit_keyring_reference(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "provider.json").write_text(
                '''{
                  "provider": "qwen",
                  "keyring_service": "XiaoYu Custom",
                  "keyring_username": "qwen-primary"
                }''',
                encoding="utf-8",
            )
            config = model_adapter.load_provider(home)
            self.assertEqual(
                config["keyring_service"],
                "XiaoYu Custom",
            )
            self.assertEqual(
                config["keyring_username"],
                "qwen-primary",
            )


if __name__ == "__main__":
    unittest.main()
