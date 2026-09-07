"""Corpus Analyst Streamlit Research Dashboard UI (Quant Trading Floor Edition).

Provides interactive document analysis, research chat with citations (UI-01),
ingestion monitoring (UI-02), lakehouse partition exploration & DuckDB SQL console (UI-03),
and dynamic domain & retrieval parameter controls (UI-04).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
import streamlit as st

from ui.components.chat import render_research_chat_view
from ui.components.ingestion_view import render_ingestion_monitor_view
from ui.components.lake_explorer import render_lakehouse_explorer_view
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
DATA_LAKE_PATH = os.getenv("DATA_LAKE_PATH", "/data/lake")


def check_query_engine_health() -> dict[str, Any]:
    """Check connectivity and lake status from Query Engine API."""
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

# Sidebar: Platform & Portfolio Control (UI-04)
with st.sidebar:
    st.markdown("### ⚙️ TERMINAL CONTROLS")
    domain_choice = st.selectbox(
        "Corpus Domain Profile",
        options=["finance", "literature", "general"],
        index=0,
        help="Select active domain profile for embedding model selection and partition pruning.",
    )

    with st.expander("🎯 RETRIEVAL PREDICATES (UI-04)", expanded=True):
        top_k_val = st.slider("Candidate Chunks (Top-K)", min_value=1, max_value=50, value=5)
        sim_threshold = st.slider("Cosine Similarity Cutoff", min_value=0.0, max_value=1.0, value=0.0, step=0.05)
        form_filter = st.selectbox(
            "Form Type Filter",
            options=["All", "10-K", "10-Q", "8-K", "BOOK", "MISC"],
            index=0,
        )
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            start_date_val = st.date_input("Filed From", value=None)
        with col_d2:
            end_date_val = st.date_input("Filed To", value=None)
        is_table_val = st.checkbox("Tabular Chunks Only", value=False)

    st.markdown("---")

    st.markdown("### 📡 MESH TELEMETRY")
    if qe_online:
        total_files = health_info.get("total_parquet_files", 0)
        st.success(f"🟢 Query Engine: **Online** ({total_files} Parquet files)")
    else:
        st.warning("🟡 Query Engine: **Connecting...**")

    if daemon_online:
        st.success("🟢 Ingestion Daemon: **Active**")
    else:
        st.error("🔴 Ingestion Daemon: **Offline**")

    st.markdown("---")
    st.caption("Corpus Analyst Platform // Phase 6 (Stateless Vector Lakehouse)")

query_params = {
    "top_k": top_k_val,
    "similarity_threshold": sim_threshold,
    "form_type": None if form_filter == "All" else form_filter,
    "start_date": start_date_val,
    "end_date": end_date_val,
    "is_table_only": is_table_val,
}

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
        "💬 RESEARCH CHAT (UI-01)",
        "🗄️ LAKEHOUSE EXPLORER (UI-03)",
        "🔧 SYSTEM TELEMETRY",
    ]
)

# TAB 1: Document Ingestion Monitor & SEC Trigger (UI-02)
with tab_ingest:
    render_ingestion_monitor_view()

# TAB 2: Research Chat with Citations (UI-01)
with tab_chat:
    render_research_chat_view(
        query_engine_url=QUERY_ENGINE_URL,
        active_domain=domain_choice,
        query_params=query_params,
    )

# TAB 3: Lakehouse Parquet Explorer & SQL Console (UI-03)
with tab_lake:
    render_lakehouse_explorer_view(
        lake_path=DATA_LAKE_PATH,
        query_engine_url=QUERY_ENGINE_URL,
    )

# TAB 4: System Settings & Telemetry
with tab_settings:
    st.subheader("Environment & Model Profiles")
    st.json(
        {
            "query_engine_url": QUERY_ENGINE_URL,
            "incoming_path": DATA_INCOMING_PATH,
            "lake_path": DATA_LAKE_PATH,
            "active_domain": domain_choice,
            "active_retrieval_params": {
                "top_k": top_k_val,
                "similarity_threshold": sim_threshold,
                "form_type": form_filter,
                "is_table_only": is_table_val,
            },
            "phase": "Phase 6 (DuckDB Vector Search, Pruning, REST API & Quant UI)",
            "theme": "Quant Trading Floor (Obsidian & Amber)",
        }
    )
