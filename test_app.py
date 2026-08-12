import unittest
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app
import image2_cli


@contextmanager
def test_database(path):
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class Image2ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_db = app.DB
        cls.original_outputs = app.OUTPUTS
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        app.DB = root / "image2.sqlite3"
        app.OUTPUTS = root / "outputs"
        app.OUTPUTS.mkdir()
        app.init_db()
        cls.client = TestClient(app.app)
        cls.headers = {"X-Image2-Local-Token": app.local_token()}

    @classmethod
    def tearDownClass(cls):
        app.DB = cls.original_db
        app.OUTPUTS = cls.original_outputs
        cls.temp_dir.cleanup()

    def setUp(self):
        with test_database(app.DB) as conn:
            conn.execute("DELETE FROM provider_profiles")
            conn.execute("DELETE FROM image2_settings")
            conn.execute("DELETE FROM generations")

    def seed_provider(self):
        with test_database(app.DB) as conn:
            conn.execute(
                """INSERT INTO provider_profiles
                   (id, name, base_url, model, generation_path, edit_path, auth_type, image_field, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("test-provider", "Test Provider", "http://127.0.0.1:9999/v1", "test-image", "/images/generations", "/images/edits", "none", "image[]", 1, 1),
            )
            conn.execute("INSERT INTO image2_settings(key, value) VALUES ('active_provider', ?)", ("test-provider",))

    def test_health_requires_local_token(self):
        self.assertEqual(self.client.get("/api/health").status_code, 401)
        response = self.client.get("/api/health", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["first_use"])
        self.assertFalse(response.json()["configured"])

    def test_unconfigured_generation_is_rejected(self):
        response = self.client.post("/api/generate", headers=self.headers, json={"prompt": "x"})
        self.assertEqual(response.status_code, 409)

    def test_invalid_generation_options_are_rejected(self):
        response = self.client.post("/api/generate", headers=self.headers, json={"prompt": "x", "size": "bad"})
        self.assertEqual(response.status_code, 400)

    def test_common_custom_size_is_forwarded_to_provider(self):
        self.seed_provider()
        upstream = AsyncMock(return_value={"data": [{}]})
        saved = AsyncMock(return_value=["/outputs/mock.png"])
        with patch.object(app, "image_provider_request", upstream), patch.object(app, "save_results", saved):
            response = self.client.post(
                "/api/generate",
                headers=self.headers,
                json={"prompt": "x", "size": "1600x1200", "quality": "high"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(upstream.await_args.kwargs["json"]["size"], "1600x1200")
        self.assertEqual(upstream.await_args.kwargs["json"]["quality"], "high")

    def test_size_over_pixel_limit_is_rejected(self):
        with patch.object(app, "MAX_IMAGE_PIXELS", 1_000_000):
            response = self.client.post(
                "/api/generate",
                headers=self.headers,
                json={"prompt": "x", "size": "1024x1024"},
            )
        self.assertEqual(response.status_code, 400)

    def test_private_reference_url_is_rejected(self):
        response = self.client.post("/api/edit-url", headers=self.headers, json={"prompt": "x", "image_url": "http://127.0.0.1/ref.png"})
        self.assertEqual(response.status_code, 400)

    def test_edit_upload_uses_image_array_field(self):
        self.seed_provider()
        upstream = AsyncMock(return_value={"data": [{}]})
        saved = AsyncMock(return_value=["/outputs/mock.png"])
        with patch.object(app, "image_provider_request", upstream), patch.object(app, "save_results", saved):
            response = self.client.post(
                "/api/edit",
                headers=self.headers,
                data={"prompt": "x", "size": "1024x1024", "quality": "medium"},
                files=[("image[]", ("ref.png", b"png", "image/png"))],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(upstream.await_args.kwargs["files"][0][0], "image[]")

    def test_edit_prompt_limit_is_enforced_server_side(self):
        response = self.client.post(
            "/api/edit",
            headers=self.headers,
            data={"prompt": "x" * (app.MAX_PROMPT_LENGTH + 1)},
            files=[("image[]", ("ref.png", b"png", "image/png"))],
        )
        self.assertEqual(response.status_code, 413)

    def test_generation_uses_active_provider_model_and_path(self):
        self.seed_provider()
        upstream = AsyncMock(return_value={"data": [{}]})
        saved = AsyncMock(return_value=["/outputs/mock.png"])
        with patch.object(app, "image_provider_request", upstream), patch.object(app, "save_results", saved):
            response = self.client.post("/api/generate", headers=self.headers, json={"prompt": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(upstream.await_args.args[0], "/images/generations")
        self.assertEqual(upstream.await_args.kwargs["json"]["model"], app.active_provider()["model"])

    def test_provider_config_does_not_return_api_key(self):
        provider_id = "test-provider"
        with patch.object(app, "save_keyring_password") as save_key, patch.object(app, "keyring_password", return_value=None):
            response = self.client.post(
                "/api/providers",
                headers=self.headers,
                json={
                    "id": provider_id,
                    "name": "Test Provider",
                    "base_url": "http://127.0.0.1:9999/v1",
                    "model": "test-image",
                    "api_key": "test-secret",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("api_key", response.json())
            self.assertEqual(response.json()["id"], provider_id)
            save_key.assert_called_once_with(provider_id, "test-secret")
            listing = self.client.get("/api/providers", headers=self.headers)
            self.assertEqual(listing.status_code, 200)
            self.assertNotIn("api_key", listing.text)
        with patch.object(app, "delete_keyring_password"):
            self.client.delete(f"/api/providers/{provider_id}", headers=self.headers)

    def test_history_scans_existing_output_files_without_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "new.png").write_bytes(b"png")
            (output_dir / "notes.txt").write_text("ignore", encoding="utf-8")
            with patch.object(app, "OUTPUTS", output_dir):
                history = self.client.get("/api/history", headers=self.headers)
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["filename"] for item in history.json()], ["new.png"])
        self.assertNotIn("prompt", history.text)

    @patch.object(image2_cli.httpx, "get")
    def test_cli_health_probe_sends_local_token(self, get):
        image2_cli.ensure_server("http://127.0.0.1:8765")
        self.assertEqual(get.call_args.kwargs["headers"], self.headers)

    def test_codex_status_reports_project_connection_without_secrets(self):
        response = self.client.get("/api/codex-status", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        status = response.json()
        self.assertTrue(status["project_connected"])
        self.assertTrue(status["connected"])
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("auth.json", status["prompt"])

    def test_codex_skill_install_copies_project_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            target_home = Path(directory) / ".codex"
            with patch.object(app, "codex_home", return_value=target_home):
                response = self.client.post("/api/codex/install", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue((target_home / "skills" / app.CODEX_SKILL_ID / "SKILL.md").is_file())
            self.assertTrue((target_home / "skills" / app.CODEX_SKILL_ID / "image2_cli.py").is_file())
            self.assertTrue((target_home / "skills" / app.CODEX_SKILL_ID / "image2-client.json").is_file())
            self.assertTrue(response.json()["global_connected"])


if __name__ == "__main__":
    unittest.main()
