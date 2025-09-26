import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from ssh_jumpboard import config


class ConfigTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        patcher = mock.patch.object(
            config, "PlatformDirs", return_value=mock.Mock(user_config_dir=self.tmpdir.name)
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def _config_path(self) -> Path:
        return Path(self.tmpdir.name) / "config.json"

    def test_init_and_load_roundtrip(self):
        cfg = config.init_config("alice", "jump.example.com")
        path = self._config_path()
        self.assertTrue(path.exists())

        loaded = config.load_config()
        self.assertEqual(loaded.jump_user, "alice")
        self.assertEqual(loaded.jump_ip, "jump.example.com")
        self.assertEqual(loaded.history_limit, 10)

    def test_set_alias_persists(self):
        cfg = config.init_config("bob", "jump.internal")
        config.set_alias(cfg, "db", "10.0.0.1")
        data = json.loads(self._config_path().read_text())
        self.assertEqual(data["aliases"], {"db": "10.0.0.1"})

    def test_invalid_alias_name_rejected(self):
        cfg = config.init_config("carol", "jump.internal")
        with self.assertRaises(config.ValidationError):
            config.set_alias(cfg, "Invalid Name", "10.0.0.5")

    def test_invalid_jump_ip_rejected(self):
        with self.assertRaises(config.ValidationError):
            config.init_config("dave", "not valid host")
