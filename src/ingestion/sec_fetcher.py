"""SEC EDGAR automated downloader utility for 10-K, 10-Q, and 8-K filings.

Follows TREM-Python principles:
- Testable: Injected httpx.Client, mockable rate limiter, and clean public methods.
- Readable: Fully type-hinted signatures, structured logging, and clear error conditions.
- Extensible: Day-granularity date filtering, multiple filing types, and Typer CLI interface.
- Maintainable: Zero-config User-Agent via SEC_USER_AGENT env var and strict rate-limiting compliance.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import typer

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Domain Exceptions
# -----------------------------------------------------------------------------


class SecApiError(Exception):
    """Base exception for SEC EDGAR API failures."""
    pass


class SecFilingNotFoundError(SecApiError):
    """Raised when requested filing or ticker cannot be found."""
    pass


class SecRateLimitError(SecApiError):
    """Raised when SEC rate limit is exceeded."""
    pass


# -----------------------------------------------------------------------------
# Token-Bucket Rate Limiter
# -----------------------------------------------------------------------------


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter to enforce SEC's <= 10 req/s limit."""

    def __init__(self, rate_per_sec: float = 10.0, capacity: float = 10.0) -> None:
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0, timeout: float = 5.0) -> bool:
        """Acquire tokens, blocking up to timeout if necessary."""
        start_wait = time.monotonic()

        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

                needed = tokens - self.tokens
                sleep_time = needed / self.rate

            if (time.monotonic() - start_wait) + sleep_time > timeout:
                return False

            time.sleep(min(sleep_time, 0.05))


# -----------------------------------------------------------------------------
# SEC Fetcher Client
# -----------------------------------------------------------------------------


class SecFetcher:
    """Downloader client querying SEC EDGAR submissions and primary documents."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        output_dir: str | Path | None = None,
        user_agent: str | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
    ) -> None:
        self.output_dir = Path(output_dir or "./data/incoming")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Injected or resolved User-Agent
        resolved_ua = (
            user_agent
            or os.environ.get("SEC_USER_AGENT")
            or os.environ.get("SEC_EDGAR_USER_AGENT")
        )
        if not resolved_ua:
            raise ValueError(
                "SEC EDGAR requires a compliant User-Agent header. "
                "Provide user_agent parameter or set SEC_USER_AGENT environment variable."
            )

        self.user_agent = self._normalize_user_agent(resolved_ua)

        self.client = client or httpx.Client(timeout=30.0)
        self.limiter = rate_limiter or TokenBucketRateLimiter(rate_per_sec=10.0, capacity=10.0)
        self._cik_cache: dict[str, tuple[str, str]] = {}  # ticker -> (cik_10digit, entity_title)

    @classmethod
    def _normalize_user_agent(cls, ua: str) -> str:
        """Validate and normalize User-Agent to comply with SEC EDGAR formatting: 'Sample Name AdminContact@domain.com'.

        If a bare email address is provided (e.g. 'clive.km.chung@gmail.com'),
        auto-normalizes to 'CorpusAnalyst <email>'.
        """
        clean_ua = ua.strip()
        if not clean_ua:
            raise ValueError(
                "SEC EDGAR requires a compliant User-Agent header. "
                "Provide user_agent parameter or set SEC_USER_AGENT environment variable."
            )
        if "@" not in clean_ua:
            raise ValueError(
                f"Invalid SEC User-Agent format: '{clean_ua}'. "
                "SEC requires an email address in 'Sample Company Name AdminContact@domain.com'."
            )
        parts = clean_ua.split()
        if len(parts) == 1:
            normalized = f"CorpusAnalyst {clean_ua}"
            logger.info("Auto-normalized bare email SEC User-Agent to '%s'", normalized)
            return normalized
        return clean_ua

    @classmethod
    def _validate_user_agent(cls, ua: str) -> None:
        """Validate User-Agent format."""
        cls._normalize_user_agent(ua)

    def _headers(self) -> dict[str, str]:
        """SEC EDGAR compliant HTTP headers."""
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        }

    def _get(self, url: str, host: str = "data.sec.gov") -> httpx.Response:
        """Make rate-limited HTTP GET request with retry backoff for 429s."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": host,
        }

        for attempt in range(3):
            if not self.limiter.acquire(timeout=5.0):
                raise SecRateLimitError("Timed out waiting for SEC rate limiter token")

            resp = self.client.get(url, headers=headers)
            if resp.status_code == 429:
                backoff = (2 ** attempt) * 0.5
                logger.warning("Received 429 from SEC EDGAR. Backing off for %.2fs...", backoff)
                time.sleep(backoff)
                continue

            return resp

        raise SecRateLimitError("SEC EDGAR rate limit exceeded after maximum retries.")

    def get_cik_by_ticker(self, ticker: str) -> str:
        """Resolve a stock ticker symbol to a 10-digit zero-padded SEC CIK string."""
        clean_ticker = ticker.strip().upper()
        if clean_ticker in self._cik_cache:
            return self._cik_cache[clean_ticker][0]

        logger.info("Fetching SEC company tickers index...")
        resp = self._get("https://www.sec.gov/files/company_tickers.json", host="www.sec.gov")
        if resp.status_code != 200:
            raise SecApiError(f"Failed to fetch SEC tickers index: HTTP {resp.status_code}")

        data = resp.json()
        for item in data.values():
            t = str(item.get("ticker", "")).strip().upper()
            cik = str(item.get("cik_str", "")).zfill(10)
            title = str(item.get("title", ""))
            self._cik_cache[t] = (cik, title)

        if clean_ticker not in self._cik_cache:
            raise SecFilingNotFoundError(f"Ticker '{clean_ticker}' not found in SEC company index.")

        return self._cik_cache[clean_ticker][0]

    def get_recent_filings(
        self,
        ticker: str,
        form_type: str = "10-K",
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        year: int | None = None,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        """Query filings for ticker and filter by form type and day-granularity date range."""
        clean_ticker = ticker.strip().upper()
        cik = self.get_cik_by_ticker(clean_ticker)
        company_name = self._cik_cache.get(clean_ticker, ("", clean_ticker))[1]

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = self._get(url, host="data.sec.gov")
        if resp.status_code != 200:
            raise SecApiError(f"Failed to fetch submissions for CIK {cik}: HTTP {resp.status_code}")

        submissions = resp.json()
        recent = submissions.get("filings", {}).get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        # Normalize filter boundaries
        start_str = str(start_date) if start_date else None
        end_str = str(end_date) if end_date else None
        year_str = str(year) if year else None
        form_target = form_type.strip().upper()

        matches: list[dict[str, Any]] = []
        for i, form_val in enumerate(forms):
            if form_val.strip().upper() != form_target:
                continue

            f_date = filing_dates[i] if i < len(filing_dates) else ""
            r_date = report_dates[i] if i < len(report_dates) else ""

            # Filter by fiscal year if specified
            if year_str and not (f_date.startswith(year_str) or r_date.startswith(year_str)):
                continue

            # Filter by day granularity start_date (inclusive)
            if start_str and f_date < start_str:
                continue

            # Filter by day granularity end_date (inclusive)
            if end_str and f_date > end_str:
                continue

            matches.append({
                "ticker": clean_ticker,
                "company_name": company_name,
                "cik": cik,
                "form": form_val,
                "filingDate": f_date,
                "reportDate": r_date,
                "accessionNumber": accessions[i] if i < len(accessions) else "",
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
            })

            if len(matches) >= limit:
                break

        return matches

    def download_filing(
        self,
        ticker: str,
        form_type: str = "10-K",
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        year: int | None = None,
    ) -> Path:
        """Download the most recent matching filing document and emit companion .meta.json sidecar."""
        matches = self.get_recent_filings(
            ticker=ticker,
            form_type=form_type,
            start_date=start_date,
            end_date=end_date,
            year=year,
            limit=1,
        )

        if not matches:
            date_filter_desc = f" [{start_date or '*'} to {end_date or '*'}]" if (start_date or end_date) else ""
            raise SecFilingNotFoundError(
                f"No matching {form_type} filings found for ticker '{ticker}'{date_filter_desc}"
            )

        filing = matches[0]
        cik_int = str(int(filing["cik"]))
        accession_clean = filing["accessionNumber"].replace("-", "")
        primary_doc = filing["primaryDocument"]

        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{primary_doc}"
        logger.info("Downloading primary document from: %s", doc_url)

        resp = self._get(doc_url, host="www.sec.gov")
        if resp.status_code != 200:
            raise SecApiError(f"Failed to download document at {doc_url}: HTTP {resp.status_code}")

        # Construct target filename: e.g. NVDA_10-K_20240221.htm
        clean_ext = Path(primary_doc).suffix or ".htm"
        date_stamp = filing["filingDate"].replace("-", "")
        clean_ticker = filing["ticker"]
        clean_form = filing["form"].replace("/", "-")
        target_filename = f"{clean_ticker}_{clean_form}_{date_stamp}{clean_ext}"
        target_path = self.output_dir / target_filename

        with open(target_path, "wb") as f:
            f.write(resp.content)

        # Write companion metadata sidecar (.meta.json)
        sidecar_path = target_path.with_name(f"{target_path.name}.meta.json")
        meta_payload = {
            "doc_id": filing["accessionNumber"],
            "source_filename": target_filename,
            "domain": "finance",
            "form_type": filing["form"],
            "filing_date": filing["filingDate"],
            "company_name": filing["company_name"],
            "ticker": clean_ticker,
            "extra": {
                "cik": filing["cik"],
                "report_date": filing["reportDate"],
                "accession_number": filing["accessionNumber"],
                "primary_document": primary_doc,
            },
        }

        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(meta_payload, f, indent=2)

        logger.info(
            "Saved filing document to %s and companion metadata to %s",
            target_path,
            sidecar_path,
        )
        return target_path


# -----------------------------------------------------------------------------
# CLI Entrypoint (Typer)
# -----------------------------------------------------------------------------

app = typer.Typer(help="SEC EDGAR Document Downloader Utility")


@app.command()
def fetch(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Stock ticker symbol (e.g. NVDA, AAPL)"),
    form: str = typer.Option("10-K", "--form", "-f", help="Filing form type (10-K, 10-Q, 8-K)"),
    start_date: str = typer.Option(None, "--start-date", "-s", help="Start date (inclusive, YYYY-MM-DD)"),
    end_date: str = typer.Option(None, "--end-date", "-e", help="End date (inclusive, YYYY-MM-DD)"),
    year: int = typer.Option(None, "--year", "-y", help="Fiscal year filter"),
    limit: int = typer.Option(1, "--limit", "-l", help="Maximum filings to download"),
    output_dir: str = typer.Option("./data/incoming", "--output-dir", "-o", help="Target download directory"),
    user_agent: str = typer.Option(None, "--user-agent", "-u", help="SEC User-Agent header string"),
) -> None:
    """Fetch SEC EDGAR filings directly into the incoming ingestion staging directory."""
    try:
        fetcher = SecFetcher(output_dir=output_dir, user_agent=user_agent)
        result_path = fetcher.download_filing(
            ticker=ticker,
            form_type=form,
            start_date=start_date,
            end_date=end_date,
            year=year,
        )
        typer.echo(f"Successfully downloaded filing to: {result_path}")
    except Exception as exc:
        typer.secho(f"Error fetching SEC filing: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

