"""Corpus Analyst Streamlit Research Dashboard UI (Quant Trading Floor Edition).

Provides interactive document analysis, chat with citations, ingestion monitoring,
and lakehouse partition exploration.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
import streamlit as st

from ui.components.ingestion_view import render_ingestion_monitor_view
from ui.components.quant_theme import (
    inject_quant_theme,
    render_trading_floor_header,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("corpus_analyst_ui")

# Page Configuration
st.set_page_config(
    page_title="Corpus Analyst // Trading Floor Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject Bloomberg / Refinitiv inspired Quant Trading Floor theme
inject_quant_theme()

QUERY_ENGINE_URL = os.getenv("QUERY_ENGINE_URL", "http://query-engine:8000").rstrip("/")
DATA_INCOMING_PATH = os.getenv("DATA_INCOMING_PATH", "/data/incoming")


def check_query_engine_health() -> dict[str, str]:
    """Check connectivity to Query Engine API."""
    try:
        resp = httpx.get(f"{QUERY_ENGINE_URL}/api/v1/health", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.debug("Query engine health check failed: %s", exc)
    return {"status": "unavailable", "service": "query-engine"}


def check_ingestion_daemon_health() -> bool:
    """Check if ingestion incoming directory is mounted and accessible."""
    try:
        p = Path(DATA_INCOMING_PATH)
        return p.is_dir() and os.access(str(p), os.R_OK | os.W_OK)
    except Exception:
        return False


# Check service states
health_info = check_query_engine_health()
qe_online = health_info.get("status") == "ok"
daemon_online = check_ingestion_daemon_health()

# Sidebar: Platform & Portfolio Control
with st.sidebar:
    st.markdown("### ⚙️ TERMINAL CONTROLS")
    domain_choice = st.selectbox(
        "Corpus Domain Profile",
        options=["finance", "literature", "general"],
        index=0,
        help="Select active domain profile for embedding model selection and partition pruning.",
    )
    st.markdown("---")

    st.markdown("### 📡 MESH TELEMETRY")
    if qe_online:
        st.success(f"🟢 Query Engine: **Online** ({health_info.get('environment', 'dev')})")
    else:
        st.warning("🟡 Query Engine: **Connecting...**")

    if daemon_online:
        st.success("🟢 Ingestion Daemon: **Active**")
    else:
        st.error("🔴 Ingestion Daemon: **Offline**")

    st.markdown("---")
    st.caption("Corpus Analyst Platform // Phase 3 (Ingest Path UI-02)")

# Top Trading Floor Terminal Header Bar
render_trading_floor_header(
    query_engine_online=qe_online,
    daemon_online=daemon_online,
    active_domain=domain_choice,
)

# Tabs
tab_ingest, tab_chat, tab_lake, tab_settings = st.tabs(
    [
        "📥 INGESTION MONITOR (UI-02)",
        "💬 RESEARCH CHAT",
        "🗄️ LAKEHOUSE EXPLORER",
        "🔧 SYSTEM TELEMETRY",
    ]
)

# TAB 1: Document Ingestion Monitor & SEC Trigger (UI-02)
with tab_ingest:
    render_ingestion_monitor_view()

# TAB 2: Research Chat
with tab_chat:
    st.subheader("Financial & Document Research Assistant")
    st.caption("DuckDB in-process vector scan over Parquet data lake with citation attribution.")

    user_query = st.text_input(
        "Enter research question or filing query:",
        placeholder="e.g. What were NVIDIA's Data Center revenue figures for fiscal 2024?",
    )
    col_submit, col_topk = st.columns([1, 4])
    with col_submit:
        run_query = st.button("Search & Synthesize", type="primary")

    if run_query and user_query:
        with st.spinner("Querying lakehouse..."):
            try:
                payload = {
                    "question": user_query,
                    "domain": domain_choice,
                    "top_k": 5,
                    "similarity_threshold": 0.0,
                }
                resp = httpx.post(f"{QUERY_ENGINE_URL}/api/v1/query", json=payload, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    st.markdown("### Answer")
                    st.info(data.get("answer", "No answer generated."))

                    citations = data.get("citations", [])
                    if citations:
                        st.markdown("### 📑 Citations")
                        for idx, cit in enumerate(citations, 1):
                            with st.expander(f"Citation {idx}: {cit.get('source_filename', 'Unknown')}"):
                                st.markdown(f"**Section:** {cit.get('section', 'N/A')}")
                                st.markdown(f"**Similarity Score:** `{cit.get('similarity_score', 0.0):.4f}`")
                                st.markdown(f"> {cit.get('excerpt', '')}")
                    else:
                        st.caption("No citations returned in current phase.")
                else:
                    st.error(f"Query Engine error ({resp.status_code}): {resp.text}")
            except Exception as exc:
                st.error(f"Failed to communicate with Query Engine: {exc}")

# TAB 3: Lakehouse Explorer
with tab_lake:
    st.subheader("Hive Parquet Lakehouse Explorer")
    st.caption("Partition hierarchy: `/data/lake/domain={domain}/year={YYYY}/month={MM}/day={DD}/*.parquet`")
    lake_dir = Path(os.getenv("DATA_LAKE_PATH", "/data/lake"))
    if lake_dir.exists():
        partitions = list(lake_dir.glob("**/*.parquet"))
        st.metric("Total Parquet Files", len(partitions))
    else:
        st.caption("Lakehouse path not mounted or empty.")

# TAB 4: System Settings & Telemetry
with tab_settings:
    st.subheader("Environment & Model Profiles")
    st.json({
        "query_engine_url": QUERY_ENGINE_URL,
        "incoming_path": DATA_INCOMING_PATH,
        "active_domain": domain_choice,
        "phase": "Phase 3 (UI-02 Document Ingestion Monitor & Manual Trigger)",
        "theme": "Quant Trading Floor (Obsidian & Amber)",
    })
