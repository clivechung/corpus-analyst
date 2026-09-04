"""Quant Trading Floor styling and theme injection for Corpus Analyst UI.

Provides Bloomberg Terminal / Refinitiv inspired dark obsidian and amber aesthetics,
monospace typography, high-density telemetry widgets, market hours tracker, and terminal status badges.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import streamlit as st

QUANT_CSS = """
<style>
/* Global Quant Styling */
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, .stButton, .stTextInput, .stSelectbox {
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
}

/* Page background & main container padding */
.stApp {
    background-color: #0b0e14 !important;
    color: #e2e8f0 !important;
}

.main .block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 2rem !important;
    padding-left: 1.8rem !important;
    padding-right: 1.8rem !important;
    max-width: 100% !important;
}

/* Sidebar Styling */
section[data-testid="stSidebar"] {
    background-color: #0e121a !important;
    border-right: 1px solid #1e293b !important;
}

/* Top Trading Floor Banner */
.quant-header-banner {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: linear-gradient(90deg, #111622 0%, #161f30 100%);
    border: 1px solid #1e293b;
    border-left: 4px solid #ffb000;
    border-radius: 4px;
    padding: 0.6rem 1.2rem;
    margin-bottom: 1.2rem;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}

.quant-header-title {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #f8fafc;
}

.quant-header-title span.accent {
    color: #ffb000;
}

.quant-telemetry-cluster {
    display: flex;
    align-items: center;
    gap: 1.2rem;
    font-size: 0.82rem;
}

.quant-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.2rem 0.6rem;
    border-radius: 3px;
    font-weight: 600;
    letter-spacing: 0.03em;
    font-size: 0.78rem;
}

.quant-pill-market-open {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.4);
}

.quant-pill-market-closed {
    background-color: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.4);
}

.quant-pill-daemon-live {
    background-color: rgba(0, 229, 255, 0.12);
    color: #00e5ff;
    border: 1px solid rgba(0, 229, 255, 0.4);
}

/* Metric Cards */
.quant-kpi-card {
    background: #111622;
    border: 1px solid #1e293b;
    border-radius: 4px;
    padding: 0.8rem 1rem;
    position: relative;
    overflow: hidden;
}

.quant-kpi-card::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
}

.quant-kpi-card.amber::before { background-color: #ffb000; }
.quant-kpi-card.emerald::before { background-color: #10b981; }
.quant-kpi-card.cyan::before { background-color: #00e5ff; }
.quant-kpi-card.crimson::before { background-color: #ef4444; }

.quant-kpi-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #94a3b8;
    margin-bottom: 0.2rem;
}

.quant-kpi-value {
    font-size: 1.7rem;
    font-weight: 700;
    color: #f8fafc;
    line-height: 1.2;
}

.quant-kpi-sub {
    font-size: 0.72rem;
    color: #64748b;
    margin-top: 0.2rem;
}

/* Badges for status */
.quant-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.quant-badge-pending {
    background-color: rgba(255, 176, 0, 0.15);
    color: #fbbf24;
    border: 1px solid rgba(255, 176, 0, 0.4);
}

.quant-badge-processing {
    background-color: rgba(0, 229, 255, 0.15);
    color: #38bdf8;
    border: 1px solid rgba(0, 229, 255, 0.4);
}

.quant-badge-processed {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.4);
}

.quant-badge-failed {
    background-color: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.4);
}

.quant-badge-ticker {
    background-color: #1e293b;
    color: #38bdf8;
    border: 1px solid #334155;
    font-weight: 700;
}

.quant-badge-form {
    background-color: #1e293b;
    color: #ffb000;
    border: 1px solid #334155;
}

/* Streamlit Tabs Customization */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background-color: #0e121a;
    border-bottom: 1px solid #1e293b;
    padding: 0.2rem 0.4rem 0 0.4rem;
}

.stTabs [data-baseweb="tab"] {
    padding: 0.5rem 1rem;
    font-size: 0.85rem;
    font-weight: 600;
    color: #94a3b8 !important;
    background-color: transparent !important;
    border-top: 2px solid transparent !important;
    border-radius: 4px 4px 0 0 !important;
}

.stTabs [aria-selected="true"] {
    color: #ffb000 !important;
    border-top: 2px solid #ffb000 !important;
    background-color: #111622 !important;
}

/* Buttons */
.stButton > button {
    border-radius: 3px !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    transition: all 0.15s ease !important;
}

.stButton > button[kind="primary"] {
    background-color: #ffb000 !important;
    color: #0b0e14 !important;
    border: 1px solid #d99100 !important;
}

.stButton > button[kind="primary"]:hover {
    background-color: #ffbe26 !important;
    box-shadow: 0 0 10px rgba(255, 176, 0, 0.4) !important;
}

.stButton > button[kind="secondary"] {
    background-color: #161f30 !important;
    color: #e2e8f0 !important;
    border: 1px solid #2d3e58 !important;
}

.stButton > button[kind="secondary"]:hover {
    background-color: #1c273c !important;
    border-color: #38bdf8 !important;
}

/* Inputs */
div[data-baseweb="input"] {
    background-color: #111622 !important;
    border: 1px solid #1e293b !important;
    border-radius: 3px !important;
}

/* Quant Terminal Box */
.quant-terminal-box {
    background-color: #080b10;
    border: 1px solid #1e293b;
    border-left: 3px solid #ef4444;
    border-radius: 3px;
    padding: 0.8rem;
    font-size: 0.78rem;
    color: #f87171;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
}

/* Clean up Streamlit default header decoration */
header[data-testid="stHeader"] {
    background-color: rgba(11, 14, 20, 0.8) !important;
}
</style>
"""


def inject_quant_theme() -> None:
    """Inject quant trading floor styling into the active Streamlit app session."""
    st.markdown(QUANT_CSS, unsafe_allow_html=True)


def get_market_session_info() -> dict[str, str | bool]:
    """Calculate current US equity market session status (NYSE/NASDAQ 09:30-16:00 ET)."""
    now_utc = datetime.now(timezone.utc)
    try:
        eastern_tz = ZoneInfo("America/New_York")
        now_et = now_utc.astimezone(eastern_tz)
    except Exception:
        # Fallback if ZoneInfo not found in lightweight container
        now_et = now_utc

    # Mon=0, Tue=1, ..., Sun=6
    is_weekday = now_et.weekday() < 5
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    is_open = is_weekday and (market_open <= now_et < market_close)

    status_str = "NYSE: OPEN" if is_open else "NYSE: CLOSED"
    time_str = now_et.strftime("%H:%M:%S ET")
    utc_str = now_utc.strftime("%H:%M:%S UTC")

    return {
        "is_open": is_open,
        "status_label": status_str,
        "et_time": time_str,
        "utc_time": utc_str,
    }


def render_trading_floor_header(
    query_engine_online: bool = True,
    daemon_online: bool = True,
    active_domain: str = "finance",
) -> None:
    """Render top terminal header banner with market hours, service health, and clock."""
    market = get_market_session_info()
    market_pill_class = "quant-pill-market-open" if market["is_open"] else "quant-pill-market-closed"
    market_dot = "🟢" if market["is_open"] else "🔴"

    daemon_pill = (
        '<span class="quant-pill quant-pill-daemon-live">⚡ INGEST DAEMON: ACTIVE</span>'
        if daemon_online
        else '<span class="quant-pill quant-pill-market-closed">⚠️ INGEST DAEMON: OFF</span>'
    )

    qe_pill = (
        '<span class="quant-pill quant-pill-market-open">🟢 QUERY ENGINE: ONLINE</span>'
        if query_engine_online
        else '<span class="quant-pill quant-pill-market-closed">🟡 QUERY ENGINE: IDLE</span>'
    )

    header_html = f"""
    <div class="quant-header-banner">
        <div class="quant-header-title">
            <span>⚡ <span class="accent">CORPUS ANALYST</span> // QUANTITATIVE INGESTION ENGINE</span>
            <span class="quant-badge quant-badge-ticker">{active_domain.upper()}</span>
        </div>
        <div class="quant-telemetry-cluster">
            <span class="quant-pill {market_pill_class}">{market_dot} {market["status_label"]} ({market["et_time"]})</span>
            {daemon_pill}
            {qe_pill}
            <span style="color: #94a3b8; font-size: 0.78rem;">🕒 {market["utc_time"]}</span>
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)
