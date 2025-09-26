from datetime import datetime, timezone
import tempfile
from unittest import TestCase, mock

from ssh_jumpboard import config, history


class HistoryTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        patcher = mock.patch.object(
            config, "PlatformDirs", return_value=mock.Mock(user_config_dir=self.tmpdir.name)
        )
        self.addCleanup(patcher.stop)
        patcher.start()
        self.cfg = config.init_config("erin", "jump.test")

    def test_record_and_list_recent(self):
        history.record(self.cfg, "10.0.0.2")
        items = history.list_recent(self.cfg)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].target_ip, "10.0.0.2")
        self.assertIsInstance(items[0].ts, datetime)
        self.assertIsNotNone(items[0].ts.tzinfo)

    def test_dedup_consecutive_entries(self):
        history.record(self.cfg, "10.0.0.3")
        first_ts = history.list_recent(self.cfg)[0].ts
        history.record(self.cfg, "10.0.0.3")
        items = history.list_recent(self.cfg)
        self.assertEqual(len(items), 1)
        self.assertNotEqual(items[0].ts, first_ts)

    def test_respects_history_limit(self):
        self.cfg.history_limit = 2
        for idx in range(3):
            history.record(self.cfg, f"host-{idx}")
        items = history.list_recent(self.cfg)
        self.assertEqual(len(items), 2)
        self.assertEqual([item.target_ip for item in items], ["host-2", "host-1"])

    def test_clear_history(self):
        history.record(self.cfg, "10.0.0.4")
        history.clear(self.cfg)
        self.assertEqual(history.list_recent(self.cfg), [])
