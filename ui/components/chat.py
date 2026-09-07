"""Streamlit Presentation Component for Research Chat & Citation Cards (UI-01).

Follows TREM-Python principles:
- Testable: Pure formatting helpers (format_similarity_badge, format_table_badge) and
  decoupled API query executor (execute_chat_query).
- Readable: Descriptive variable naming, type annotations, and structured layout.
- Extensible: Expandable citation cards with metadata drawers and copy-ready excerpts.
- Maintainable: Quant trading floor styling integration with resilient error handling.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]

logger = logging.getLogger("corpus_analyst_ui.chat")


# -----------------------------------------------------------------------------
# Pure Formatting Helpers (TREM: Testable)
# -----------------------------------------------------------------------------


def format_similarity_badge(score: float) -> str:
    """Format similarity score into a color-coded quant badge HTML snippet.

    Scores >= 0.80 -> Emerald green (high relevance)
    Scores >= 0.60 -> Amber gold (moderate relevance)
    Scores < 0.60  -> Slate gray (low relevance)
    """
    pct = round(score * 100.0, 1)
    if score >= 0.80:
        color = "#10b981"
        bg = "rgba(16, 185, 129, 0.15)"
        border = "rgba(16, 185, 129, 0.3)"
    elif score >= 0.60:
        color = "#f59e0b"
        bg = "rgba(245, 158, 11, 0.15)"
        border = "rgba(245, 158, 11, 0.3)"
    else:
        color = "#94a3b8"
        bg = "rgba(148, 163, 184, 0.15)"
        border = "rgba(148, 163, 184, 0.3)"

    return (
        f'<span style="background-color: {bg}; color: {color}; border: 1px solid {border}; '
        f'padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.82rem;">'
        f'SIMILARITY: {pct:.1f}% ({score:.4f})</span>'
    )


def format_table_badge(is_table: bool) -> str:
    """Format tabular indicator badge HTML snippet."""
    if is_table:
        return (
            '<span style="background-color: rgba(6, 182, 212, 0.15); color: #06b6d4; '
            'border: 1px solid rgba(6, 182, 212, 0.3); padding: 2px 8px; border-radius: 4px; '
            'font-weight: 600; font-size: 0.82rem;">📊 TABULAR DATA</span>'
        )
    return (
        '<span style="background-color: rgba(148, 163, 184, 0.1); color: #94a3b8; '
        'border: 1px solid rgba(148, 163, 184, 0.2); padding: 2px 8px; border-radius: 4px; '
        'font-weight: 500; font-size: 0.82rem;">📄 PROSE TEXT</span>'
    )


# -----------------------------------------------------------------------------
# HTTP Dispatch Helper (TREM: Testable)
# -----------------------------------------------------------------------------


def execute_chat_query(
    query_engine_url: str,
    payload: dict[str, Any],
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Dispatch query request to Query Engine API and return JSON response dictionary."""
    url = f"{query_engine_url.rstrip('/')}/api/v1/query"
    try:
        response = httpx.post(url, json=payload, timeout=timeout_seconds)
        if response.status_code == 200:
            return response.json()
        return {
            "error": True,
            "status_code": response.status_code,
            "message": f"Query Engine error ({response.status_code}): {response.text}",
        }
    except Exception as exc:
        logger.error("Failed to communicate with Query Engine at %s: %s", url, exc)
        return {
            "error": True,
            "status_code": 0,
            "message": f"Query Engine connection failure: {exc}",
        }


# -----------------------------------------------------------------------------
# Streamlit Presentation Component (UI-01)
# -----------------------------------------------------------------------------


def render_research_chat_view(
    query_engine_url: str,
    active_domain: str = "finance",
    query_params: dict[str, Any] | None = None,
) -> None:
    """Render interactive research chat view with expandable citation cards."""
    params = query_params or {}

    st.subheader("💬 Financial & Corpus Research Assistant")
    st.caption(
        f"Stateless DuckDB vector search over Parquet lake with grounded citations. Active domain: `{active_domain}`."
    )

    # Quick prompt suggestion chips
    st.markdown("##### 💡 QUANT PROMPT SHORTCUTS")
    quick_queries = [
        "What were NVIDIA's Data Center revenue figures for fiscal 2024?",
        "Summarize Item 1A Risk Factors related to supply chain and geopolitics.",
        "Compare AWS segment sales growth and operating margins.",
    ]
    cols = st.columns(len(quick_queries))
    for idx, prompt_text in enumerate(quick_queries):
        with cols[idx]:
            if st.button(f"⚡ {prompt_text[:38]}...", key=f"quick_prompt_{idx}", use_container_width=True):
                st.session_state["chat_query_input"] = prompt_text

    # Query Input Box
    current_input = st.session_state.get("chat_query_input", "")
    user_query = st.text_input(
        "Enter research inquiry or filing question:",
        value=current_input,
        placeholder="e.g. What was the net income expansion rate?",
        key="main_chat_text_input",
    )

    col_run, col_clear = st.columns([1, 5])
    with col_run:
        submit_query = st.button("🚀 Search & Synthesize", type="primary", use_container_width=True)

    if submit_query and user_query:
        # Build API payload merging user query with active sidebar controls (UI-04)
        payload = {
            "question": user_query,
            "domain": active_domain,
            "top_k": params.get("top_k", 5),
            "similarity_threshold": params.get("similarity_threshold", 0.0),
            "form_type": params.get("form_type"),
            "start_date": params.get("start_date"),
            "end_date": params.get("end_date"),
            "is_table_only": params.get("is_table_only", False),
        }

        # Format dates to ISO strings if provided as date objects
        if isinstance(payload.get("start_date"), date):
            payload["start_date"] = payload["start_date"].isoformat()
        if isinstance(payload.get("end_date"), date):
            payload["end_date"] = payload["end_date"].isoformat()

        with st.spinner("Executing DuckDB SIMD vector scan over Parquet lakehouse..."):
            result = execute_chat_query(query_engine_url, payload)

        if result.get("error"):
            st.error(result.get("message", "Unknown query engine error."))
            return

        # Render Response Telemetry
        latency = result.get("latency_ms", 0.0)
        model_used = result.get("model_used", "duckdb-vector")
        st.markdown(
            f"""
            <div style="display: flex; gap: 1rem; align-items: center; margin-top: 0.5rem; margin-bottom: 1rem;">
                <span class="quant-badge cyan">⚡ LATENCY: {latency:.1f} ms</span>
                <span class="quant-badge amber">🧠 ENGINE: {model_used}</span>
                <span class="quant-badge emerald">📚 CHUNKS: {len(result.get('retrieved_chunks', []))}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Render Grounded Answer
        st.markdown("### 📝 Grounded Synthesis")
        st.info(result.get("answer", "No synthesis generated."))

        # Render Expandable Citation Cards (UI-01)
        citations = result.get("citations", [])
        chunks = result.get("retrieved_chunks", [])
        chunks_by_id = {c.get("chunk_id"): c for c in chunks if isinstance(c, dict)}

        if citations:
            st.markdown(f"### 📑 Grounded Citations ({len(citations)})")
            for idx, cit in enumerate(citations, 1):
                chunk_id = cit.get("chunk_id", "")
                chunk_data = chunks_by_id.get(chunk_id, {})
                score = cit.get("similarity_score", 0.0)
                is_table = chunk_data.get("is_table", False)
                form_type = chunk_data.get("form_type", "N/A")
                filing_date = chunk_data.get("filing_date", "N/A")
                source_file = cit.get("source_filename", "Unknown")
                section = cit.get("section", "General")

                badge_sim = format_similarity_badge(score)
                badge_tbl = format_table_badge(is_table)

                expander_title = f"Citation #{idx} // {source_file} — {section}"
                with st.expander(expander_title, expanded=(idx == 1)):
                    # Header badges
                    st.markdown(
                        f"""
                        <div style="display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.8rem; flex-wrap: wrap;">
                            {badge_sim}
                            {badge_tbl}
                            <span class="quant-badge amber">FORM: {form_type}</span>
                            <span class="quant-badge cyan">DATE: {filing_date}</span>
                            <span style="color: #64748b; font-size: 0.8rem;">ID: <code>{chunk_id[:12]}...</code></span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Grounding Excerpt
                    st.markdown("##### 📌 Verbatim Lakehouse Excerpt:")
                    st.markdown(f"> {cit.get('excerpt', '')}")

                    # Full chunk metadata drawer
                    meta = chunk_data.get("metadata", {})
                    if meta:
                        with st.popover("🔍 Inspect Chunk Metadata"):
                            st.json(meta)
        else:
            st.caption("No citations matched the active retrieval thresholds.")
