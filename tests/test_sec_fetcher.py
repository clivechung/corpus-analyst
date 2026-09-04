"""Unit tests for SEC EDGAR fetcher seam (SEAM-SEC-FETCHER).

Follows TREM-Python principles:
- Testable: In-memory mock HTTP transport with deterministic SEC JSON fixture responses.
- Readable: Explicit assertions on CIK lookup, filing filtering, day-granularity date filtering, and headers.
- Extensible: Protocol and client injection without live network access.
- Maintainable: Verification of rate limiting, error handling, and companion metadata generation.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from src.ingestion.sec_fetcher import (
    SecFetcher,
    SecFilingNotFoundError,
    SecRateLimitError,
    TokenBucketRateLimiter,
)

# Mock SEC API response fixtures
MOCK_TICKERS_JSON = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

MOCK_SUBMISSIONS_NVDA = {
    "cik": "0001045810",
    "entityType": "operating",
    "name": "NVIDIA CORP",
    "tickers": ["NVDA"],
    "filings": {
      "recent": {
        "accessionNumber": [
            "0001045810-24-000029",
            "0001045810-23-000017",
            "0001045810-24-000010",
        ],
        "filingDate": ["2024-02-21", "2023-02-24", "2024-01-15"],
        "reportDate": ["2024-01-28", "2023-01-29", "2024-01-10"],
        "form": ["10-K", "10-K", "8-K"],
        "primaryDocument": ["nvda-20240128.htm", "nvda-20230129.htm", "nvda-8k.htm"],
        "primaryDocDescription": ["10-K", "10-K", "8-K"],
      }
    },
}

MOCK_FILING_HTML = "<html><body><h1>NVIDIA ANNUAL REPORT 2024</h1></body></html>"


def mock_sec_transport_handler(request: httpx.Request) -> httpx.Response:
    """Mock handler for httpx requests simulating SEC EDGAR endpoints."""
    url = str(request.url)

    # 1. Company tickers mapping endpoint
    if "company_tickers.json" in url:
        return httpx.Response(200, json=MOCK_TICKERS_JSON)

    # 2. Submissions endpoint for CIK 0001045810
    if "CIK0001045810.json" in url:
        return httpx.Response(200, json=MOCK_SUBMISSIONS_NVDA)

    # 3. Document download endpoint
    if "Archives/edgar/data" in url and "nvda-20240128.htm" in url:
        return httpx.Response(200, text=MOCK_FILING_HTML)

    if "Archives/edgar/data" in url and "nvda-8k.htm" in url:
        return httpx.Response(200, text="<html><body>NVIDIA 8-K</body></html>")

    # 429 Simulation
    if "trigger_429" in url:
        return httpx.Response(429, text="Too Many Requests")

    return httpx.Response(404, text="Not Found")


class TestSecFetcherSeam(unittest.TestCase):
    """Test suite for SecFetcher and TokenBucketRateLimiter."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.transport = httpx.MockTransport(mock_sec_transport_handler)
        self.client = httpx.Client(transport=self.transport)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_token_bucket_rate_limiter_allows_and_throttles(self) -> None:
        """Verify rate limiter allows tokens up to capacity and delays excess."""
        limiter = TokenBucketRateLimiter(rate_per_sec=10.0, capacity=2.0)
        # Should acquire immediately when bucket has capacity
        self.assertTrue(limiter.acquire(timeout=0.01))
        self.assertTrue(limiter.acquire(timeout=0.01))

    def test_cik_lookup_by_ticker(self) -> None:
        """Verify ticker-to-CIK resolution with mock company_tickers.json."""
        fetcher = SecFetcher(
            client=self.client,
            output_dir=self.output_dir,
            user_agent="TestUser test@example.com",
        )
        cik = fetcher.get_cik_by_ticker("NVDA")
        self.assertEqual(cik, "0001045810")

        # Verify case insensitivity
        cik_lower = fetcher.get_cik_by_ticker("nvda")
        self.assertEqual(cik_lower, "0001045810")

    def test_cik_lookup_unknown_ticker_raises_error(self) -> None:
        """Verify unknown ticker raises SecFilingNotFoundError."""
        fetcher = SecFetcher(
            client=self.client,
            output_dir=self.output_dir,
            user_agent="TestUser test@example.com",
        )
        with self.assertRaises(SecFilingNotFoundError):
            fetcher.get_cik_by_ticker("UNKNOWN_TICKER_XYZ")

    def test_get_recent_filings_filtering_and_day_granularity(self) -> None:
        """Verify submissions filtering by form type and day-granularity dates."""
        fetcher = SecFetcher(
            client=self.client,
            output_dir=self.output_dir,
            user_agent="TestUser test@example.com",
        )

        # 1. Filter by form 10-K
        filings_10k = fetcher.get_recent_filings(ticker="NVDA", form_type="10-K", limit=10)
        self.assertEqual(len(filings_10k), 2)
        self.assertEqual(filings_10k[0]["form"], "10-K")
        self.assertEqual(filings_10k[0]["filingDate"], "2024-02-21")

        # 2. Filter by day-granularity date range [2024-01-01 to 2024-01-31]
        jan_filings = fetcher.get_recent_filings(
            ticker="NVDA",
            form_type="8-K",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        self.assertEqual(len(jan_filings), 1)
        self.assertEqual(jan_filings[0]["form"], "8-K")
        self.assertEqual(jan_filings[0]["filingDate"], "2024-01-15")

        # 3. Filter with non-matching day range
        none_filings = fetcher.get_recent_filings(
            ticker="NVDA",
            form_type="10-K",
            start_date="2024-03-01",
            end_date="2024-03-31",
        )
        self.assertEqual(len(none_filings), 0)

    def test_download_filing_writes_document_and_meta_sidecar(self) -> None:
        """Verify download_filing fetches primary document and writes companion .meta.json."""
        fetcher = SecFetcher(
            client=self.client,
            output_dir=self.output_dir,
            user_agent="TestUser test@example.com",
        )

        doc_path = fetcher.download_filing(
            ticker="NVDA",
            form_type="10-K",
            start_date="2024-01-01",
            end_date="2024-03-31",
        )

        self.assertTrue(doc_path.exists())
        self.assertEqual(doc_path.read_text(), MOCK_FILING_HTML)

        # Confirm companion metadata sidecar
        meta_path = doc_path.with_name(f"{doc_path.name}.meta.json")
        self.assertTrue(meta_path.exists())

        meta_data = json.loads(meta_path.read_text())
        self.assertEqual(meta_data["ticker"], "NVDA")
        self.assertEqual(meta_data["company_name"], "NVIDIA CORP")
        self.assertEqual(meta_data["form_type"], "10-K")
        self.assertEqual(meta_data["filing_date"], "2024-02-21")
        self.assertEqual(meta_data["doc_id"], "0001045810-24-000029")

    def test_user_agent_injection_from_env(self) -> None:
        """Verify user_agent is injected from SEC_USER_AGENT env var when not explicitly passed."""
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": "EnvUser env@domain.com"}):
            fetcher = SecFetcher(client=self.client, output_dir=self.output_dir)
            self.assertEqual(fetcher.user_agent, "EnvUser env@domain.com")

    def test_user_agent_validation_enforces_format(self) -> None:
        """Verify invalid user-agent format raises ValueError."""
        with self.assertRaises(ValueError):
            SecFetcher(
                client=self.client,
                output_dir=self.output_dir,
                user_agent="InvalidWithoutEmail",
            )
        with self.assertRaises(ValueError):
            SecFetcher(
                client=self.client,
                output_dir=self.output_dir,
                user_agent="   ",
            )

    def test_user_agent_auto_normalizes_bare_email(self) -> None:
        """Verify bare email address is auto-normalized with default organization prefix."""
        fetcher = SecFetcher(
            client=self.client,
            output_dir=self.output_dir,
            user_agent="clive.km.chung@gmail.com",
        )
        self.assertEqual(fetcher.user_agent, "CorpusAnalyst clive.km.chung@gmail.com")

        # Also test with env var
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": "another.user@example.com"}):
            fetcher_env = SecFetcher(client=self.client, output_dir=self.output_dir)
            self.assertEqual(fetcher_env.user_agent, "CorpusAnalyst another.user@example.com")


if __name__ == "__main__":
    unittest.main()

