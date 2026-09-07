"""Unit and integration tests for Nginx Ingress Reverse Proxy configuration seam (SEAM-NGINX)."""

import os
import subprocess
import unittest
from pathlib import Path


class TestNginxConfigSeam(unittest.TestCase):
    """Test suite verifying Nginx reverse proxy routing, WebSocket support, and health endpoints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).parent.parent
        cls.nginx_conf = cls.project_root / "docker" / "nginx" / "default.conf"

    def test_nginx_conf_file_exists(self) -> None:
        """Verify docker/nginx/default.conf exists on disk."""
        self.assertTrue(
            self.nginx_conf.exists(),
            f"Expected nginx configuration at {self.nginx_conf} to exist.",
        )

    def test_nginx_conf_has_required_upstreams_and_locations(self) -> None:
        """Verify upstreams, health route, api route, and websocket upgrade configuration."""
        content = self.nginx_conf.read_text()

        # Upstreams
        self.assertIn("upstream query_engine", content)
        self.assertIn("upstream streamlit", content)

        # Health endpoint
        self.assertIn("location /health", content)
        self.assertIn("return 200", content)
        self.assertIn("application/json", content)

        # API routing
        self.assertIn("location /api/", content)
        self.assertIn("proxy_pass http://query_engine", content)

        # Streamlit and WebSocket support
        self.assertIn("location /", content)
        self.assertIn("location /_stcore/", content)
        self.assertIn("proxy_pass http://streamlit", content)
        self.assertIn("proxy_set_header Upgrade $http_upgrade", content)
        self.assertIn("proxy_set_header Connection", content)
        self.assertIn("proxy_http_version 1.1", content)

    def test_nginx_conf_syntax_validity(self) -> None:
        """Verify Nginx configuration passes syntax validation if docker is available."""
        import shutil

        docker_bin = shutil.which("docker")
        if not docker_bin:
            self.skipTest("Docker CLI not available in current test environment")

        cmd = [
            docker_bin,
            "run",
            "--rm",
            "--add-host",
            "query-engine:127.0.0.1",
            "--add-host",
            "streamlit:127.0.0.1",
            "-v",
            f"{self.nginx_conf.resolve()}:/etc/nginx/conf.d/default.conf:ro",
            "nginx:alpine",
            "nginx",
            "-t",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(
            result.returncode,
            0,
            f"Nginx configuration syntax check failed:\nStdout: {result.stdout}\nStderr: {result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
