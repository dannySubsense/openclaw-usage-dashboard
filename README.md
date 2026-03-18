# OpenClaw Token Usage Dashboard

A local HTML dashboard for visualizing API token usage and costs across Kimi (Moonshot) and Anthropic providers.

## Features

- **Real-time cost tracking** — Parse OpenClaw session logs and display token usage
- **Live balance display** — Fetch current Moonshot balance via API (already in USD)
- **Interactive visualizations** — Chart.js powered charts (daily spend, model breakdown, session types)
- **Sortable sessions table** — Click column headers to sort by date, cost, model, or tokens
- **Singapore timezone** — All timestamps displayed in UTC+8 (Asia/Singapore)
- **Anomaly detection** — Flags Sonnet/Opus fallback usage
- **Responsive design** — Works on mobile, tablet, and desktop
- **Zero external dependencies** — Single Python file, static HTML output

## Quick Start

### Step 1: Configure API Keys

Create or edit `.env` in the project directory:

```bash
cat > .env << 'EOF'
MOONSHOT_API_KEY=sk-your-moonshot-api-key
MONTHLY_BUDGET_USD=100.0
WARNING_THRESHOLD_USD=75.0
SESSION_DIR=~/.openclaw/agents/main/sessions
DAYS_BACK=30
EOF

# Secure the file (important!)
chmod 600 .env
```

**Required:**
- `MOONSHOT_API_KEY` — Your Moonshot API key for live balance fetch

**Optional (defaults provided):**
- `MONTHLY_BUDGET_USD` — Monthly spending limit (default: 100.0)
- `WARNING_THRESHOLD_USD` — Alert threshold (default: 75.0)
- `SESSION_DIR` — Path to OpenClaw session files (default: ~/.openclaw/agents/main/sessions)
- `DAYS_BACK` — Days of history to analyze (default: 30)

### Step 2: Generate Dashboard

The main command to generate a fresh dashboard:

```bash
cd /path/to/openclaw-usage-dashboard && python3 generate_dashboard.py
```

(Replace `/path/to/openclaw-usage-dashboard` with your actual installation path)

**What this does:**
1. Reads all `.jsonl` files from your OpenClaw sessions directory
2. Parses token usage and costs
3. Fetches current Moonshot balance from API
4. Generates a new `dashboard.html` with all data

**Output:**
```
2026-03-18 08:34:52,188 - INFO - Moonshot balance fetched: ¥83
2026-03-18 08:34:52,188 - INFO - Dashboard generated: dashboard.html
2026-03-18 08:34:52,188 - INFO - Processed 125 sessions, 4128 messages
```

### Step 3: View Dashboard

#### Option A: Local HTTP Server (Recommended)

```bash
cd /path/to/openclaw-usage-dashboard
python3 -m http.server 8888
```

Then open in your browser:
```
http://ml-research:8888/dashboard.html
```

#### Option B: Copy to Your Laptop

```bash
# On your laptop, run:
scp username@hostname:/path/to/openclaw-usage-dashboard/dashboard.html ~/Downloads/
open ~/Downloads/dashboard.html  # macOS
# or: xdg-open ~/Downloads/dashboard.html  # Linux
# or: start ~/Downloads/dashboard.html  # Windows
```

---

## Using the Dashboard

### Refreshing Data

The dashboard is **static HTML** — it doesn't auto-refresh. To see updated data:

1. **On the server**, regenerate:
   ```bash
   cd /path/to/openclaw-usage-dashboard && python3 generate_dashboard.py
   ```

2. **In your browser**, refresh the page (Cmd+R or Ctrl+R)

### Sorting the Top Sessions Table

Click any column header to sort:
- **Date** — Oldest/newest first
- **Cost** — Highest/lowest cost
- **Model** — Alphabetical by model name
- **Session ID** — Alphabetical
- **Type** — Cron vs Interactive
- **Tokens** — Most/least tokens used

Click the same header again to reverse sort order. Visual indicators (▲/▼) show the current sort column.

### Understanding the Display

All **timestamps are in Singapore time (UTC+8)**. If you see `12:00`, that's noon Singapore time.

All **costs are in USD** after conversion from CNY (if applicable).

---

## CLI Options

```bash
python3 generate_dashboard.py [OPTIONS]

Options:
  -o, --output PATH     Output HTML file (default: dashboard.html)
  -d, --days N          Number of days to analyze (default: 30)
  --session-dir PATH    Session files directory
  --no-api              Skip Moonshot API balance fetch
  -v, --verbose         Enable verbose logging
  -h, --help            Show help message
```

### Examples

**Analyze last 60 days:**
```bash
cd /path/to/openclaw-usage-dashboard && python3 generate_dashboard.py -d 60
```

**Use a different output file:**
```bash
cd /path/to/openclaw-usage-dashboard && python3 generate_dashboard.py -o dashboard-backup.html
```

**Skip API calls (offline mode):**
```bash
cd /path/to/openclaw-usage-dashboard && python3 generate_dashboard.py --no-api
```

**Verbose logging:**
```bash
cd /path/to/openclaw-usage-dashboard && python3 generate_dashboard.py -v
```

---

## Dashboard Sections

1. **Moonshot Balance Card** — Live balance in USD (fetched from API)
2. **Anthropic Spend Card** — Cumulative estimated spend from session logs
3. **Budget Tracker** — Progress bar with warning indicators (turns red at threshold)
4. **Daily Spend Chart** — Stacked bar chart showing Moonshot vs Anthropic over time
5. **Model Breakdown** — Pie chart and horizontal bar chart by model
6. **Session Type Distribution** — Doughnut chart (Cron jobs vs Interactive sessions)
7. **Top Sessions Table** — Highest-cost sessions (sortable, clickable headers)
8. **Anomaly Flags** — Warnings if Sonnet/Opus fallback was triggered

---

## Architecture

| Component | Details |
|-----------|---------|
| **Main Script** | `generate_dashboard.py` (~1,500 lines) |
| **Output** | `dashboard.html` (self-contained, static) |
| **Data Source** | OpenClaw JSONL session files |
| **Charting** | Chart.js 4.4.0 (CDN) |
| **Dependencies** | `requests`, `python-dotenv` (stdlib for the rest) |
| **Timezone** | Singapore (UTC+8) for all timestamps |

---

## Configuration Reference

### `.env` Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOONSHOT_API_KEY` | — | Moonshot API key (required for live balance) |
| `MONTHLY_BUDGET_USD` | 100.0 | Monthly spending budget |
| `WARNING_THRESHOLD_USD` | 75.0 | Dollar amount to trigger warning color |
| `SESSION_DIR` | `~/.openclaw/agents/main/sessions` | Path to OpenClaw session files |
| `DAYS_BACK` | 30 | How many days of history to include |
| `OUTPUT_FILE` | dashboard.html | Output filename |

### Security

- API keys are read from `.env` only (never hardcoded)
- `.env` file should have `chmod 600` permissions (warning issued if not)
- All dynamic HTML content is escaped to prevent injection
- Session file paths are validated

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `generate_dashboard.py` | Main script — run this to generate the dashboard |
| `dashboard.html` | Generated output — view this in your browser |
| `.env` | Configuration (API keys, settings) — gitignored, never committed |
| `README.md` | This file |
| `spec.md` | Implementation specification |
| `ARCHITECTURE.md` | Technical architecture details |
| `VALIDATION.md` | Post-generation validation report |

---

## Development & Maintenance

### Post-Generation Validation

After generating the dashboard, a validation report is written to `VALIDATION.md` with:
- Data accuracy checks
- Escaped tag detection
- Timestamp verification
- Cost attribution validation

Review this file to ensure data quality.

### Git Repository

This project is hosted at:
```
https://github.com/dannySubsense/openclaw-usage-dashboard
```

Never commit:
- `.env` file (contains API keys)
- Generated `dashboard.html` (run `generate_dashboard.py` to create)
- Temporary files or logs

---

## License

MIT
