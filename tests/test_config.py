from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.config import ConfigError, load_settings
from server.game_tcp import GameTcpServer


class ConfigTests(unittest.TestCase):
    def test_toml_values_override_legacy_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(
                """
[http]
port = 18080

[game]
tcp_port = 19001

[sdk]
auto_credit_g_points = false
""",
                encoding="utf-8",
            )
            settings = load_settings(
                config_path,
                environ={
                    "SERVER_HTTP_PORT": "28080",
                    "GAME_TCP_PORT": "29001",
                    "SDK_AUTO_CREDIT_G_POINTS": "1",
                },
            )

        self.assertEqual(settings.http.port, 18080)
        self.assertEqual(settings.game.tcp_port, 19001)
        self.assertFalse(settings.sdk.auto_credit_g_points)

    def test_environment_fills_missing_toml_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "empty.toml"
            config_path.write_text("", encoding="utf-8")
            settings = load_settings(
                config_path,
                environ={
                    "SERVER_HTTP_PORT": "28080",
                    "GAME_TCP_ADVERTISE_HOST": "10.0.0.2",
                    "SDK_DOMAIN_URLS": "http://10.0.0.2:8080, http://10.0.0.3:8080/",
                },
            )

        self.assertEqual(settings.http.port, 28080)
        self.assertEqual(settings.game.advertise_host, "10.0.0.2")
        self.assertEqual(
            settings.sdk.domain_urls,
            ("http://10.0.0.2:8080", "http://10.0.0.3:8080"),
        )

    def test_explicit_overrides_win_over_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("[http]\nport = 18080\n", encoding="utf-8")
            settings = load_settings(
                config_path,
                environ={"SERVER_HTTP_PORT": "28080"},
                overrides={"http.port": 38080},
            )

        self.assertEqual(settings.http.port, 38080)

    def test_game_tcp_server_uses_injected_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "empty.toml"
            config_path.write_text("", encoding="utf-8")
            settings = load_settings(
                config_path,
                environ={},
                overrides={
                    "storage.database": root / "server.sqlite3",
                    "logging.data_dir": root / "logs",
                    "game.tcp_host": "127.0.0.1",
                    "game.tcp_port": 21002,
                    "game.advertise_host": "10.0.0.2",
                    "game.server_id": 7,
                    "game.init_capture": root / "init.json",
                    "game.gameplay_capture": root / "gameplay.json",
                    "game.poll_interval": 0.25,
                    "game.trace": True,
                },
            )
            service = GameTcpServer(settings=settings)

        self.assertEqual(service.host, "127.0.0.1")
        self.assertEqual(service.port, 21002)
        self.assertEqual(service.server_id, 7)
        self.assertEqual(service.response_capture, root / "init.json")
        self.assertEqual(service.gameplay_capture, root / "gameplay.json")
        self.assertEqual(service.poll_interval, 0.25)
        self.assertTrue(service.trace)
        self.assertEqual(service.notify_url, "http://127.0.0.1:8080/local/notify-disabled")

    def test_invalid_config_values_fail_fast(self) -> None:
        cases = (
            ("[http]\nport = 0\n", "http.port"),
            ("[game]\npoll_interval = 0.01\n", "game.poll_interval"),
            ("[storage]\ntoken_ttl_seconds = 0\n", "storage.token_ttl_seconds"),
        )
        for content, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory) / "config.toml"
                config_path.write_text(content, encoding="utf-8")
                with self.assertRaises(ConfigError) as context:
                    load_settings(config_path)
                self.assertIn(expected, str(context.exception))

    def test_explicit_missing_or_malformed_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ConfigError):
                load_settings(root / "missing.toml")

            malformed = root / "malformed.toml"
            malformed.write_text("[http\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_settings(malformed)


if __name__ == "__main__":
    unittest.main()
