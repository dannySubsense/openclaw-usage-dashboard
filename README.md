# OpenClaw Token Usage Dashboard

A local HTML dashboard for visualizing API token usage and costs across Kimi (Moonshot) and Anthropic providers.

## Features

- **Real-time cost tracking** — Parse OpenClaw session logs and display token usage
- **Live balance display** — Fetch current Moonshot balance via API
- **Interactive visualizations** — Chart.js powered charts (daily spend, model breakdown, session types)
- **Anomaly detection** — Flags Sonnet/Opus fallback usage
- **Responsive design** — Works on mobile, tablet, and desktop
- **Zero external dependencies** — Single Python file, static HTML output

## Quick Start

### 1. Configure API Keys

Edit `.env` and add your keys:

```bash
# Required for live balance
MOONSHOT_API_KEY=sk-your-moonshot-key

# Optional settings
MONTHLY_BUDGET_USD=100.0
WARNING_THRESHOLD_USD=75.0
DAYS_BACK=30
```

### 2. Generate Dashboard

```bash
python3 generate_dashboard.py
```

This creates `dashboard.html` with fresh data.

### 3. View Dashboard

```bash
# Linux
xdg-open dashboard.html

# Or copy to local machine
scp user@host:/path/to/dashboard.html ~/Downloads/
```

## Quick Reference Card

| Task | Command |
|------|---------|
| Refresh dashboard | `python3 generate_dashboard.py` |
| View dashboard | `xdg-open dashboard.html` |
| Change days analyzed | Edit `.env` → `DAYS_BACK=60` → regenerate |
| Change output file | `python3 generate_dashboard.py -o custom.html` |
| Skip API calls | `python3 generate_dashboard.py --no-api` |
| Verbose logging | `python3 generate_dashboard.py -v` |

## CLI Options

```
python3 generate_dashboard.py [OPTIONS]

Options:
  -o, --output PATH     Output HTML file (default: dashboard.html)
  -d, --days N          Number of days to analyze (default: 30)
  --session-dir PATH    Session files directory
  --no-api              Skip Moonshot API balance fetch
  -v, --verbose         Enable verbose logging
  -h, --help            Show help message
```

## Configuration

All settings via `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `MOONSHOT_API_KEY` | — | Moonshot API key for live balance |
| `MONTHLY_BUDGET_USD` | 100.0 | Monthly spending limit |
| `WARNING_THRESHOLD_USD` | 75.0 | Alert threshold (red indicator) |
| `CNY_TO_USD_RATE` | 0.14 | Exchange rate for balance display |
| `SESSION_DIR` | `~/.openclaw/agents/main/sessions` | OpenClaw session files |
| `OUTPUT_FILE` | dashboard.html | Default output filename |
| `DAYS_BACK` | 30 | Days of history to analyze |

## Dashboard Sections

1. **Live Balance Cards** — Moonshot balance (CNY + USD), Anthropic cumulative spend
2. **Budget Tracker** — Progress bar with warning indicators
3. **Daily Spend Chart** — Stacked bar chart (Moonshot vs Anthropic)
4. **Model Breakdown** — Pie + horizontal bar charts by model
5. **Session Type** — Cron vs Interactive doughnut chart
6. **Top Sessions Table** — Sortable table of highest-cost sessions
7. **Anomaly Flags** — Warnings for Sonnet/Opus fallback usage

## Architecture

- **Single file**: All code in `generate_dashboard.py`
- **Minimal dependencies**: `requests`, `python-dotenv` (plus stdlib)
- **Static output**: Self-contained HTML, no server required
- **Data source**: OpenClaw JSONL session files
- **Charting**: Chart.js 4.4.0 via CDN

## Security

- API keys from environment only (`.env` file)
- `.env` file permission checked (warns if world-readable)
- All dynamic content HTML-escaped
- Path validation prevents directory traversal

## Files

| File | Purpose |
|------|---------|
| `generate_dashboard.py` | Main script (1,477 lines) |
| `dashboard.html` | Generated output (view in browser) |
| `.env` | Configuration and API keys (gitignored) |
| `dashboard_generation.log` | Runtime logs |

## Development

This dashboard was built using the OpenClaw sprint framework:
- **Spec**: See `spec.md` for complete implementation specification
- **Sprint**: token-usage-dashboard (2026-03-17 to 2026-03-18)
- **Review**: APPROVED — see `REVIEW.md`

## License

MIT
