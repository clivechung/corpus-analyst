"""Streamlit Presentation Component for Ingestion Monitor & Manual Trigger (UI-02).

Provides a Bloomberg Terminal / Quant Trading Floor inspired dashboard:
- Ingestion HUD KPI metric tiles
- Order-ticket style SEC EDGAR filing requisition
- OTC / Direct document intake dropzone with SHA-256 validation
- Live pipeline queue telemetry table with search and filtering
- Dead-letter quarantine forensic drawer with one-click retry
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from ui.components.ingestion_service import IngestionService, QueueItem, QueueMetrics


# -----------------------------------------------------------------------------
# KPI Telemetry Strip
# -----------------------------------------------------------------------------


def render_kpi_strip(metrics: QueueMetrics) -> None:
    """Render 4 high-density quant metric cards across the top of the tab."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
            <div class="quant-kpi-card amber">
                <div class="quant-kpi-label">INCOMING QUEUE DEPTH</div>
                <div class="quant-kpi-value">{metrics.incoming_count}</div>
                <div class="quant-kpi-sub">Pending Watchdog Intake</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="quant-kpi-card emerald">
                <div class="quant-kpi-label">SETTLED CORPUS ARCHIVE</div>
                <div class="quant-kpi-value">{metrics.processed_count}</div>
                <div class="quant-kpi-sub">Volume: {metrics.formatted_volume}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""
            <div class="quant-kpi-card crimson">
                <div class="quant-kpi-label">DEAD-LETTER QUARANTINE</div>
                <div class="quant-kpi-value">{metrics.failed_count}</div>
                <div class="quant-kpi-sub">Failure Rate: {metrics.failure_rate_pct:.1f}%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        latest_label = metrics.latest_ingest_time or "No batches yet"
        st.markdown(
            f"""
            <div class="quant-kpi-card cyan">
                <div class="quant-kpi-label">LATEST SETTLEMENT</div>
                <div class="quant-kpi-value" style="font-size: 1.05rem; padding-top: 0.4rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    {latest_label}
                </div>
                <div class="quant-kpi-sub">Hive Partitioned Lake</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# -----------------------------------------------------------------------------
# SEC EDGAR Requisition Ticket Form
# -----------------------------------------------------------------------------


def render_sec_requisition_ticket(service: IngestionService) -> None:
    """Render order-ticket styled SEC requisition interface."""
    st.markdown("#### ⚡ SEC EDGAR REQUISITION TICKET")

    # Quick Ticker Selector Chips
    st.caption("QUICK SELECT QUANT INSTRUMENTS:")
    quick_tickers = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "JPM"]
    cols = st.columns(len(quick_tickers))
    for idx, ticker in enumerate(quick_tickers):
        with cols[idx]:
            if st.button(ticker, key=f"quick_t_{ticker}", use_container_width=True):
                st.session_state["sec_target_ticker"] = ticker

    if "sec_target_ticker" not in st.session_state:
        st.session_state["sec_target_ticker"] = "NVDA"

    # Form parameters
    col_t, col_form, col_preset = st.columns([1.5, 1.5, 2])
    with col_t:
        target_ticker = st.text_input(
            "EQUITY TICKER",
            value=st.session_state["sec_target_ticker"],
            placeholder="e.g. NVDA, AAPL",
            help="Stock ticker symbol for SEC EDGAR CIK resolution.",
        ).strip().upper()

    with col_form:
        form_type = st.selectbox(
            "FILING FORM TYPE",
            options=["10-K", "10-Q", "8-K"],
            index=0,
            help="10-K (Annual), 10-Q (Quarterly), 8-K (Material Event).",
        )

    with col_preset:
        date_preset = st.selectbox(
            "DATE RANGE FILTER",
            options=["Trailing 12M", "Year to Date (YTD)", "Fiscal 2024", "Custom Range"],
            index=0,
        )

    # Date range resolution
    today = date.today()
    if date_preset == "Trailing 12M":
        start_d = today - timedelta(days=365)
        end_d = today
    elif date_preset == "Year to Date (YTD)":
        start_d = date(today.year, 1, 1)
        end_d = today
    elif date_preset == "Fiscal 2024":
        start_d = date(2024, 1, 1)
        end_d = date(2024, 12, 31)
    else:
        col_sd, col_ed = st.columns(2)
        with col_sd:
            start_d = st.date_input("START DATE", value=date(2024, 1, 1))
        with col_ed:
            end_d = st.date_input("END DATE", value=today)

    # SEC User Agent compliance check
    default_ua = (
        os.environ.get("SEC_USER_AGENT")
        or os.environ.get("SEC_EDGAR_USER_AGENT")
        or "CorpusAnalystAdmin admin@corpus-analyst.local"
    )
    with st.expander("⚙️ SEC EDGAR Protocol & Compliance Settings", expanded=False):
        ua_input = st.text_input(
            "SEC User-Agent Header (Required: Name email@domain.com)",
            value=default_ua,
            help="SEC EDGAR Fair Access policy strictly mandates a declared User-Agent with valid email.",
        )
        st.caption("Rate limit: Strictly enforced at $\le 10$ req/s via token-bucket rate limiter.")
        st.caption(r"Rate limit: Strictly enforced at $\le 10$ req/s via token-bucket rate limiter.")

    col_btn, col_info = st.columns([1.5, 3])
    with col_btn:
        exec_btn = st.button("▶ EXECUTE REQUISITION", type="primary", use_container_width=True)

    with col_info:
        st.caption(
            f"Target: **{target_ticker or 'N/A'}** ({form_type}) from `{start_d}` to `{end_d}` $\\to$ `/data/incoming`"
        )

    if exec_btn:
        if not target_ticker:
            st.error("Please provide a valid stock ticker symbol.")
            return

        with st.spinner(f"Querying SEC EDGAR for {target_ticker} {form_type}..."):
            res = service.execute_sec_fetch(
                ticker=target_ticker,
                form_type=form_type,
                start_date=str(start_d),
                end_date=str(end_d),
                user_agent=ua_input,
            )

            if res.get("success"):
                st.success(
                    f"✅ Successfully acquired {target_ticker} {form_type} filing: "
                    f"`{res.get('filename')}` $\\to$ `/data/incoming/`"
                )
                st.info("Watchdog daemon has queued filing for write stability verification.")
                st.rerun()
            else:
                st.error(f"❌ SEC Requisition Failed: {res.get('error')}")


# -----------------------------------------------------------------------------
# OTC / Direct Document Intake Dropzone
# -----------------------------------------------------------------------------


def render_intake_dropzone(service: IngestionService) -> None:
    """Render direct file dropzone for OTC and proprietary research documents."""
    st.markdown("#### 📥 DIRECT DOCUMENT INTAKE DROPBOX")

    uploaded = st.file_uploader(
        "DROP DOCUMENT FILE DIRECTLY INTO PIPELINE (PDF, HTM, HTML, JSON, TXT)",
        type=["pdf", "htm", "html", "json", "txt"],
        key="intake_file_uploader",
    )

    if uploaded:
        file_bytes = uploaded.getvalue()
        sha256_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size_kb = len(file_bytes) / 1024.0

        st.markdown(
            f"""
            <div style="background: #111622; border: 1px solid #1e293b; border-radius: 4px; padding: 0.6rem 1rem; margin-bottom: 0.8rem;">
                <span style="color: #38bdf8; font-weight: 600;">{uploaded.name}</span>
                <span class="quant-badge quant-badge-ticker" style="margin-left: 0.6rem;">{file_size_kb:.1f} KB</span>
                <div style="color: #64748b; font-size: 0.72rem; margin-top: 0.2rem;">
                    SHA-256: <code>{sha256_hash}</code>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_tag_t, col_tag_f, col_tag_d = st.columns(3)
        with col_tag_t:
            tag_ticker = st.text_input("EQUITY TICKER (OPTIONAL)", placeholder="e.g. AAPL").strip().upper()
        with col_tag_f:
            tag_form = st.selectbox("DOCUMENT TYPE", options=["10-K", "10-Q", "8-K", "RESEARCH", "MISC"], index=3)
        with col_tag_d:
            tag_domain = st.selectbox("DOMAIN PROFILE", options=["finance", "literature", "general"], index=0)

        if st.button("📥 INJECT TO INCOMING QUEUE", type="primary"):
            try:
                saved = service.save_uploaded_file(
                    file_name=uploaded.name,
                    file_bytes=file_bytes,
                    ticker=tag_ticker if tag_ticker else None,
                    form_type=tag_form,
                    domain=tag_domain,
                )
                st.success(f"✅ Injected `{uploaded.name}` to incoming drop folder `{saved.parent}`.")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to inject document: {exc}")


# -----------------------------------------------------------------------------
# Pipeline Queue Telemetry Grid
# -----------------------------------------------------------------------------


def render_pipeline_queue_grid(service: IngestionService) -> None:
    """Render real-time queue table with filtering, search, and action triggers."""
    st.markdown("#### 📊 REAL-TIME INGESTION PIPELINE TELEMETRY")

    col_filter, col_search, col_refresh = st.columns([2.5, 3, 1])

    with col_filter:
        status_filter = st.segmented_control(
            "FILTER BY STATUS",
            options=["ALL", "PENDING", "PROCESSED", "FAILED"],
            default="ALL",
            label_visibility="collapsed",
        ) or "ALL"

    with col_search:
        search_query = st.text_input(
            "Search filings...",
            placeholder="Search by ticker, form, or filename...",
            label_visibility="collapsed",
        )

    with col_refresh:
        if st.button("🔄 REFRESH", use_container_width=True):
            st.rerun()

    items = service.scan_queue(status_filter=status_filter, search_query=search_query)

    if not items:
        st.info("No documents currently matching filter criteria.")
        return

    st.caption(f"Showing **{len(items)}** pipeline records in active storage:")

    # Render high-density item rows
    for item in items:
        # Determine status badge class
        if item.status == "PENDING":
            status_badge = '<span class="quant-badge quant-badge-pending">⏳ PENDING</span>'
        elif item.status == "PROCESSED":
            status_badge = '<span class="quant-badge quant-badge-processed">✅ SETTLED</span>'
        else:
            status_badge = '<span class="quant-badge quant-badge-failed">❌ QUARANTINED</span>'

        ticker_pill = (
            f'<span class="quant-badge quant-badge-ticker">{item.ticker}</span>'
            if item.ticker
            else '<span class="quant-badge" style="color:#64748b; border:1px solid #1e293b;">N/A</span>'
        )

        form_pill = (
            f'<span class="quant-badge quant-badge-form">{item.form_type}</span>'
            if item.form_type
            else ""
        )

        row_header = f"{item.filename}  ({item.formatted_size} | {item.formatted_time})"

        with st.expander(f"{item.status} // {item.filename}"):
            col_meta1, col_meta2 = st.columns([3, 1])

            with col_meta1:
                st.markdown(
                    f"""
                    <div style="margin-bottom: 0.6rem;">
                        {status_badge}
                        {ticker_pill}
                        {form_pill}
                        <span style="color: #94a3b8; font-size: 0.8rem; margin-left: 0.6rem;">
                            Size: <code>{item.formatted_size}</code> | Timestamp: <code>{item.formatted_time} UTC</code>
                        </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if item.company_name:
                    st.markdown(f"**Entity Title:** `{item.company_name}`")

                # If failed, show error forensic summary
                if item.status == "FAILED":
                    st.markdown("##### 🚨 Dead-Letter Forensic Trace")
                    dead_letter = service.get_dead_letter_details(item.filename)
                    if dead_letter:
                        st.markdown(f"**Error Type:** `{dead_letter.get('error_type', 'Unknown')}`")
                        st.markdown(f"**Message:** `{dead_letter.get('error_message', 'No details')}`")
                        stack = dead_letter.get("stack_trace")
                        if stack:
                            st.markdown(
                                f'<div class="quant-terminal-box">{stack}</div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("No companion `.error.json` record found.")

                # If has metadata, display sidecar preview
                if item.has_metadata:
                    with st.expander("📑 Companion Metadata Sidecar (.meta.json)"):
                        meta_payload = service.get_metadata_details(item.filename, status=item.status)
                        st.json(meta_payload or {})

            with col_meta2:
                # Actions for failed items
                if item.status == "FAILED":
                    st.markdown("**Quarantine Actions:**")
                    if st.button("↺ RE-QUEUE FILE", key=f"requeue_{item.filename}", use_container_width=True):
                        if service.requeue_failed_file(item.filename):
                            st.success(f"Re-queued `{item.filename}` to incoming drop folder.")
                            st.rerun()
                        else:
                            st.error("Failed to re-queue file.")


# -----------------------------------------------------------------------------
# Main View Entrypoint
# -----------------------------------------------------------------------------


def render_ingestion_monitor_view(service: IngestionService | None = None) -> None:
    """Master presentation coordinator for Tab 2 (Ingestion Monitor)."""
    if service is None:
        service = IngestionService()

    # 1. Telemetry KPI Strip
    metrics = service.get_metrics()
    render_kpi_strip(metrics)
    st.markdown("---")

    # 2. Left / Right Split: SEC Requisition Ticket vs Direct Dropzone
    col_sec, col_drop = st.columns([1.2, 1])

    with col_sec:
        render_sec_requisition_ticket(service)

    with col_drop:
        render_intake_dropzone(service)

    st.markdown("---")

    # 3. Pipeline Queue Data Grid
    render_pipeline_queue_grid(service)
