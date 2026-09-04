#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# SEC EDGAR Downloader Utility Script
#
# Fetches 10-K, 10-Q, and 8-K filings with day-granularity date filtering
# and enforces SEC EDGAR User-Agent compliance.
#
# Usage:
#   ./scripts/fetch_sec_filings.sh --ticker NVDA --form 10-K \
#       --start-date 2024-01-01 --end-date 2024-03-31 \
#       --user-agent "MyName myemail@domain.com"
#
# Alternatively, set SEC_USER_AGENT in your environment:
#   export SEC_USER_AGENT="MyName myemail@domain.com"
#   ./scripts/fetch_sec_filings.sh --ticker NVDA --form 10-K
# ==============================================================================

TICKER=""
FORM="10-K"
START_DATE=""
END_DATE=""
LIMIT="1"
OUTPUT_DIR="./data/incoming"
USER_AGENT="${SEC_USER_AGENT:-}"

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -t, --ticker TICKER          Stock ticker symbol (required, e.g. NVDA, AAPL, MSFT)"
    echo "  -f, --form FORM              Filing form type (10-K, 10-Q, 8-K; default: 10-K)"
    echo "  -s, --start-date YYYY-MM-DD  Start date (inclusive, day granularity)"
    echo "  -e, --end-date YYYY-MM-DD    End date (inclusive, day granularity)"
    echo "  -l, --limit N                Maximum filings to download (default: 1)"
    echo "  -o, --output-dir DIR         Destination directory (default: ./data/incoming)"
    echo "  -u, --user-agent STRING      SEC User-Agent header (format: 'Name email@domain.com')"
    echo "  -h, --help                   Display this help message"
    echo ""
}

# Parse command line options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -t|--ticker)
            TICKER="$2"
            shift 2
            ;;
        -f|--form)
            FORM="$2"
            shift 2
            ;;
        -s|--start-date)
            START_DATE="$2"
            shift 2
            ;;
        -e|--end-date)
            END_DATE="$2"
            shift 2
            ;;
        -l|--limit)
            LIMIT="$2"
            shift 2
            ;;
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -u|--user-agent)
            USER_AGENT="$2"
            shift 2
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1" >&2
            print_usage
            exit 1
            ;;
    esac
done

# Validate required ticker
if [[ -z "$TICKER" ]]; then
    echo "Error: --ticker is required." >&2
    print_usage
    exit 1
fi

# Prompt for User-Agent if not provided
if [[ -z "$USER_AGENT" ]]; then
    echo "===================================================================="
    echo "SEC EDGAR requires a user-agent header in the format:"
    echo "  Sample Company Name AdminContact@<sample company domain>.com"
    echo "===================================================================="
    read -rp "Please enter your SEC User-Agent string: " USER_AGENT
    if [[ -z "$USER_AGENT" ]]; then
        echo "Error: User-Agent cannot be empty. SEC will reject requests." >&2
        exit 1
    fi
fi

# Export SEC_USER_AGENT so python / sub-process inherits it
export SEC_USER_AGENT="$USER_AGENT"

# Build arguments array
ARGS=(
    "--ticker" "$TICKER"
    "--form" "$FORM"
    "--limit" "$LIMIT"
    "--output-dir" "$OUTPUT_DIR"
)

if [[ -n "$START_DATE" ]]; then
    ARGS+=("--start-date" "$START_DATE")
fi

if [[ -n "$END_DATE" ]]; then
    ARGS+=("--end-date" "$END_DATE")
fi

echo "==> Fetching SEC filings for ticker: $TICKER (Form: $FORM)..."
echo "==> Using User-Agent: $USER_AGENT"
if [[ -n "$START_DATE" || -n "$END_DATE" ]]; then
    echo "==> Date filter: [${START_DATE:-*} to ${END_DATE:-*}]"
fi

# Determine execution runtime: if docker compose ingestion-runner is running, use it; otherwise python3
if command -v docker >/dev/null 2>&1 && docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "ingestion-runner"; then
    echo "==> Executing via running Docker container: ingestion-runner"
    CONTAINER_ARGS=()
    for arg in "${ARGS[@]}"; do
        if [[ "$arg" == "./data/incoming" || "$arg" == "data/incoming" ]]; then
            CONTAINER_ARGS+=("/data/incoming")
        else
            CONTAINER_ARGS+=("$arg")
        fi
    done
    docker compose exec -e SEC_USER_AGENT="$SEC_USER_AGENT" ingestion-runner python -m src.ingestion.sec_fetcher "${CONTAINER_ARGS[@]}"
else
    echo "==> Executing via local Python environment"
    python3 -m src.ingestion.sec_fetcher "${ARGS[@]}"
fi

