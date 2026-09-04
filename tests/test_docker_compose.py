"""Unit tests for Docker Compose topology seam (SEAM-COMPOSE).

Follows TREM principles:
- Testable: Inspects parsed YAML data structure without requiring a running Docker daemon.
- Readable: Direct assertions on services, ports, volume bindings, and healthcheck contracts.
- Maintainable: Verification that all Phase 2 requirements (INF-01, EMB-02, LocalFS) are satisfied.
"""

import unittest
from pathlib import Path
import yaml


class TestDockerComposeSeam(unittest.TestCase):
    """Test suite verifying docker-compose.yml topology and configuration."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.compose_path = Path(__file__).parent.parent / "docker-compose.yml"
        if cls.compose_path.exists():
            with open(cls.compose_path, "r", encoding="utf-8") as f:
                cls.compose = yaml.safe_load(f)
        else:
            cls.compose = None

    def test_compose_file_exists_and_parses(self) -> None:
        """Verify docker-compose.yml exists and contains valid YAML."""
        self.assertIsNotNone(
            self.compose,
            f"Expected {self.compose_path} to exist and parse as valid YAML.",
        )

    def test_required_services_declared(self) -> None:
        """Verify the 4 required microservices are declared and edgeblob is removed."""
        services = self.compose.get("services", {})
        expected_services = {
            "nginx",
            "ingestion-runner",
            "query-engine",
            "streamlit",
        }
        self.assertTrue(
            expected_services.issubset(services.keys()),
            f"Missing services: {expected_services - set(services.keys())}",
        )
        self.assertNotIn(
            "edgeblob",
            services,
            "edgeblob service should be removed in favor of pluggable localfs storage.",
        )

    def test_nginx_service_configuration(self) -> None:
        """Verify Nginx ingress service configuration, ports, and dependencies (INF-02)."""
        nginx = self.compose["services"]["nginx"]
        self.assertEqual(nginx.get("image"), "nginx:alpine")
        ports = nginx.get("ports", [])
        self.assertTrue(any("80:80" in str(p) for p in ports))
        self.assertIn("streamlit", nginx.get("depends_on", []))
        self.assertIn("query-engine", nginx.get("depends_on", []))
        self.assertIn("healthcheck", nginx)

    def test_localfs_storage_configuration(self) -> None:
        """Verify LocalFS storage configuration across services."""
        ingestion = self.compose["services"]["ingestion-runner"]
        query_engine = self.compose["services"]["query-engine"]

        # LocalFS environment flags
        ingestion_env = str(ingestion.get("environment", []))
        self.assertIn("STORAGE_PROVIDER=localfs", ingestion_env)
        self.assertIn("STORAGE_LOCAL_PATH=/data/lake", ingestion_env)

        query_env = str(query_engine.get("environment", []))
        self.assertIn("STORAGE_PROVIDER=localfs", query_env)
        self.assertIn("STORAGE_LOCAL_PATH=/data/lake", query_env)

    def test_persistent_volumes_declared(self) -> None:
        """Verify model_cache named volume is declared and edgeblob_data is removed."""
        volumes = self.compose.get("volumes", {})
        self.assertIn("model_cache", volumes)
        self.assertNotIn("edgeblob_data", volumes)

    def test_query_engine_read_only_lake_mount(self) -> None:
        """Verify Query Engine mounts /data/lake in read-only mode (:ro) for stateless HPA scaling."""
        query_engine = self.compose["services"]["query-engine"]
        volumes = [str(v) for v in query_engine.get("volumes", [])]
        # /data/lake must have :ro flag
        lake_mounts = [v for v in volumes if "data/lake" in v]
        self.assertTrue(len(lake_mounts) > 0, "Expected /data/lake volume mount on query-engine")
        self.assertTrue(any(":ro" in v for v in lake_mounts), "Query engine lake mount must be read-only (:ro)")

    def test_all_services_have_healthchecks(self) -> None:
        """Verify every microservice defines a healthcheck for Docker Compose orchestration."""
        services = self.compose.get("services", {})
        for name, cfg in services.items():
            self.assertIn(
                "healthcheck",
                cfg,
                f"Service '{name}' is missing a healthcheck definition.",
            )


if __name__ == "__main__":
    unittest.main()

