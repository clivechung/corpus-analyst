"""Corpus Analyst Streamlit Research Dashboard UI.

Provides interactive document analysis, chat with citations, ingestion monitoring,
and lakehouse partition exploration.
"""

from __future__ import annotations

import os
import json
import logging
import httpx
import streamlit as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("corpus_analyst_ui")

# Page Configuration
st.set_page_config(
    page_title="Corpus Analyst — Multi-Domain RAG Platform",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

QUERY_ENGINE_URL = os.getenv("QUERY_ENGINE_URL", "http://query-engine:8000").rstrip("/")


def check_query_engine_health() -> dict[str, str]:
    """Check connectivity to Query Engine API."""
    try:
        resp = httpx.get(f"{QUERY_ENGINE_URL}/api/v1/health", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.debug("Query engine health check failed: %s", exc)
    return {"status": "unavailable", "service": "query-engine"}


# Sidebar
with st.sidebar:
    st.title("⚙️ Platform Control")
    domain_choice = st.selectbox(
        "Corpus Domain Profile",
        options=["finance", "literature", "general"],
        index=0,
        help="Select active domain profile for embedding and retrieval.",
    )
    st.markdown("---")

    health_info = check_query_engine_health()
    if health_info.get("status") == "ok":
        st.success(f"🟢 Query Engine: **Online** ({health_info.get('environment', 'dev')})")
    else:
        st.warning("🟡 Query Engine: **Connecting...**")

    st.markdown("---")
    st.caption("Corpus Analyst RAG Platform v0.1.0 (Phase 2 Topology)")

# Main Header
st.title("📚 Corpus Analyst — Research Assistant")
st.markdown("Zero-VectorDB Data Lakehouse with DuckDB, Azurite / Edge Blob, and Multi-Domain RAG.")

# Tabs
tab_chat, tab_ingest, tab_lake, tab_settings = st.tabs(
    ["💬 Research Chat", "📥 Ingestion Monitor", "🗄️ Lakehouse Explorer", "🔧 System Settings"]
)

with tab_chat:
    st.subheader("Financial & Document Research Assistant")
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

with tab_ingest:
    st.subheader("Incoming Documents & Queue Status")
    st.info("Incoming directory: `/data/incoming`. Automated file watchdog daemon active.")
    uploaded_file = st.file_uploader(
        "Upload document directly to incoming drop folder",
        type=["pdf", "htm", "html", "json"],
    )
    if uploaded_file:
        save_path = Path("/data/incoming") / uploaded_file.name
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success(f"Saved {uploaded_file.name} to {save_path} for ingestion.")
        except Exception as exc:
            st.warning(f"Could not save file to host path: {exc}")

with tab_lake:
    st.subheader("Hive Parquet Lakehouse Explorer")
    st.caption("Partition hierarchy: `/data/lake/domain={domain}/year={YYYY}/month={MM}/day={DD}/*.parquet`")
    lake_dir = Path("/data/lake")
    if lake_dir.exists():
        partitions = list(lake_dir.glob("**/*.parquet"))
        st.metric("Total Parquet Files", len(partitions))
    else:
        st.caption("Lakehouse path not mounted or empty.")

with tab_settings:
    st.subheader("Environment & Model Profiles")
    st.json({
        "query_engine_url": QUERY_ENGINE_URL,
        "active_domain": domain_choice,
        "phase": "Phase 2 (Basic Services in Compose)",
    })

