# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**SFD Pipeline** — an automated Korean stock market signal pipeline that runs as a GitHub Actions workflow weekdays at 08:35 KST (UTC 23:35). It fetches market data, scores each ticker across multiple dimensions, and outputs buy/watch/hold signals to Google Drive.

## Running the Pipeline

**GitHub Actions (production):** `.github/workflows/sfd_daily_v10.4.yml` — the current active workflow. `sfd_daily.yml` is an older reference.

**Local run (Windows):**
```powershell
# Set runtime base dir (matches GitHub Actions /tmp/sfd)
$env:SFD_BASE_DIR = "D:\AI_WorkSpace\I_SFC\09_Implementation\sfd-pipeline"

# Run individual layer
python tools/sfd_signal_aggregator.py

# Or run full pipeline (note: hardcoded paths in run_sfd_v02_pipeline.py may need adjustment)
python tools/run_sfd_v02_pipeline.py
```

**Install dependencies:**
```
pip install -r requirements.txt
```
Requires Python 3.11. Key packages: `pandas`, `numpy`, `yfinance`, `FinanceDataReader`, `requests`, `beautifulsoup4`, `google-api-python-client`.

## Layer Architecture

The pipeline executes in strict layer order. Most layers use `continue-on-error: true` except Layer 1 (`prev_close_fetch`) and Layer 2.7 (`technical_analyzer`).

| Layer | Script | Purpose |
|-------|--------|---------|
| -2 | `sfd_macro_radar.py` | Global macro indicators (yfinance: indices, DXY, bonds) |
| 0.5 | `sfd_global_trigger.py` | US market pre-trigger → KR ticker boost scores |
| 1 | `sfd_prev_close_fetch.py` | Previous close prices → `sfd_prev_close_latest.csv` + ticker list |
| 1.5 | `sfd_news_fetcher.py` | Naver News API → `sfd_news_score_latest.csv` |
| 1.6 | `sfd_event_calendar_builder.py` | DART event calendar |
| 1.8 | `sfd_365_event_calendar.py` | Extended 365-day event calendar |
| 2.7 | `sfd_technical_analyzer.py` | Technical scoring (max 93pt) → `sfd_technical_latest.csv` |
| 2.8 | `sfd_oscillation_analyzer.py` | Oscillation / zone analysis |
| **2 Pass1** | `sfd_signal_aggregator.py` | Pre-fund aggregation → `sfd_master_signal_latest.csv` (top-200 seed) |
| 2.5 | `sfd_rerating_watch.py` | Re-rating watch layer |
| 2.6 | `sfd_fundamental_watch.py` | PER/PBR/EPS scraping from Naver Finance (top-200 only) → `sfd_fundamental_watch_latest.csv` |
| 2.6b | `sfd_sector_injector.py` | Sector score injection (BM-6) |
| 2.6c | `sfd_investor_flow_fetch.py` | KIS API foreign/institution net-buy → `sfd_investor_flow_latest.csv` |
| **2 Pass2** | `sfd_signal_aggregator.py` | Final aggregation with `fund_score` + `investor_score` |
| 3 | `sfd_backtest_d1.py` | D+1 backtest |
| 3b | `sfd_backtest_analyzer.py` | Backtest analysis |
| 3c | `sfd_threshold_optimizer.py` | Threshold optimization |
| 4 | `sfd_finalize.py` | Merge master_signal + fundamental → `sfd_signal.csv` |
| 5 | `sfd_portfolio_monitor.py` | Portfolio P&L monitoring |
| 5.5 | `sfd_trade_guardian.py` | Trade rule enforcement + psychology alerts |
| Upload | `utils/gdrive_uploader.py` | OAuth2 refresh-token upload to Google Drive |

### Why 3-Pass Aggregator

`fundamental_watch` (Layer 2.6) only processes the **top-200 tickers** from Pass1 output to limit DART/Naver scraping. Pass1 runs with `fund_score=0`, Pass2 re-runs after fundamentals are populated. Without this, `fund_score` and `investor_score` would always be zero.

## Signal Classification

`sfd_master_signal_latest.csv` outputs one of these signals per ticker:

| Signal | Condition |
|--------|-----------|
| `RESERVE_BUY` | `total_score >= 90` |
| `WATCH_ONLY` | `total_score >= 70` |
| `HOLD` | below 70 |
| `NO_TRADE` | ticker in `sfd_no_trade_tickers.json` (BM-5 override) |
| `SIGNAL_EXPIRED` | was RESERVE_BUY/WATCH_ONLY but 5 consecutive HOLD bars elapsed (BM-13) |

## Technical Score Architecture (`sfd_technical_analyzer.py`)

Max **93pt** total (`tech_total_score`):

| Component | Max | BM code |
|-----------|-----|---------|
| [A] Volume Profile / POC | 15pt | |
| [B] Support/Resistance | 10pt | |
| [C] RSI oversold position | 5pt | |
| [D] MA5>20>60>120 alignment | 10pt | |
| [E] Volume Gap Score (설거지 detection) | 15pt | v1.1 |
| [F] Standard Bar Score (기준봉) | 10pt | v1.1 |
| [G] Pullback Zone Score (눌림목) | 10pt | v1.2 BM-12 |
| [H] Volume Surge Score (치량천) | 10pt | v1.3 BM-10 |
| [I] MA60 direction score | 8pt | v1.4 BM-2 |

## Path Convention

All scripts resolve their working directory via:
```python
_env_base = os.environ.get("SFD_BASE_DIR", "")
if _env_base and os.path.isdir(_env_base):
    BASE_DIR = _env_base
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

In GitHub Actions: `SFD_BASE_DIR=/tmp/sfd`. Locally: falls back to the repo root (two levels up from `tools/`). All outputs go under `$BASE_DIR/outputs/latest/` and `$BASE_DIR/outputs/history/`.

## Key File Locations

| File | Purpose |
|------|---------|
| `inputs/sfd_master_signal_input.csv` | Ticker list (copied from prev_close output at Layer 1) |
| `inputs/sfd_naver_news_queries.csv` | Naver News search query mappings |
| `data/sfd_company_master_v1.4_sector_filled.csv` | Company master with sector info |
| `portfolio.json` | Active holdings (grades A/B/C, trigger prices, step ratios) |
| `outputs/latest/sfd_master_signal_latest.csv` | Current day's final signal output |
| `outputs/latest/sfd_signal_aggregator.log` | Aggregator run log |
| `outputs/latest/signal_timeout_state.json` | BM-13 state machine persistence |
| `outputs/latest/sfd_no_trade_tickers.json` | BM-5 no-trade override list |
| `config.py` | Path constants (used by some older layers) |

## External APIs & Secrets

| Secret | Used by |
|--------|---------|
| `KIS_APP_KEY` / `KIS_APP_SECRET` | `sfd_investor_flow_fetch.py` — KIS Developers API |
| `KIS_ACCOUNT_NO` / `KIS_ACCT_PROD` | Portfolio/account calls |
| `DART_API_KEY` | `sfd_event_calendar_builder.py` — DART filing events |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | `sfd_news_fetcher.py` |
| `GDRIVE_*` (5 secrets) | `utils/gdrive_uploader.py` — OAuth2 refresh token flow |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service account fallback |

KIS credentials also fall back to a local `.env` file (not committed) when env vars are absent.

## Aggregator Score Columns

The `sfd_master_signal_latest.csv` includes these score breakdown columns:
`tech_score`, `poc_score`, `sr_score`, `news_score`, `investor_score`, `theme_score`, `fund_score`, `bias_filter_score` (BM-3), `vol_surge_score` (BM-10), `zone_pullback_score` (BM-12), `pullback_zone_score`.

The `fund_score` column is normalized: `(raw 0–100) / 100 × 15` → max 15pt.

## Fundamental Watch Column Compatibility

`sfd_fundamental_watch.py` outputs `sfd_fundamental_watch_latest.csv` (v1.6+). The aggregator checks for this file first, falls back to `sfd_fundamental_latest.csv` (legacy). Score column priority: `adjusted_fund_score` > `fund_score` > `fundamental_score`.

## `portfolio.json` Structure

Holdings have `grade` (A/B/C), `trigger_pct`, `trigger_price`, `current_step`, `max_steps`, `step_qty_ratio`. Grade A = core long-term (pyramiding 1:2:3:4, -15% trigger). Grade B = small/uncertain (equal small, -25% trigger). Grade C = inactive/spider-web.

## SFD Operations Rules (Permanent)

### File Deployment
- NEVER edit yml files in-place via PowerShell — always deploy Claude-generated files only
- Deploy to BOTH paths simultaneously: sfd-pipeline/tools/ AND SFC_DataPipeline/tools/
- present_files download lands at: D:\AI_WorkSpace\I_SFC\download\
- Copy-Item source: always D:\AI_WorkSpace\I_SFC\download\ (never $env:USERPROFILE\Downloads\)

### Terminal
- VS Code PowerShell only — use `py` command (not `python`)
- CMD syntax (chcp, python) does NOT work in PowerShell

### Git / GitHub Actions
- GitHub Actions budget resets: 2026-06-29
- Run #93 trigger: after 6/29 reset — rename sfd_daily_v10.4.yml → sfd_daily.yml first
- yml V10.4 is ready locally, pending rename+push on 6/29

### Token Conservation
- Never push speculatively — confirm root cause before any fix
- No intermediate SESSION_BRIEFs — write only once at session end (>75% window)
- Same mistake must never repeat — record all fixes immediately

### Signal Thresholds
- RESERVE_BUY >= 90, WATCH_ONLY >= 70, MODE=ORIGINAL
- Do NOT change thresholds until backtest confidence = HIGH (need 30+ days data)

### SESSION_BRIEF
- Save to Google Drive (parentId: 1p2ZTMfjW7HJx49GDXiL5loQjQp22SHkN)
- Notion: Drive link only (no full text duplication)
- Always provide next-session start phrase in code block
