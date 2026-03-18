# Token Usage Dashboard - Technical Architecture

## Overview
A local HTML dashboard displaying API costs across Kimi (Moonshot) and Anthropic providers, generated from session JSONL files and live API data. Single Python script generates static HTML with Chart.js visualizations.

## 1. File Structure and Naming

```
/home/d-tuned/openclaw-usage-dashboard/
├── generate_dashboard.py         # Main Python script (single file)
├── dashboard.html                # Generated output
├── .env                          # Configuration (gitignored)
├── ARCHITECTURE.md               # This file
└── README.md                     # Usage instructions
```

### Design Decisions
- **Single Python script**: Simplifies deployment, no package dependencies beyond stdlib and requests
- **Static HTML output**: No backend required, can be viewed offline or served via simple HTTP server
- **Separate .env file**: API keys and config externalized for security
- **Generated output name**: `dashboard.html` (default), configurable via CLI arg

## 2. Data Model / Schema

### 2.1 Input Data Sources

#### Session JSONL Files
**Location**: `~/.openclaw/agents/main/sessions/*.jsonl`

**Relevant Event Types**:
- `type: "session"` - Session metadata (timestamp, id, cwd)
- `type: "message"` - API call with usage data
- `type: "model_change"` - Provider/model switches

**Key Fields to Extract from Message Events**:
```python
{
    "type": "message",
    "id": str,              # Message ID
    "timestamp": str,       # ISO 8601 format
    "message": {
        "role": str,        # "user" or "assistant"
        "provider": str,    # "moonshot" or "anthropic"
        "model": str,       # "kimi-k2.5", "claude-sonnet-4-5-20250929", etc.
        "usage": {
            "input": int,           # Input tokens
            "output": int,          # Output tokens
            "cacheRead": int,       # Cache read tokens
            "cacheWrite": int,      # Cache write tokens
            "totalTokens": int,     # Total tokens
            "cost": {
                "input": float,     # Input cost in USD
                "output": float,    # Output cost in USD
                "cacheRead": float, # Cache read cost
                "cacheWrite": float,# Cache write cost
                "total": float      # Total cost in USD
            }
        }
    }
}
```

**Session Type Detection**:
- **Cron**: Detect from message content containing `[cron:` prefix
- **Interactive**: All other sessions

**File Filtering**:
- Exclude: `*.deleted.*`, `*.reset.*` (corrupted/archived sessions)
- Include: Active `*.jsonl` files only

#### Moonshot Live Balance API
**Endpoint**: `https://api.moonshot.ai/v1/users/me/balance`
**Method**: GET
**Authentication**: Bearer token (API key)
**Response Structure**:
```json
{
    "available_balance": 1234.56,  // Total available balance (CNY)
    "voucher_balance": 0.00,       // Balance from vouchers/credits (CNY)
    "cash_balance": 1234.56        // Cash balance (CNY)
}
```

**Response Fields**:
- `available_balance`: Total available balance (CNY) - sum of voucher and cash balances
- `voucher_balance`: Balance from vouchers/credits (CNY)
- `cash_balance`: Cash balance (CNY)

**Example Request**:
```bash
curl -X GET https://api.moonshot.ai/v1/users/me/balance \
  -H "Authorization: Bearer $MOONSHOT_API_KEY"
```

**Conversion**: CNY to USD using current exchange rate (configurable)

#### Anthropic Balance (Estimated)
**Calculation**: Sum of all Anthropic costs from JSONL files
**Note**: No official balance API - this is cumulative spend

### 2.2 Parsed Data Schema

#### SessionData
```python
@dataclass
class SessionData:
    session_id: str
    start_timestamp: datetime
    end_timestamp: datetime
    session_type: str  # "cron" or "interactive"
    provider: str      # "moonshot" or "anthropic"
    model: str         # e.g., "kimi-k2.5"
    total_input: int
    total_output: int
    total_cache_read: int
    total_cache_write: int
    total_cost: float  # USD
    message_count: int
```

#### DailySummary
```python
@dataclass
class DailySummary:
    date: date
    moonshot_cost: float
    anthropic_cost: float
    total_cost: float
    message_count: int
    session_count: int
```

#### ModelBreakdown
```python
@dataclass
class ModelBreakdown:
    model: str
    provider: str
    total_cost: float
    message_count: int
    token_count: int
```

#### AnomalyFlag
```python
@dataclass
class AnomalyFlag:
    session_id: str
    timestamp: datetime
    model: str  # "sonnet" or "opus"
    reason: str  # "Fallback triggered: Kimi unavailable"
    cost: float
```

**Anomaly Detection Rules**:
- Sonnet (claude-sonnet-*) usage: Flag as fallback
- Opus (claude-opus-*) usage: Flag as fallback
- Threshold: Any usage indicates fallback triggered

### 2.3 Configuration Schema

```python
@dataclass
class Config:
    # Paths
    session_dir: str = "~/.openclaw/agents/main/sessions"
    output_file: str = "dashboard.html"

    # API Keys
    moonshot_api_key: str = ""  # From .env

    # Budget
    monthly_budget_usd: float = 100.0
    warning_threshold_usd: float = 75.0

    # Exchange Rate
    cny_to_usd_rate: float = 0.14  # ~7.1 CNY per USD

    # Time Range
    days_back: int = 30  # Default analysis window
```

## 3. HTML/Chart.js Structure

### 3.1 Page Layout

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Token Usage Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        /* Embedded CSS: Dark theme, responsive grid */
    </style>
</head>
<body>
    <header>
        <h1>OpenClaw Token Usage Dashboard</h1>
        <div id="generated-time">Generated: {timestamp}</div>
    </header>

    <main>
        <!-- Section 1: Live Balance -->
        <section id="live-balance">
            <div class="balance-card moonshot">
                <h3>Moonshot Balance</h3>
                <div class="amount">${moonshot_balance_usd}</div>
                <div class="subtitle">¥{moonshot_balance_cny}</div>
            </div>
            <div class="balance-card anthropic">
                <h3>Anthropic Spend (Estimated)</h3>
                <div class="amount">${anthropic_total_usd}</div>
                <div class="subtitle">Cumulative from logs</div>
            </div>
        </section>

        <!-- Section 2: Budget Tracker -->
        <section id="budget-tracker">
            <h2>Monthly Budget Tracker</h2>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {percent}%"></div>
            </div>
            <div class="budget-stats">
                <span>Spent: ${spent}</span>
                <span>Budget: ${budget}</span>
                <span>Remaining: ${remaining}</span>
            </div>
            <!-- Warning indicator if over threshold -->
        </section>

        <!-- Section 3: Daily Spend Chart -->
        <section id="daily-spend">
            <h2>Daily Spend (Last 30 Days)</h2>
            <canvas id="daily-spend-chart"></canvas>
        </section>

        <!-- Section 4: Model Breakdown -->
        <section id="model-breakdown">
            <h2>Model Breakdown</h2>
            <div class="chart-row">
                <canvas id="model-pie-chart"></canvas>
                <canvas id="model-bar-chart"></canvas>
            </div>
        </section>

        <!-- Section 5: Cron vs Interactive -->
        <section id="session-type">
            <h2>Cron vs Interactive Sessions</h2>
            <canvas id="session-type-chart"></canvas>
        </section>

        <!-- Section 6: Top Sessions Table -->
        <section id="top-sessions">
            <h2>Top Sessions by Cost</h2>
            <table id="sessions-table">
                <thead>
                    <tr>
                        <th data-sort="timestamp">Timestamp</th>
                        <th data-sort="session_id">Session ID</th>
                        <th data-sort="type">Type</th>
                        <th data-sort="model">Model</th>
                        <th data-sort="cost">Cost</th>
                        <th data-sort="tokens">Tokens</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- Rows generated from data -->
                </tbody>
            </table>
        </section>

        <!-- Section 7: Anomaly Flags -->
        <section id="anomalies">
            <h2>Anomaly Flags</h2>
            <div id="anomaly-list">
                <!-- Flag cards for Sonnet/Opus usage -->
            </div>
        </section>
    </main>

    <footer>
        <p>Data from: {session_count} sessions, {message_count} messages</p>
    </footer>

    <script>
        // Chart.js configurations embedded here
        // Sortable table logic
    </script>
</body>
</html>
```

### 3.2 Chart.js Configurations

#### Daily Spend Chart (Stacked Bar)
```javascript
new Chart(ctx, {
    type: 'bar',
    data: {
        labels: ['2026-03-01', '2026-03-02', ...],  // Dates
        datasets: [
            {
                label: 'Moonshot',
                data: [1.23, 2.34, ...],
                backgroundColor: '#4c8bf5',
                stack: 'stack0'
            },
            {
                label: 'Anthropic',
                data: [0.45, 0.67, ...],
                backgroundColor: '#d97706',
                stack: 'stack0'
            }
        ]
    },
    options: {
        responsive: true,
        scales: {
            x: { stacked: true },
            y: {
                stacked: true,
                ticks: {
                    callback: (value) => '$' + value.toFixed(2)
                }
            }
        }
    }
});
```

#### Model Breakdown (Pie)
```javascript
new Chart(ctx, {
    type: 'pie',
    data: {
        labels: ['kimi-k2.5', 'claude-sonnet-4-5', ...],
        datasets: [{
            data: [45.67, 12.34, ...],  // Costs
            backgroundColor: ['#4c8bf5', '#d97706', '#10b981', ...]
        }]
    },
    options: {
        responsive: true,
        plugins: {
            tooltip: {
                callbacks: {
                    label: (context) => {
                        const cost = context.parsed;
                        const percent = (cost / total * 100).toFixed(1);
                        return `$${cost.toFixed(2)} (${percent}%)`;
                    }
                }
            }
        }
    }
});
```

#### Model Breakdown (Horizontal Bar)
```javascript
new Chart(ctx, {
    type: 'bar',
    data: {
        labels: ['kimi-k2.5', 'claude-sonnet-4-5', ...],
        datasets: [{
            label: 'Cost (USD)',
            data: [45.67, 12.34, ...],
            backgroundColor: '#4c8bf5'
        }]
    },
    options: {
        indexAxis: 'y',
        responsive: true,
        scales: {
            x: {
                ticks: {
                    callback: (value) => '$' + value.toFixed(2)
                }
            }
        }
    }
});
```

#### Session Type Chart (Doughnut)
```javascript
new Chart(ctx, {
    type: 'doughnut',
    data: {
        labels: ['Cron', 'Interactive'],
        datasets: [{
            data: [34.56, 23.45],  // Costs
            backgroundColor: ['#8b5cf6', '#10b981']
        }]
    },
    options: {
        responsive: true,
        plugins: {
            legend: { position: 'bottom' }
        }
    }
});
```

### 3.3 Styling Guidelines

**Color Palette**:
- Moonshot: `#4c8bf5` (blue)
- Anthropic: `#d97706` (orange)
- Cron: `#8b5cf6` (purple)
- Interactive: `#10b981` (green)
- Warning: `#ef4444` (red)
- Background: `#0f172a` (dark blue)
- Cards: `#1e293b` (lighter dark)
- Text: `#f1f5f9` (light gray)

**Responsive Breakpoints**:
- Mobile: < 768px (single column)
- Tablet: 768px - 1024px (2 columns)
- Desktop: > 1024px (3 columns for cards, 2 for charts)

**Typography**:
- Font: System sans-serif stack
- Headings: Bold, larger sizes
- Monospace: Session IDs, timestamps

## 4. Error Handling Strategy

### 4.1 File System Errors

**Issue**: Session directory not found or inaccessible
```python
try:
    session_files = glob.glob(os.path.expanduser(config.session_dir) + '/*.jsonl')
except FileNotFoundError:
    logger.error(f"Session directory not found: {config.session_dir}")
    # Create empty dashboard with error message
    generate_error_dashboard("Session directory not found")
    sys.exit(1)
```

**Handling**:
- Log error with full path
- Generate HTML with error message prominently displayed
- Exit with code 1

### 4.2 JSONL Parsing Errors

**Issue**: Malformed JSON lines in session files
```python
for line in file:
    try:
        event = json.loads(line)
        # Process event
    except json.JSONDecodeError as e:
        logger.warning(f"Skipping malformed line in {filename}:{line_num}: {e}")
        continue  # Skip this line, continue processing
```

**Handling**:
- Warn about specific file/line
- Skip malformed lines
- Continue processing remaining data
- Report parsing errors in dashboard footer

### 4.3 API Errors

**Issue**: Moonshot API unavailable or authentication failure
```python
try:
    response = requests.get(
        'https://api.moonshot.cn/v1/users/me',
        headers={'Authorization': f'Bearer {api_key}'},
        timeout=10
    )
    response.raise_for_status()
    balance = response.json()['balance']
except requests.RequestException as e:
    logger.error(f"Failed to fetch Moonshot balance: {e}")
    balance = None  # Display "N/A" in dashboard
```

**Handling**:
- Log error with details
- Display "N/A" or "Unavailable" in balance card
- Add warning icon/message
- Dashboard still generates with remaining data

### 4.4 Missing Configuration

**Issue**: Required env vars not set
```python
moonshot_key = os.getenv('MOONSHOT_API_KEY')
if not moonshot_key:
    logger.warning("MOONSHOT_API_KEY not set, balance will not be fetched")
    # Proceed without live balance
```

**Handling**:
- Warn about missing config
- Use defaults where possible
- Skip optional features (like live balance)
- Dashboard still generates

### 4.5 Data Validation Errors

**Issue**: Invalid/missing fields in parsed data
```python
def validate_usage(usage: dict) -> bool:
    required_fields = ['input', 'output', 'cost']
    for field in required_fields:
        if field not in usage:
            return False
    if not isinstance(usage['cost'].get('total'), (int, float)):
        return False
    return True

if not validate_usage(message.get('usage', {})):
    logger.debug(f"Invalid usage data in message {msg_id}, skipping")
    continue
```

**Handling**:
- Validate critical fields before processing
- Log validation failures at DEBUG level
- Skip invalid records
- Count skipped records, report in dashboard

### 4.6 Empty Dataset

**Issue**: No valid sessions found in time range
```python
if not sessions:
    logger.warning("No sessions found in specified time range")
    generate_empty_dashboard()
    sys.exit(0)
```

**Handling**:
- Generate dashboard with empty charts
- Display "No data available" message
- Show date range searched
- Exit gracefully (code 0)

### 4.7 Logging Strategy

**Configuration**:
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dashboard_generation.log'),
        logging.StreamHandler()
    ]
)
```

**Log Levels**:
- `ERROR`: Critical failures preventing generation
- `WARNING`: Non-critical issues (missing balance, malformed lines)
- `INFO`: Progress updates (files processed, charts generated)
- `DEBUG`: Detailed processing info (skipped records, validation)

## 5. Configuration Approach

### 5.1 Environment Variables (.env)

**File**: `/home/d-tuned/openclaw-usage-dashboard/.env`

```bash
# API Keys
MOONSHOT_API_KEY=sk-...

# Budget Settings
MONTHLY_BUDGET_USD=100.0
WARNING_THRESHOLD_USD=75.0

# Exchange Rate (optional, defaults to 0.14)
CNY_TO_USD_RATE=0.14

# Data Source (optional, defaults to ~/.openclaw/agents/main/sessions)
SESSION_DIR=/home/d-tuned/.openclaw/agents/main/sessions

# Time Range (optional, defaults to 30 days)
DAYS_BACK=30

# Output File (optional, defaults to dashboard.html)
OUTPUT_FILE=dashboard.html
```

**Loading**:
```python
from dotenv import load_dotenv
import os

load_dotenv()

config = Config(
    moonshot_api_key=os.getenv('MOONSHOT_API_KEY', ''),
    monthly_budget_usd=float(os.getenv('MONTHLY_BUDGET_USD', '100.0')),
    warning_threshold_usd=float(os.getenv('WARNING_THRESHOLD_USD', '75.0')),
    cny_to_usd_rate=float(os.getenv('CNY_TO_USD_RATE', '0.14')),
    session_dir=os.getenv('SESSION_DIR', '~/.openclaw/agents/main/sessions'),
    days_back=int(os.getenv('DAYS_BACK', '30')),
    output_file=os.getenv('OUTPUT_FILE', 'dashboard.html')
)
```

### 5.2 Command-Line Arguments

**Usage**:
```bash
python3 generate_dashboard.py [OPTIONS]
```

**Options**:
```python
import argparse

parser = argparse.ArgumentParser(
    description='Generate OpenClaw token usage dashboard'
)
parser.add_argument(
    '-o', '--output',
    default='dashboard.html',
    help='Output HTML file path (default: dashboard.html)'
)
parser.add_argument(
    '-d', '--days',
    type=int,
    default=30,
    help='Number of days to analyze (default: 30)'
)
parser.add_argument(
    '--session-dir',
    default='~/.openclaw/agents/main/sessions',
    help='Session files directory'
)
parser.add_argument(
    '--no-api',
    action='store_true',
    help='Skip live API balance fetch'
)
parser.add_argument(
    '-v', '--verbose',
    action='store_true',
    help='Enable verbose logging'
)
```

**Precedence** (highest to lowest):
1. CLI arguments
2. Environment variables
3. Defaults

### 5.3 Cron Integration

**Example crontab entry**:
```bash
# Generate dashboard daily at 6 AM
0 6 * * * cd /home/d-tuned/openclaw-usage-dashboard && python3 generate_dashboard.py -o /var/www/html/dashboard.html

# Or with custom time range
0 6 * * * cd /home/d-tuned/openclaw-usage-dashboard && python3 generate_dashboard.py --days 90 -o dashboard_90d.html
```

**Considerations**:
- Use absolute paths in cron
- Redirect output to log: `>> generation.log 2>&1`
- Set proper permissions for output directory
- .env file must be readable by cron user

## 6. Processing Flow

```
1. Load Configuration
   ├─ Read .env file
   ├─ Parse CLI arguments
   └─ Merge with defaults

2. Discover Session Files
   ├─ Scan session directory
   ├─ Filter *.jsonl (exclude .deleted, .reset)
   └─ Sort by modification time

3. Parse Sessions
   ├─ For each session file:
   │  ├─ Read line-by-line (JSONL)
   │  ├─ Extract session metadata
   │  ├─ Detect session type (cron/interactive)
   │  ├─ Aggregate usage per session
   │  └─ Detect anomalies (Sonnet/Opus)
   └─ Build SessionData objects

4. Aggregate Data
   ├─ Group by date → DailySummary
   ├─ Group by model → ModelBreakdown
   ├─ Group by session_type → SessionTypeSummary
   └─ Sort sessions by cost → Top Sessions

5. Fetch Live Balance
   ├─ Call Moonshot API (if key provided)
   ├─ Convert CNY to USD
   └─ Calculate Anthropic spend from logs

6. Calculate Budget Progress
   ├─ Sum current month costs
   ├─ Compare to budget
   └─ Flag if over warning threshold

7. Generate HTML
   ├─ Render live balance cards
   ├─ Render budget tracker
   ├─ Embed Chart.js data
   │  ├─ Daily spend chart
   │  ├─ Model pie/bar charts
   │  └─ Session type chart
   ├─ Render top sessions table
   ├─ Render anomaly flags
   └─ Add footer metadata

8. Write Output
   ├─ Write dashboard.html
   ├─ Log generation summary
   └─ Exit with code 0
```

## 7. Key Technical Decisions

### 7.1 Why Single Python Script?
**Decision**: All logic in one file (generate_dashboard.py)
**Rationale**:
- Simplifies deployment (no package structure)
- Easy to run manually or via cron
- Minimal dependencies (stdlib + requests)
- Self-contained for version control

**Trade-offs**:
- Harder to unit test individual components
- May become large (500-800 lines estimated)
- Mitigated by clear function separation

### 7.2 Why Static HTML?
**Decision**: Generate static HTML, no backend server
**Rationale**:
- No runtime dependencies (no Flask/FastAPI)
- Can be viewed offline
- Easy to serve (nginx, Python http.server, or file://)
- Faster load times

**Trade-offs**:
- No live updates (must regenerate)
- No interactive filtering (unless JS-only)
- Mitigated by cron regeneration

### 7.3 Why Chart.js from CDN?
**Decision**: Use CDN-hosted Chart.js (not bundled)
**Rationale**:
- Zero local dependencies
- Always latest version (specify version in URL)
- Faster initial page load (browser cache)

**Trade-offs**:
- Requires internet connection
- CDN downtime affects dashboard
- Mitigated by version pinning (4.4.0)

### 7.4 Why Not Database?
**Decision**: Parse JSONL files directly, no SQLite/DB
**Rationale**:
- Source of truth is already on disk (JSONL)
- Avoids sync issues
- Simpler architecture

**Trade-offs**:
- Slower for large datasets (>10k sessions)
- Must parse all files on each run
- Mitigated by filtering recent files first

### 7.5 Anomaly Detection Strategy
**Decision**: Flag any Sonnet/Opus usage as anomaly
**Rationale**:
- These models are fallbacks in OpenClaw
- Their presence indicates primary model (Kimi) unavailable
- Helps identify cost spikes

**Alternative Considered**:
- Statistical anomaly detection (> 2σ from mean)
- Rejected: Too complex for v1, harder to explain

### 7.6 Currency Handling
**Decision**: Store all costs in USD internally
**Rationale**:
- Simplifies aggregation across providers
- USD is common reporting currency
- Display both CNY and USD for Moonshot balance

**Trade-offs**:
- Exchange rate fluctuations
- Mitigated by configurable rate, daily updates

## 8. Dependencies

### 8.1 Python Standard Library
- `json`: JSONL parsing
- `datetime`: Timestamp handling
- `dataclasses`: Data structures
- `argparse`: CLI arguments
- `logging`: Error/progress logging
- `os`, `sys`, `glob`: File operations
- `pathlib`: Path handling

### 8.2 External Packages (pip)
- `requests`: Moonshot API calls
- `python-dotenv`: .env file loading

**Installation**:
```bash
pip3 install requests python-dotenv
```

## 9. Security Considerations

### 9.1 API Key Protection
- Store in .env (gitignored)
- Never hardcode in script
- File permissions: `chmod 600 .env`
- Warn if .env is world-readable

### 9.2 HTML Injection Prevention
- Escape all user-generated content (session IDs, timestamps)
- Use parameterized HTML generation
- No eval() or innerHTML with untrusted data

### 9.3 File System Access
- Validate session_dir is under home directory
- Prevent directory traversal (../../../etc/passwd)
- Check file permissions before reading

## 10. Testing Strategy (Out of Scope for Architecture)

**Note**: Implementation phase should include:
- Unit tests for parsing functions
- Integration test with sample JSONL
- Mock API responses for testing
- Edge case handling (empty files, zero costs)

## 11. Future Enhancements (Out of Scope for V1)

- Real-time updates (WebSocket streaming)
- Historical comparisons (month-over-month)
- Cost forecasting (linear regression)
- Export to CSV/JSON
- User-defined date range picker (JS)
- Model-specific token breakdowns
- Session detail drill-down
- Alert notifications (email/webhook on budget exceeded)

## 12. Definition of Done

- [x] File structure defined
- [x] Data model/schema documented
- [x] HTML/Chart.js structure designed
- [x] Error handling strategy documented
- [x] Configuration approach documented
- [ ] Architecture reviewed by Spec Writer
- [ ] Ready for implementation phase

## Document Metadata

- **Author**: Claude (Architect Agent)
- **Date**: 2026-03-17
- **Version**: 1.0
- **Status**: Draft - Awaiting Review
- **Next Phase**: Spec Writer to formalize into implementation spec
