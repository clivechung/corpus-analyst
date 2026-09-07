"""Streamlit Presentation Component for Hive Parquet Lakehouse Explorer & SQL Console (UI-03).

Follows TREM-Python principles:
- Testable: Pure filesystem partition scanner (scan_hive_partitions) and byte formatting utilities.
- Readable: Modular sections for Telemetry Strip, Hive Directory Browser, Schema Inspector,
  and DuckDB SQL Console.
- Extensible: Pre-canned SQL templates for quantitative analysis, temporal partition checks,
  and tabular data auditing.
- Maintainable: Read-only query execution guards, error trapping, and zero mutation risk.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
import httpx
import pandas as pd

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]

try:
    from src.query_engine.duckdb_client import DuckDBLakehouseClient
except ImportError:
    DuckDBLakehouseClient = None  # type: ignore[assignment, misc]

logger = logging.getLogger("corpus_analyst_ui.lake_explorer")


# -----------------------------------------------------------------------------
# Pure Partition & Formatting Helpers (TREM: Testable)
# -----------------------------------------------------------------------------


def format_bytes(num_bytes: int) -> str:
    """Format byte counts into human-readable strings (KB, MB, GB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def scan_hive_partitions(lake_path: Path | str) -> list[dict[str, Any]]:
    """Scan Parquet data lake filesystem and return structured Hive partition records."""
    path_obj = Path(lake_path)
    if not path_obj.exists():
        return []

    files = list(path_obj.glob("**/*.parquet"))
    records: list[dict[str, Any]] = []

    for p in files:
        rel = p.relative_to(path_obj)
        parts = rel.parts

        domain_val = "unknown"
        year_val = "unknown"
        month_val = "unknown"
        day_val = "unknown"

        for segment in parts[:-1]:
            if segment.startswith("domain="):
                domain_val = segment.split("=", 1)[1]
            elif segment.startswith("year="):
                year_val = segment.split("=", 1)[1]
            elif segment.startswith("month="):
                month_val = segment.split("=", 1)[1]
            elif segment.startswith("day="):
                day_val = segment.split("=", 1)[1]

        stat = p.stat()
        records.append(
            {
                "domain": domain_val,
                "year": year_val,
                "month": month_val,
                "day": day_val,
                "filename": p.name,
                "relative_path": str(rel),
                "size_bytes": stat.st_size,
                "size_formatted": format_bytes(stat.st_size),
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(stat.st_mtime)),
            }
        )

    return records


def get_lakehouse_query_templates(lake_glob: str = "/data/lake/**/*.parquet") -> dict[str, str]:
    """Return dictionary of pre-canned DuckDB SQL queries over Hive Parquet lakehouse."""
    return {
        "Top 10 Vector Search (Cosine Similarity)": (
            f"-- Top 10 Vector Cosine Similarity Search using DuckDB array_cosine_similarity over 384-dim embeddings\n"
            f"-- Compares all chunks against a reference revenue & operational performance disclosure\n"
            f"WITH ref_chunk AS (\n"
            f"    SELECT embedding\n"
            f"    FROM read_parquet('{lake_glob}', hive_partitioning=true)\n"
            f"    WHERE lower(text) LIKE '%revenues increased%' OR lower(text) LIKE '%operating income increased%'\n"
            f"    LIMIT 1\n"
            f")\n"
            f"SELECT\n"
            f"    c.source_filename,\n"
            f"    c.section,\n"
            f"    c.is_table,\n"
            f"    round(array_cosine_similarity(c.embedding::FLOAT[384], ref.embedding::FLOAT[384]), 4) AS cosine_similarity,\n"
            f"    substring(c.text, 1, 140) AS excerpt\n"
            f"FROM read_parquet('{lake_glob}', hive_partitioning=true) c, ref_chunk ref\n"
            f"ORDER BY cosine_similarity DESC\n"
            f"LIMIT 10;"
        ),
        "Top 10 Tabular Disclosures": (
            f"SELECT source_filename, section, length(text) as char_length, text\n"
            f"FROM read_parquet('{lake_glob}', hive_partitioning=true)\n"
            f"WHERE is_table = true\n"
            f"LIMIT 10;"
        ),
        "Chunk Count by Domain": (
            f"SELECT domain, count(*) as chunk_count, count(distinct source_filename) as file_count\n"
            f"FROM read_parquet('{lake_glob}', hive_partitioning=true)\n"
            f"GROUP BY domain;"
        ),
        "Chunk Distribution by Year & Form": (
            f"SELECT domain, year, form_type, count(*) as count\n"
            f"FROM read_parquet('{lake_glob}', hive_partitioning=true)\n"
            f"GROUP BY domain, year, form_type\n"
            f"ORDER BY year DESC;"
        ),
        "Inspect Parquet Columns & Schema": (
            f"DESCRIBE SELECT * FROM read_parquet('{lake_glob}', hive_partitioning=true) LIMIT 1;"
        ),
    }


def execute_vector_search_api(
    query_engine_url: str,
    question: str,
    top_k: int = 10,
    domain: str = "finance",
) -> list[dict[str, Any]]:
    """Query the query-engine API for top-k candidate chunks."""
    resp = httpx.post(
        f"{query_engine_url.rstrip('/')}/api/v1/search",
        json={"question": question, "top_k": top_k, "domain": domain},
        timeout=30.0,
    )
    if resp.status_code == 200:
        return resp.json()
    raise RuntimeError(f"Search failed ({resp.status_code}): {resp.text}")


def generate_vector_search_sql(
    query_engine_url: str,
    prompt: str,
    lake_glob: str = "/data/lake/**/*.parquet",
    top_k: int = 10,
    domain: str = "finance",
) -> str:
    """Embed prompt via query engine and generate executable DuckDB vector similarity SQL."""
    resp = httpx.post(
        f"{query_engine_url.rstrip('/')}/api/v1/embed",
        json={"text": prompt, "domain": domain},
        timeout=30.0,
    )
    if resp.status_code == 200:
        vec = resp.json().get("embedding", [])
        dim = len(vec)
        # Format compact float representations
        vec_str = "[" + ", ".join(f"{v:.6f}" for v in vec) + "]"
        escaped_prompt = prompt.replace('"', '\\"')
        return (
            f"-- Top {top_k} Vector Cosine Similarity Search for: \"{escaped_prompt}\"\n"
            f"SELECT\n"
            f"    source_filename,\n"
            f"    section,\n"
            f"    is_table,\n"
            f"    round(array_cosine_similarity(embedding::FLOAT[{dim}], {vec_str}::FLOAT[{dim}]), 4) AS cosine_similarity,\n"
            f"    substring(text, 1, 140) AS excerpt\n"
            f"FROM read_parquet('{lake_glob}', hive_partitioning=true)\n"
            f"ORDER BY cosine_similarity DESC\n"
            f"LIMIT {top_k};"
        )
    raise RuntimeError(f"Embedding failed ({resp.status_code}): {resp.text}")


# -----------------------------------------------------------------------------
# Streamlit Presentation Component (UI-03)
# -----------------------------------------------------------------------------


def render_lakehouse_explorer_view(
    lake_path: str = "/data/lake",
    duckdb_client: Any = None,
    query_engine_url: str | None = None,
) -> None:
    """Render Hive Parquet Lakehouse Explorer and interactive DuckDB SQL Console."""
    st.subheader("🗄️ Hive Parquet Lakehouse Explorer & SQL Console")
    st.caption(
        "Direct vectorized inspection of Snappy Parquet columnar partitions: "
        f"`{lake_path}/domain={{domain}}/year={{YYYY}}/month={{MM}}/day={{DD}}/*.parquet`"
    )

    records = scan_hive_partitions(lake_path)

    # 1. Telemetry Strip
    total_files = len(records)
    total_bytes = sum(r["size_bytes"] for r in records)
    domains = sorted(set(r["domain"] for r in records if r["domain"] != "unknown"))
    partitions = sorted(set(f"{r['domain']}/{r['year']}/{r['month']}/{r['day']}" for r in records))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""
            <div class="quant-kpi-card amber">
                <div class="quant-kpi-label">TOTAL PARQUET FILES</div>
                <div class="quant-kpi-value">{total_files}</div>
                <div class="quant-kpi-sub">Hive Partitioned Batches</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
            <div class="quant-kpi-card emerald">
                <div class="quant-kpi-label">LAKEHOUSE STORAGE</div>
                <div class="quant-kpi-value">{format_bytes(total_bytes)}</div>
                <div class="quant-kpi-sub">Snappy Columnar Volume</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
            <div class="quant-kpi-card cyan">
                <div class="quant-kpi-label">INDEXED DOMAINS</div>
                <div class="quant-kpi-value">{len(domains)}</div>
                <div class="quant-kpi-sub">{", ".join(domains) if domains else "None"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f"""
            <div class="quant-kpi-card slate">
                <div class="quant-kpi-label">HIVE PARTITIONS</div>
                <div class="quant-kpi-value">{len(partitions)}</div>
                <div class="quant-kpi-sub">domain/year/month/day</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # 2. Hive Partition Directory Browser
    st.markdown("#### 📂 HIVE PARTITION BROWSER")
    st.caption("Inspect physical `.parquet` partitions and verify pruning paths.")

    if records:
        df_records = pd.DataFrame(records)
        selected_domain = st.selectbox(
            "Filter by Domain:",
            options=["All"] + domains,
            index=0,
            key="lake_domain_filter",
        )
        if selected_domain != "All":
            df_filtered = df_records[df_records["domain"] == selected_domain]
        else:
            df_filtered = df_records

        st.dataframe(
            df_filtered[
                [
                    "domain",
                    "year",
                    "month",
                    "day",
                    "filename",
                    "size_formatted",
                    "modified",
                    "relative_path",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.warning(f"No Parquet datasets found in data lake at: `{lake_path}`")

    st.markdown("---")

    # 3. Embedded DuckDB SQL Console
    st.markdown("#### ⚡ EMBEDDED DUCKDB SQL CONSOLE")
    st.caption("Execute in-process SQL queries directly over the Parquet lakehouse with zero external database.")

    lake_glob = f"{lake_path.rstrip('/')}/**/*.parquet"
    pre_canned_queries = get_lakehouse_query_templates(lake_glob)

    # Top 10 Vector Search Interactive Natural Language Query Box
    with st.expander("🔎 TOP 10 VECTOR SEARCH (Natural Language)", expanded=False):
        st.markdown(
            "Execute an end-to-end vector cosine similarity search across all Parquet lakehouse embeddings "
            "for any custom question or prompt."
        )
        v_col1, v_col2, v_col3 = st.columns([3, 1, 1])
        with v_col1:
            nl_prompt = st.text_input(
                "Search Prompt:",
                value="google revenue in 2026",
                key="lake_nl_search_prompt",
                placeholder="Enter financial, legal, or research question...",
            )
        with v_col2:
            st.write("")
            st.write("")
            btn_nl_search = st.button("🔍 Top 10 Search", key="btn_run_nl_vector_search", use_container_width=True)
        with v_col3:
            st.write("")
            st.write("")
            btn_gen_sql = st.button("⚡ Generate SQL", key="btn_gen_vector_sql", use_container_width=True)

        target_url = query_engine_url or "http://query-engine:8000"

        if btn_gen_sql and nl_prompt:
            with st.spinner("Generating DuckDB Vector Search SQL..."):
                try:
                    generated_sql = generate_vector_search_sql(
                        query_engine_url=target_url,
                        prompt=nl_prompt,
                        lake_glob=lake_glob,
                        top_k=10,
                    )
                    st.session_state["lake_sql_query_input"] = generated_sql
                    st.success("Generated executable DuckDB vector search SQL loaded into console below!")
                except Exception as ex:
                    st.error(f"SQL generation failed: {ex}")

        if btn_nl_search and nl_prompt:
            with st.spinner("Executing DuckDB vector search across Parquet lakehouse..."):
                try:
                    candidates = execute_vector_search_api(
                        query_engine_url=target_url,
                        question=nl_prompt,
                        top_k=10,
                    )
                    if candidates:
                        st.success(f"Retrieved {len(candidates)} candidate chunks via DuckDB Vector Search.")
                        table_data = []
                        for idx, c in enumerate(candidates, 1):
                            score = c.get("similarity_score", 0.0)
                            table_data.append(
                                {
                                    "Rank": f"#{idx}",
                                    "Similarity": f"{score:.4f}",
                                    "Source Filing": c.get("source_filename"),
                                    "Section": c.get("section"),
                                    "Type": "📊 Table" if c.get("is_table") else "📄 Prose",
                                    "Excerpt": (c.get("text") or "")[:150].replace("\n", " ") + "...",
                                }
                            )
                        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
                    else:
                        st.info("No matching chunks found above threshold.")
                except Exception as ex:
                    st.error(f"Vector search failed: {ex}")

    selected_template = st.selectbox(
        "Select Sample Query Template:",
        options=list(pre_canned_queries.keys()),
        index=0,
        key="sql_template_selector",
    )

    if (
        "prev_sql_template" not in st.session_state
        or st.session_state["prev_sql_template"] != selected_template
    ):
        st.session_state["lake_sql_query_input"] = pre_canned_queries[selected_template]
        st.session_state["prev_sql_template"] = selected_template

    query_input = st.text_area(
        "SQL Query:",
        value=st.session_state.get("lake_sql_query_input", pre_canned_queries[selected_template]),
        height=140,
        key="lake_sql_query_input",
    )

    col_exec, col_info = st.columns([1, 4])
    with col_exec:
        run_sql = st.button("▶ Run SQL", type="primary", use_container_width=True)

    if run_sql and query_input:
        start_time = time.perf_counter()
        try:
            cols: list[str] = []
            rows: list[tuple[Any, ...]] = []
            duration_ms: float = 0.0

            if duckdb_client is not None:
                cols, rows = duckdb_client.execute_sql(query_input)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
            elif DuckDBLakehouseClient is not None:
                client = DuckDBLakehouseClient()
                cols, rows = client.execute_sql(query_input)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
            elif query_engine_url:
                resp = httpx.post(
                    f"{query_engine_url.rstrip('/')}/api/v1/sql",
                    json={"query": query_input},
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    cols = data.get("columns", [])
                    rows = [tuple(r) for r in data.get("rows", [])]
                    duration_ms = data.get("duration_ms", 0.0)
                elif resp.status_code == 403:
                    raise PermissionError(resp.json().get("detail", "Security Guard: Mutative operation rejected."))
                else:
                    raise RuntimeError(resp.json().get("detail", f"Query Engine error ({resp.status_code}): {resp.text}"))
            else:
                raise RuntimeError("DuckDB client unavailable and QUERY_ENGINE_URL not configured.")

            st.markdown(
                f"""
                <div style="display: flex; gap: 1rem; margin-top: 0.5rem; margin-bottom: 0.8rem;">
                    <span class="quant-badge emerald">STATUS: SUCCESS</span>
                    <span class="quant-badge cyan">ROWS: {len(rows)}</span>
                    <span class="quant-badge amber">DURATION: {duration_ms:.2f} ms</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if cols:
                df_result = pd.DataFrame(rows, columns=cols)
                st.dataframe(df_result, use_container_width=True)
            else:
                st.info("Query executed successfully. (0 columns returned)")
        except PermissionError as perm_err:
            st.error(f"Security Guard: {perm_err}")
        except Exception as exc:
            st.error(f"DuckDB SQL Execution Error: {exc}")

