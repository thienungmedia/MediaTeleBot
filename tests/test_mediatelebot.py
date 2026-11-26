from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import bot
import gcal_bridge
import install_core
import pairing
import runtime
import safe_fs
import updater


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"
        self.config = {"bot_token": "example"}
        self.patch = patch.object(bot, "CONFIG_PATH", self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = Mock()

    def message(self, user, text, chat_type="private"):
        chat = user if chat_type == "private" else -42
        bot.handle_message(self.client, self.config, {"from": {"id": user}, "chat": {"type": chat_type, "id": chat}, "text": text})

    def test_pairing_requires_local_code_and_private_chat(self):
        code = pairing.issue_code(self.config)
        runtime.write_private_json(self.path, self.config)
        self.message(17, "/start")
        self.assertIsNone(runtime.read_config(self.path).get("owner_id"))
        self.client.reset_mock()
        self.message(18, "/pair " + code, "group")
        self.client.send_message.assert_not_called()
        self.message(17, "/pair invalid")
        self.assertIsNone(runtime.read_config(self.path).get("owner_id"))
        self.message(18, "/pair " + code)
        saved = runtime.read_config(self.path)
        self.assertEqual(saved["owner_id"], 18)
        self.assertNotIn("pairing_hash", saved)
        self.message(17, "/pair " + code)
        self.assertEqual(runtime.read_config(self.path)["owner_id"], 18)

    def test_expired_code_and_existing_owner(self):
        code = pairing.issue_code(self.config, now=5)
        self.assertFalse(pairing.claim(self.config, code, {"id": 42}, now=5 + pairing.LIFETIME))
        self.assertTrue(pairing.claim(self.config, code, {"id": 42}, now=6))
        self.config["chat_id"] = -200
        pairing.configure_token(self.config, "example")
        self.assertEqual(self.config["chat_id"], 42)
        self.assertEqual(self.config["owner_id"], 42)
        pairing.configure_token(self.config, "new-token")
        self.assertIsNone(self.config["owner_id"])
        self.assertIsNone(self.config["chat_id"])

    def test_collaborator_and_group_cannot_control(self):
        self.config.update(owner_id=17, allowed_users=[18])
        runtime.write_private_json(self.path, self.config)
        with patch.object(bot.nl_engine, "parse_and_execute_nl") as execute:
            self.message(18, "chụp màn hình")
            self.message(17, "chụp màn hình", "supergroup")
            execute.assert_not_called()
        for user, chat in [(18, {"type": "private", "id": 18}), (17, {"type": "group", "id": -7})]:
            bot.handle_callback(self.client, self.config, {"id": "x", "from": {"id": user}, "message": {"chat": chat}, "data": "rc_snap"})
            self.client.answer_callback.assert_called_with("x", "⛔ Không có quyền.")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "src"
        self.source.mkdir()
        self.drive = self.root / "Drive"
        self.drive.mkdir()
        self.orig = self.source / "edit.mov"
        self.orig.write_bytes(b"new data")
        for patcher in (patch.object(safe_fs, "find_google_drive_root", return_value=None),
                        patch.object(safe_fs, "mounted_roots", return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_same_size_diff_content_is_copied_without_overwriting(self):
        old = self.drive / self.orig.name
        old.write_bytes(b"old data")
        with patch.object(safe_fs, "IS_MAC", False):
            result = safe_fs.safe_copy(str(self.orig), str(self.drive), drive_upload=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(old.read_bytes(), b"old data")
        self.assertEqual(Path(result["dst"]).read_bytes(), b"new data")
        self.assertEqual(Path(result["dst"]).name, "edit (copy 1).mov")

    def test_concurrent_copies_choose_separate_names(self):
        results = []
        workers = [threading.Thread(target=lambda: results.append(safe_fs.safe_copy(str(self.orig), str(self.drive)))) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len({res["dst"] for res in results if res["ok"]}), 4)

    def test_move_does_not_replace_existing(self):
        old = self.drive / self.orig.name
        old.write_bytes(b"old data")
        result = safe_fs.safe_move(str(self.orig), str(self.drive))
        self.assertTrue(result["ok"], result)
        self.assertEqual(old.read_bytes(), b"old data")
        self.assertFalse(self.orig.exists())
        self.assertEqual(Path(result["dst"]).read_bytes(), b"new data")

    def test_collaborator_only_sees_relative_names(self):
        self.assertEqual(safe_fs.search_shared("edit", str(self.source)), ["src/edit.mov"])
        self.assertEqual(safe_fs.search_shared("edit", str(self.drive)), [])


class InfrastructureTests(unittest.TestCase):
    def test_http_and_certificate_errors_fail_closed(self):
        with self.assertRaises(ValueError):
            runtime.open_https("http://example.invalid")
        opener = Mock()
        opener.open.side_effect = ssl.SSLCertVerificationError("certificate")
        with patch.object(runtime.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(ssl.SSLCertVerificationError):
                runtime.open_https("https://example.invalid")
        opener.open.assert_called_once()

    def test_legacy_calendar_url_is_inactive(self):
        saved = {"gcal_webhook_url": "https://script.google.com/macros/s/testDeployment/exec"}
        with patch.object(gcal_bridge, "read_config", return_value=saved):
            self.assertTrue(gcal_bridge.get_calendar_sync_status()["legacy_webhook"])
            self.assertEqual(gcal_bridge.list_events("2026-09-01", "2026-09-02"), [])

    def test_calendar_rejects_unsigned_legacy_api_and_no_duplicate_retry(self):
        url = "https://script.google.com/macros/s/testDeployment/exec"
        key = "k" * 32
        with patch.object(gcal_bridge, "_post_webhook", return_value={"ok": True}) as post:
            with self.assertRaises(ValueError):
                gcal_bridge.configure_webhook(url, key)
            post.assert_called_once()
        with patch.object(gcal_bridge, "read_config", return_value={"gcal_webhook_url": url, "gcal_webhook_secret": key}):
            with patch.object(gcal_bridge, "_post_webhook", side_effect=TimeoutError) as post:
                import datetime
                result = gcal_bridge.create_google_calendar_event("Quay", datetime.date(2026, 9, 1), datetime.date(2026, 9, 1))
                self.assertEqual(result, {"method": "uncertain"})
                post.assert_called_once()

    def test_release_command_is_only_a_fixed_link(self):
        with patch.object(updater, "check_for_updates", return_value={"has_update": True, "latest_version": "v1.9.1"}):
            text, markup = updater.update_message()
        self.assertIn("1.9.1", text)
        self.assertEqual(markup["inline_keyboard"][0][0]["url"], updater.RELEASES_URL)
        self.assertFalse(hasattr(updater, "perform_update"))

    def test_config_changes_are_serialized(self):
        with tempfile.TemporaryDirectory() as folder:
            config_file = Path(folder) / "config.json"
            workers = [threading.Thread(target=runtime.edit_config, args=(lambda c, i=i: c.update({str(i): i}), config_file)) for i in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            self.assertEqual(runtime.read_config(config_file), {str(i): i for i in range(8)})
            if not runtime.IS_WINDOWS:
                self.assertEqual(config_file.stat().st_mode & 0o777, 0o600)

    def test_install_without_network_copies_runtime_and_reuses_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            patchers = [patch.object(install_core, "BASE_DIR", data), patch.object(install_core, "BOT_SCRIPT", data / "bot.py"),
                        patch.object(install_core, "verify_telegram_token", return_value="test_bot"),
                        patch.object(install_core, "read_config", side_effect=lambda: runtime.read_config(data / "config.json")),
                        patch.object(install_core, "edit_config", side_effect=lambda op: runtime.edit_config(op, data / "config.json"))]
            for patcher in patchers:
                patcher.start()
            try:
                first = install_core.install("fake_token", start=False)
                self.assertTrue(first["code"])
                self.assertTrue((data / "runtime.py").is_file())
                runtime.edit_config(lambda c: c.update(owner_id=71), data / "config.json")
                self.assertIsNone(install_core.install("fake_token", start=False)["code"])
                self.assertEqual(runtime.read_config(data / "config.json")["owner_id"], 71)
            finally:
                for patcher in reversed(patchers):
                    patcher.stop()

    def test_windows_mode_keeps_only_supported_menu_commands(self):
        with patch.object(bot, "IS_MAC", False):
            markup = bot.build_home_keyboard()
        data = {row["callback_data"] for group in markup["inline_keyboard"] for row in group}
        self.assertIn("drives", data)
        self.assertFalse(any(action.startswith(("rc_", "trash_", "apps_")) for action in data))


if __name__ == "__main__":
    unittest.main()
