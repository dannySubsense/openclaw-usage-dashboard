#!/usr/bin/env python3
"""
OpenClaw Token Usage Dashboard Generator

A single-file Python script that parses session JSONL files and generates
a static HTML dashboard with token usage analytics.
"""

import argparse
import html
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
import pytz
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

# ============================================================================
# DATA STRUCTURES
# ============================================================================


@dataclass
class SessionData:
    """Aggregated data for a single session."""

    session_id: str
    start_timestamp: datetime
    end_timestamp: datetime
    session_type: str  # "cron" or "interactive"
    provider: str  # "moonshot" or "anthropic"
    model: str
    total_input: int
    total_output: int
    total_cache_read: int
    total_cache_write: int
    total_cost: float  # USD
    message_count: int


@dataclass
class DailySummary:
    """Aggregated daily spend."""

    date: date
    moonshot_cost: float
    anthropic_cost: float
    total_cost: float
    message_count: int
    session_count: int


@dataclass
class ModelBreakdown:
    """Cost breakdown by model."""

    model: str
    provider: str
    total_cost: float
    message_count: int
    token_count: int


@dataclass
class AnomalyFlag:
    """Flagged anomaly (Sonnet/Opus usage)."""

    session_id: str
    timestamp: datetime
    model: str
    reason: str
    cost: float


@dataclass
class Config:
    """Application configuration."""

    session_dir: str = "~/.openclaw/agents/main/sessions"
    output_file: str = "dashboard.html"
    moonshot_api_key: str = ""
    monthly_budget_usd: float = 100.0
    warning_threshold_usd: float = 75.0
    cny_to_usd_rate: float = 0.14
    days_back: int = 30
    skip_api: bool = False
    verbose: bool = False


@dataclass
class DashboardData:
    """Complete aggregated dashboard data."""

    moonshot_balance_cny: Optional[float]
    moonshot_balance_usd: Optional[float]
    anthropic_total_usd: float
    monthly_spend: float
    monthly_budget: float
    warning_threshold: float
    daily_summaries: List[DailySummary]
    model_breakdown: List[ModelBreakdown]
    session_type_summary: Dict[str, float]
    top_sessions: List[SessionData]
    anomalies: List[AnomalyFlag]
    generated_at: datetime
    total_sessions: int
    total_messages: int
    parse_errors: int


# ============================================================================
# LOGGING SETUP
# ============================================================================


def setup_logging(verbose: bool = False) -> None:
    """Configure logging to file and console."""
    level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s - %(levelname)s - %(message)s"

    # File handler
    file_handler = logging.FileHandler("dashboard_generation.log")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(log_format))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(log_format))

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def check_env_file_permissions() -> None:
    """Check if .env file is world-readable and warn if so."""
    env_path = Path(".env")
    if not env_path.exists():
        return

    try:
        stat_info = env_path.stat()
        # Check if world-readable (0o004 bit set)
        if stat_info.st_mode & 0o004:
            logging.warning(
                f"Security warning: {env_path} is world-readable. "
                "Consider changing permissions to 600 (chmod 600 .env)"
            )
    except OSError as e:
        logging.warning(f"Could not check .env permissions: {e}")


def generate_error_dashboard(error_message: str, output_file: str) -> None:
    """
    Generate minimal error dashboard for critical failures.

    Args:
        error_message: Error message to display
        output_file: Path where error dashboard should be written
    """
    error_html = f"""<!DOCTYPE html>
<html>
<head><title>Dashboard Error</title></head>
<body style="font-family: sans-serif; padding: 2rem;">
    <h1>Error Generating Dashboard</h1>
    <p style="color: red;">{html.escape(error_message)}</p>
    <p>Please check the configuration and try again.</p>
</body>
</html>"""

    try:
        with open(output_file, "w") as f:
            f.write(error_html)
        logging.info(f"Error dashboard written to {output_file}")
    except (IOError, OSError) as e:
        logging.error(f"Failed to write error dashboard to {output_file}: {e}")


# ============================================================================
# SLICE 1: DATA PARSING
# ============================================================================


def detect_session_type(message_content) -> str:
    """
    Detect if session is cron or interactive.

    Cron sessions have "[cron:" prefix in message content.

    Args:
        message_content: Message content (string or list of content blocks)

    Returns:
        "cron" or "interactive"
    """
    # Handle list of content blocks (e.g., [{"type": "text", "text": "..."}])
    if isinstance(message_content, list):
        for block in message_content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text and text.strip().startswith("[cron:"):
                    return "cron"
    # Handle string content
    elif isinstance(message_content, str):
        if message_content and message_content.strip().startswith("[cron:"):
            return "cron"

    return "interactive"


def parse_session_file(filepath: str) -> Optional[SessionData]:
    """
    Parse a single JSONL session file.

    Reads line-by-line, extracts message events with usage data,
    and aggregates into SessionData.

    Args:
        filepath: Path to .jsonl session file

    Returns:
        SessionData object or None if file is empty/invalid
    """
    path = Path(filepath)
    session_id = path.stem  # filename without .jsonl

    # Initialize aggregation variables
    start_timestamp = None
    end_timestamp = None
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    total_cost = 0.0
    message_count = 0
    provider = None
    model = None
    session_type = None
    model_costs = {}  # Track cost per model for accurate attribution

    try:
        with open(filepath, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError as e:
                    logging.warning(f"Malformed JSON in {filepath}:{line_num}: {e}")
                    continue

                # Only process message events
                if event.get("type") != "message":
                    continue

                message = event.get("message", {})
                usage = message.get("usage", {})

                # Skip messages without cost data
                cost_data = usage.get("cost", {})
                if "total" not in cost_data:
                    continue

                # Track timestamps
                try:
                    timestamp_str = event.get("timestamp")
                    if timestamp_str:
                        ts = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                        if start_timestamp is None:
                            start_timestamp = ts
                        end_timestamp = ts
                except (ValueError, AttributeError) as e:
                    logging.warning(f"Invalid timestamp in {filepath}:{line_num}: {e}")
                    continue

                # Extract provider from first message
                if provider is None:
                    provider = message.get("provider", "unknown")

                # Track cost per model for accurate attribution
                msg_model = message.get("model", "unknown")
                msg_cost = cost_data.get("total", 0.0)
                model_costs[msg_model] = model_costs.get(msg_model, 0) + msg_cost

                # Detect session type from first message content
                if session_type is None:
                    content = message.get("content", "")
                    session_type = detect_session_type(content)

                # Aggregate token counts
                total_input += usage.get("input", 0)
                total_output += usage.get("output", 0)
                total_cache_read += usage.get("cacheRead", 0)
                total_cache_write += usage.get("cacheWrite", 0)
                total_cost += cost_data.get("total", 0.0)
                message_count += 1

    except IOError as e:
        logging.error(f"Error reading file {filepath}: {e}")
        return None

    # Return None if no valid messages found
    if message_count == 0:
        return None

    # Attribute session to model with highest total cost
    if model_costs:
        model = max(model_costs, key=model_costs.get)
    else:
        model = "unknown"

    return SessionData(
        session_id=session_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        session_type=session_type or "interactive",
        provider=provider or "unknown",
        model=model,
        total_input=total_input,
        total_output=total_output,
        total_cache_read=total_cache_read,
        total_cache_write=total_cache_write,
        total_cost=total_cost,
        message_count=message_count,
    )


def parse_all_sessions(config: Config) -> List[SessionData]:
    """
    Discover and parse all session files.

    Filters out *.deleted.* and *.reset.* files.

    Args:
        config: Configuration object

    Returns:
        List of SessionData objects
    """
    session_dir = Path(config.session_dir).expanduser()

    if not session_dir.exists():
        logging.error(f"Session directory not found: {session_dir}")
        return []

    sessions = []
    # Use timezone-aware datetime for comparison
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=config.days_back)

    # Find all .jsonl files
    jsonl_files = sorted(session_dir.glob("*.jsonl"))

    for jsonl_path in jsonl_files:
        filename = jsonl_path.name

        # Skip deleted and reset files
        if ".deleted." in filename or ".reset." in filename:
            logging.debug(f"Skipping filtered file: {filename}")
            continue

        # Parse the file
        session_data = parse_session_file(str(jsonl_path))
        if session_data:
            # Filter by date
            if session_data.start_timestamp >= cutoff_date:
                sessions.append(session_data)
            else:
                logging.debug(
                    f"Skipping session {session_data.session_id} "
                    f"(outside time range)"
                )

    logging.info(f"Parsed {len(sessions)} sessions from {session_dir}")
    return sessions


# ============================================================================
# SLICE 2: HTML/CHART.JS GENERATION
# ============================================================================

# Color Palette
COLOR_PALETTE = {
    "moonshot": "#4c8bf5",
    "anthropic": "#d97706",
    "cron": "#8b5cf6",
    "interactive": "#10b981",
    "warning": "#ef4444",
    "background": "#0f172a",
    "cards": "#1e293b",
    "text": "#f1f5f9",
    "borders": "#475569",
}


def generate_html(data: DashboardData) -> str:
    """
    Generate static HTML5 dashboard with embedded Chart.js.

    Args:
        data: DashboardData object with aggregated metrics

    Returns:
        Valid HTML5 string
    """
    # Generate timestamp
    generated_time = data.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    # Prepare chart data
    daily_labels = []
    daily_moonshot = []
    daily_anthropic = []
    for summary in data.daily_summaries:
        daily_labels.append(summary.date.isoformat())
        daily_moonshot.append(summary.moonshot_cost)
        daily_anthropic.append(summary.anthropic_cost)

    # Model breakdown data
    model_labels = []
    model_costs = []
    model_colors = []
    for breakdown in sorted(
        data.model_breakdown, key=lambda x: x.total_cost, reverse=True
    ):
        model_labels.append(breakdown.model)
        model_costs.append(breakdown.total_cost)
        # Assign colors from palette, cycling if needed
        color_map = {
            "kimi": COLOR_PALETTE["moonshot"],
            "claude": COLOR_PALETTE["anthropic"],
        }
        color = next(
            (v for k, v in color_map.items() if k in breakdown.model.lower()),
            COLOR_PALETTE["warning"],
        )
        model_colors.append(color)

    # Session type data
    session_type_labels = []
    session_type_data = []
    session_type_colors = []
    for session_type, cost in sorted(
        data.session_type_summary.items(), key=lambda x: x[1], reverse=True
    ):
        session_type_labels.append(session_type.capitalize())
        session_type_data.append(cost)
        color = (
            COLOR_PALETTE["cron"]
            if session_type == "cron"
            else COLOR_PALETTE["interactive"]
        )
        session_type_colors.append(color)

    # Format balance display
    moonshot_balance_display = (
        "N/A"
        if data.moonshot_balance_usd is None
        else f"${data.moonshot_balance_usd:,.2f}"
    )

    # Format amounts
    anthropic_total_display = f"${data.anthropic_total_usd:,.2f}"
    monthly_spend_display = f"${data.monthly_spend:,.2f}"
    monthly_budget_display = f"${data.monthly_budget:,.2f}"

    # Calculate budget progress
    budget_percent = min(
        (
            (data.monthly_spend / data.monthly_budget * 100)
            if data.monthly_budget > 0
            else 0
        ),
        100,
    )
    budget_color = (
        COLOR_PALETTE["warning"]
        if data.monthly_spend >= data.warning_threshold
        else COLOR_PALETTE["interactive"]
    )

    # Format top sessions table data
    top_sessions_rows = []
    for session in data.top_sessions[:20]:
        # Convert UTC to Singapore time for display
        sg_tz = pytz.timezone('Asia/Singapore')
        timestamp_sg = session.start_timestamp.astimezone(sg_tz)
        timestamp_display = timestamp_sg.strftime("%Y-%m-%d %H:%M")
        cost_display = f"${session.total_cost:.3f}"
        tokens_display = f"{session.total_input + session.total_output:,}"

        top_sessions_rows.append(f"""            <tr>
                <td>{html.escape(timestamp_display)}</td>
                <td>{html.escape(session.session_id)}</td>
                <td>{html.escape(session.session_type)}</td>
                <td>{html.escape(session.model)}</td>
                <td>{html.escape(cost_display)}</td>
                <td>{html.escape(tokens_display)}</td>
            </tr>""")

    top_sessions_table = "\n".join(top_sessions_rows)

    # Format anomalies
    anomaly_cards = []
    for anomaly in sorted(data.anomalies, key=lambda x: x.timestamp, reverse=True):
        timestamp_display = anomaly.timestamp.strftime("%Y-%m-%d %H:%M")
        cost_display = f"${anomaly.cost:.3f}"
        anomaly_cards.append(f"""        <div class="anomaly-card">
            <div class="anomaly-header">
                <span class="anomaly-model">{html.escape(anomaly.model)}</span>
                <span class="anomaly-cost">{html.escape(cost_display)}</span>
            </div>
            <div class="anomaly-details">
                <p><strong>Session:</strong> {html.escape(anomaly.session_id)}</p>
                <p><strong>Timestamp:</strong> {html.escape(timestamp_display)}</p>
                <p><strong>Reason:</strong> {html.escape(anomaly.reason)}</p>
            </div>
        </div>""")

    anomalies_html = (
        "\n".join(anomaly_cards)
        if anomaly_cards
        else '        <p style="color: #10b981;">No anomalies detected</p>'
    )

    # Build the complete HTML
    html_content = rf"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Token Usage Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        :root {{
            --bg-primary: {COLOR_PALETTE["background"]};
            --bg-cards: {COLOR_PALETTE["cards"]};
            --text-primary: {COLOR_PALETTE["text"]};
            --text-secondary: #cbd5e1;
            --border-color: {COLOR_PALETTE["borders"]};
            --color-moonshot: {COLOR_PALETTE["moonshot"]};
            --color-anthropic: {COLOR_PALETTE["anthropic"]};
            --color-cron: {COLOR_PALETTE["cron"]};
            --color-interactive: {COLOR_PALETTE["interactive"]};
            --color-warning: {COLOR_PALETTE["warning"]};
        }}

        html, body {{
            height: 100%;
        }}

        body {{
            background-color: var(--bg-primary);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
        }}

        header {{
            background-color: var(--bg-cards);
            border-bottom: 1px solid var(--border-color);
            padding: 2rem;
            margin-bottom: 2rem;
        }}

        header h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}

        #generated-time {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}

        main {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 1rem 2rem 1rem;
        }}

        section {{
            margin-bottom: 2rem;
            background-color: var(--bg-cards);
            border: 1px solid var(--border-color);
            border-radius: 0.5rem;
            padding: 1.5rem;
        }}

        section h2 {{
            font-size: 1.3rem;
            margin-bottom: 1rem;
            color: var(--text-primary);
        }}

        .grid {{
            display: grid;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}

        .grid-2 {{
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        }}

        .grid-3 {{
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        }}

        .card {{
            background-color: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 0.5rem;
            padding: 1rem;
            text-align: center;
        }}

        .card-label {{
            color: var(--text-secondary);
            font-size: 0.85rem;
            text-transform: uppercase;
            margin-bottom: 0.5rem;
            letter-spacing: 0.05em;
        }}

        .card-value {{
            font-size: 1.75rem;
            font-weight: 600;
            color: var(--text-primary);
        }}

        .card.moonshot {{
            border-left: 4px solid var(--color-moonshot);
        }}

        .card.anthropic {{
            border-left: 4px solid var(--color-anthropic);
        }}

        .budget-bar-container {{
            background-color: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 0.5rem;
            height: 2rem;
            overflow: hidden;
            margin: 1rem 0;
        }}

        .budget-bar {{
            height: 100%;
            transition: width 0.3s ease;
            background-color: var(--color-interactive);
        }}

        .budget-bar.warning {{
            background-color: var(--color-warning);
        }}

        .budget-info {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
            font-size: 0.9rem;
        }}

        .budget-info-item {{
            display: flex;
            justify-content: space-between;
        }}

        .chart-container {{
            position: relative;
            height: 350px;
            margin-bottom: 1rem;
        }}

        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }}

        th {{
            background-color: var(--bg-primary);
            border-bottom: 2px solid var(--border-color);
            padding: 0.75rem;
            text-align: left;
            font-weight: 600;
            color: var(--text-primary);
            cursor: pointer;
            user-select: none;
        }}

        th:hover {{
            background-color: rgba(255, 255, 255, 0.05);
        }}

        td {{
            padding: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }}

        tr:hover {{
            background-color: rgba(255, 255, 255, 0.02);
        }}

        .anomaly-card {{
            background-color: var(--bg-primary);
            border-left: 4px solid var(--color-warning);
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--color-warning);
            border-radius: 0.5rem;
            padding: 1rem;
            margin-bottom: 1rem;
        }}

        .anomaly-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }}

        .anomaly-model {{
            font-weight: 600;
            color: var(--color-warning);
        }}

        .anomaly-cost {{
            color: var(--text-secondary);
        }}

        .anomaly-details p {{
            margin: 0.25rem 0;
            font-size: 0.9rem;
        }}

        footer {{
            background-color: var(--bg-cards);
            border-top: 1px solid var(--border-color);
            padding: 1.5rem 2rem;
            text-align: center;
            color: var(--text-secondary);
            margin-top: 2rem;
        }}

        /* Responsive Design */
        @media (max-width: 1024px) {{
            main {{
                padding: 0 1rem;
            }}

            .grid-3 {{
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            }}

            .charts-grid {{
                grid-template-columns: 1fr;
            }}

            .chart-container {{
                height: 300px;
            }}
        }}

        @media (max-width: 768px) {{
            header {{
                padding: 1.5rem 1rem;
            }}

            header h1 {{
                font-size: 1.5rem;
            }}

            main {{
                padding: 0 0.75rem;
            }}

            section {{
                padding: 1rem;
                margin-bottom: 1.5rem;
            }}

            section h2 {{
                font-size: 1.1rem;
            }}

            .grid {{
                gap: 1rem;
            }}

            .grid-2, .grid-3 {{
                grid-template-columns: 1fr;
            }}

            .card-value {{
                font-size: 1.4rem;
            }}

            .charts-grid {{
                grid-template-columns: 1fr;
                gap: 1rem;
            }}

            .chart-container {{
                height: 250px;
            }}

            table {{
                font-size: 0.85rem;
            }}

            th, td {{
                padding: 0.5rem;
            }}

            .anomaly-header {{
                flex-direction: column;
                align-items: flex-start;
            }}

            .anomaly-cost {{
                margin-top: 0.5rem;
            }}

            footer {{
                padding: 1rem;
                font-size: 0.85rem;
            }}
        }}

        @media (max-width: 480px) {{
            header h1 {{
                font-size: 1.2rem;
            }}

            section h2 {{
                font-size: 1rem;
            }}

            .card-value {{
                font-size: 1.2rem;
            }}

            table {{
                font-size: 0.75rem;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>OpenClaw Token Usage Dashboard</h1>
        <div id="generated-time">Generated: {html.escape(generated_time)}</div>
    </header>

    <main>
        <!-- Section 1: Live Balance Cards -->
        <section id="live-balance">
            <h2>Live Balance</h2>
            <div class="grid grid-2">
                <div class="card moonshot">
                    <div class="card-label">Moonshot Balance (Remaining)</div>
                    <div class="card-value">{html.escape(moonshot_balance_display)}</div>
                </div>
                <div class="card anthropic">
                    <div class="card-label">Anthropic Spend</div>
                    <div class="card-value">{html.escape(anthropic_total_display)}</div>
                </div>
            </div>
        </section>

        <!-- Section 2: Budget Tracker -->
        <section id="budget-tracker">
            <h2>Monthly Budget</h2>
            <div class="budget-bar-container">
                <div class="budget-bar{' warning' if data.monthly_spend >= data.warning_threshold else ''}" style="width: {budget_percent}%"></div>
            </div>
            <div class="budget-info">
                <div class="budget-info-item">
                    <span>Spent:</span>
                    <span>{html.escape(monthly_spend_display)}</span>
                </div>
                <div class="budget-info-item">
                    <span>Budget:</span>
                    <span>{html.escape(monthly_budget_display)}</span>
                </div>
                <div class="budget-info-item">
                    <span>Progress:</span>
                    <span>{budget_percent:.1f}%</span>
                </div>
            </div>
        </section>

        <!-- Section 3: Daily Spend Chart -->
        <section id="daily-spend">
            <h2>Daily Spend</h2>
            <div class="chart-container">
                <canvas id="daily-chart"></canvas>
            </div>
        </section>

        <!-- Section 4: Model Breakdown -->
        <section id="model-breakdown">
            <h2>Model Breakdown</h2>
            <div class="charts-grid">
                <div class="chart-container">
                    <canvas id="model-pie-chart"></canvas>
                </div>
                <div class="chart-container">
                    <canvas id="model-bar-chart"></canvas>
                </div>
            </div>
        </section>

        <!-- Section 5: Session Type -->
        <section id="session-type">
            <h2>Session Type Summary</h2>
            <div class="chart-container">
                <canvas id="session-type-chart"></canvas>
            </div>
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
{top_sessions_table}
                </tbody>
            </table>
        </section>

        <!-- Section 7: Anomalies -->
        <section id="anomalies">
            <h2>Anomaly Flags</h2>
{anomalies_html}
        </section>
    </main>

    <footer>
        <p>Data from: {data.total_sessions} sessions, {data.total_messages} messages</p>
    </footer>

    <script>
        // Chart.js initialization (placeholders for Slice 3)

        // Daily Spend Chart
        const dailyCtx = document.getElementById('daily-chart').getContext('2d');
        const dailyChart = new Chart(dailyCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(daily_labels)},
                datasets: [
                    {{
                        label: 'Moonshot',
                        data: {json.dumps(daily_moonshot)},
                        backgroundColor: '{COLOR_PALETTE["moonshot"]}',
                        stack: 'stack0'
                    }},
                    {{
                        label: 'Anthropic',
                        data: {json.dumps(daily_anthropic)},
                        backgroundColor: '{COLOR_PALETTE["anthropic"]}',
                        stack: 'stack0'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        labels: {{ color: '{COLOR_PALETTE["text"]}' }}
                    }}
                }},
                scales: {{
                    x: {{
                        stacked: true,
                        ticks: {{ color: '{COLOR_PALETTE["text"]}' }},
                        grid: {{ color: '{COLOR_PALETTE["borders"]}' }}
                    }},
                    y: {{
                        stacked: true,
                        ticks: {{ color: '{COLOR_PALETTE["text"]}' }},
                        grid: {{ color: '{COLOR_PALETTE["borders"]}' }}
                    }}
                }}
            }}
        }});

        // Model Pie Chart
        const pieCtx = document.getElementById('model-pie-chart').getContext('2d');
        const pieChart = new Chart(pieCtx, {{
            type: 'pie',
            data: {{
                labels: {json.dumps(model_labels)},
                datasets: [{{
                    data: {json.dumps(model_costs)},
                    backgroundColor: {json.dumps(model_colors)}
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        labels: {{ color: '{COLOR_PALETTE["text"]}' }}
                    }}
                }}
            }}
        }});

        // Model Bar Chart
        const barCtx = document.getElementById('model-bar-chart').getContext('2d');
        const barChart = new Chart(barCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(model_labels)},
                datasets: [{{
                    label: 'Cost (USD)',
                    data: {json.dumps(model_costs)},
                    backgroundColor: {json.dumps(model_colors)}
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        labels: {{ color: '{COLOR_PALETTE["text"]}' }}
                    }}
                }},
                scales: {{
                    x: {{
                        ticks: {{ color: '{COLOR_PALETTE["text"]}' }},
                        grid: {{ color: '{COLOR_PALETTE["borders"]}' }}
                    }},
                    y: {{
                        ticks: {{ color: '{COLOR_PALETTE["text"]}' }},
                        grid: {{ color: '{COLOR_PALETTE["borders"]}' }}
                    }}
                }}
            }}
        }});

        // Session Type Doughnut Chart
        const doughnutCtx = document.getElementById('session-type-chart').getContext('2d');
        const doughnutChart = new Chart(doughnutCtx, {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(session_type_labels)},
                datasets: [{{
                    data: {json.dumps(session_type_data)},
                    backgroundColor: {json.dumps(session_type_colors)}
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'bottom',
                        labels: {{ color: '{COLOR_PALETTE["text"]}' }}
                    }}
                }}
            }}
        }});

        // Table sorting (placeholder for client-side sorting)
        let currentSort = null;
        let sortDirection = 'asc';

        document.querySelectorAll('th[data-sort]').forEach(th => {{
            th.addEventListener('click', () => {{
                const sortBy = th.dataset.sort;
                if (currentSort === sortBy) {{
                    sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
                }} else {{
                    currentSort = sortBy;
                    sortDirection = 'asc';
                }}
                // Sorting logic would go here (Slice 3)
            }});
        }});
    </script>
</body>
</html>"""

    return html_content


# ============================================================================
# CONFIGURATION LOADING
# ============================================================================


def load_config() -> Config:
    """
    Load configuration from .env file and CLI arguments.

    CLI arguments override environment variables, which override defaults.

    Returns:
        Config object with all settings
    """
    # Load .env file
    load_dotenv()

    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="Generate OpenClaw token usage dashboard"
    )
    parser.add_argument(
        "-o",
        "--output",
        default=os.getenv("OUTPUT_FILE", "dashboard.html"),
        help="Output HTML file (default: dashboard.html)",
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=int(os.getenv("DAYS_BACK", "30")),
        help="Number of days to analyze (default: 30)",
    )
    parser.add_argument(
        "--session-dir",
        default=os.getenv("SESSION_DIR", "~/.openclaw/agents/main/sessions"),
        help="Session files directory",
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="Skip Moonshot API balance fetch",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    # Load configuration with validation
    session_dir = args.session_dir
    output_file = args.output
    days_back = args.days
    verbose = args.verbose

    # Validate and load numeric config values with defaults
    try:
        monthly_budget_usd = float(os.getenv("MONTHLY_BUDGET_USD", "100.0"))
    except (ValueError, TypeError):
        logging.warning("Invalid MONTHLY_BUDGET_USD in .env, using default: 100.0")
        monthly_budget_usd = 100.0

    try:
        warning_threshold_usd = float(os.getenv("WARNING_THRESHOLD_USD", "75.0"))
    except (ValueError, TypeError):
        logging.warning("Invalid WARNING_THRESHOLD_USD in .env, using default: 75.0")
        warning_threshold_usd = 75.0

    try:
        cny_to_usd_rate = float(os.getenv("CNY_TO_USD_RATE", "0.14"))
        if not (0.01 <= cny_to_usd_rate <= 1.0):
            raise ValueError("Rate must be between 0.01 and 1.0")
    except (ValueError, TypeError):
        logging.warning("Invalid CNY_TO_USD_RATE in .env, using default: 0.14")
        cny_to_usd_rate = 0.14

    moonshot_api_key = os.getenv("MOONSHOT_API_KEY", "")
    if not moonshot_api_key:
        logging.warning("MOONSHOT_API_KEY not set, Moonshot balance will show as N/A")

    config = Config(
        session_dir=session_dir,
        output_file=output_file,
        moonshot_api_key=moonshot_api_key,
        monthly_budget_usd=monthly_budget_usd,
        warning_threshold_usd=warning_threshold_usd,
        cny_to_usd_rate=cny_to_usd_rate,
        days_back=days_back,
        skip_api=args.no_api,
        verbose=verbose,
    )

    return config


def validate_output_path(output_file: str) -> bool:
    """
    Validate that output path is writable.

    Args:
        output_file: Path to output file

    Returns:
        True if writable, False otherwise
    """
    output_path = Path(output_file)
    parent_dir = output_path.parent

    # Create parent directory if it doesn't exist
    try:
        parent_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.error(f"Cannot create output directory {parent_dir}: {e}")
        return False

    # Test write permission
    try:
        # Try to write a small test file
        test_file = parent_dir / ".dashboard_write_test"
        test_file.write_text("test")
        test_file.unlink()
        return True
    except OSError as e:
        logging.error(f"Output directory is not writable: {e}")
        return False


# ============================================================================
# DATA AGGREGATION
# ============================================================================


def aggregate_data(sessions: List[SessionData], config: Config) -> DashboardData:
    """
    Aggregate session data into dashboard metrics.

    Args:
        sessions: List of parsed sessions
        config: Configuration object

    Returns:
        DashboardData with aggregated metrics
    """
    # Initialize aggregation structures
    daily_summaries: Dict[date, DailySummary] = {}
    model_breakdown_map: Dict[str, ModelBreakdown] = {}
    session_type_summary: Dict[str, float] = {"cron": 0.0, "interactive": 0.0}
    anomalies: List[AnomalyFlag] = []
    total_anthropic_cost = 0.0
    total_cost = 0.0

    for session in sessions:
        # Daily aggregation
        session_date = session.start_timestamp.date()
        if session_date not in daily_summaries:
            daily_summaries[session_date] = DailySummary(
                date=session_date,
                moonshot_cost=0.0,
                anthropic_cost=0.0,
                total_cost=0.0,
                message_count=0,
                session_count=0,
            )

        daily = daily_summaries[session_date]
        if session.provider == "moonshot":
            daily.moonshot_cost += session.total_cost
        elif session.provider == "anthropic":
            daily.anthropic_cost += session.total_cost
        daily.total_cost += session.total_cost
        daily.message_count += session.message_count
        daily.session_count += 1

        # Model breakdown aggregation
        model_key = session.model
        if model_key not in model_breakdown_map:
            model_breakdown_map[model_key] = ModelBreakdown(
                model=session.model,
                provider=session.provider,
                total_cost=0.0,
                message_count=0,
                token_count=0,
            )

        breakdown = model_breakdown_map[model_key]
        breakdown.total_cost += session.total_cost
        breakdown.message_count += session.message_count
        breakdown.token_count += session.total_input + session.total_output

        # Session type aggregation
        session_type_summary[session.session_type] += session.total_cost

        # Track Anthropic spend
        if session.provider == "anthropic":
            total_anthropic_cost += session.total_cost

        # Detect anomalies (Sonnet/Opus usage)
        if "sonnet" in session.model.lower() or "opus" in session.model.lower():
            anomalies.append(
                AnomalyFlag(
                    session_id=session.session_id,
                    timestamp=session.start_timestamp,
                    model=session.model,
                    reason="Fallback triggered: Kimi unavailable",
                    cost=session.total_cost,
                )
            )

        total_cost += session.total_cost

    # Sort daily summaries by date
    sorted_daily = sorted(daily_summaries.values(), key=lambda x: x.date)

    # Sort sessions by cost (descending) and get top 20
    top_sessions = sorted(sessions, key=lambda x: x.total_cost, reverse=True)[:20]

    return DashboardData(
        moonshot_balance_cny=None,
        moonshot_balance_usd=None,
        anthropic_total_usd=total_anthropic_cost,
        monthly_spend=total_cost,
        monthly_budget=config.monthly_budget_usd,
        warning_threshold=config.warning_threshold_usd,
        daily_summaries=sorted_daily,
        model_breakdown=list(model_breakdown_map.values()),
        session_type_summary=session_type_summary,
        top_sessions=top_sessions,
        anomalies=anomalies,
        generated_at=datetime.now(),
        total_sessions=len(sessions),
        total_messages=sum(s.message_count for s in sessions),
        parse_errors=0,
    )


def fetch_moonshot_balance(api_key: str) -> Optional[float]:
    """
    Fetch live Moonshot balance via API.

    Args:
        api_key: Moonshot API key

    Returns:
        Balance in CNY or None if API fails
    """
    try:
        response = requests.get(
            "https://api.moonshot.ai/v1/users/me/balance",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        balance_cny = data.get("data", {}).get("available_balance")
        if balance_cny is not None:
            logging.info(f"Moonshot balance fetched: ¥{balance_cny:,.0f}")
            return float(balance_cny)
    except requests.exceptions.Timeout:
        logging.error("Moonshot API request timed out")
    except requests.exceptions.RequestException as e:
        logging.error(f"Moonshot API error: {e}")
    except (ValueError, KeyError) as e:
        logging.error(f"Invalid response from Moonshot API: {e}")

    return None


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    """Main entry point with comprehensive error handling."""
    # Load configuration
    config = load_config()

    # Setup logging after loading config to respect verbose flag
    setup_logging(config.verbose)
    logging.info("Starting token usage dashboard generation")

    # Check .env permissions
    check_env_file_permissions()

    # Validate output path
    if not validate_output_path(config.output_file):
        logging.error(f"Invalid output path: {config.output_file}")
        generate_error_dashboard(
            "Invalid output path. Check permissions and try again.",
            config.output_file,
        )
        return 1

    # Validate session directory exists
    session_dir = Path(config.session_dir).expanduser()
    if not session_dir.exists():
        error_msg = f"Session directory not found: {session_dir}"
        logging.error(error_msg)
        generate_error_dashboard(error_msg, config.output_file)
        return 1

    # Parse all sessions
    sessions = parse_all_sessions(config)
    if not sessions:
        logging.warning("No sessions found in time range")

    # Aggregate data
    dashboard_data = aggregate_data(sessions, config)

    # Fetch Moonshot balance (if API key provided and not skipped)
    if config.moonshot_api_key and not config.skip_api:
        balance_usd = fetch_moonshot_balance(config.moonshot_api_key)
        if balance_usd is not None:
            dashboard_data.moonshot_balance_usd = balance_usd
            dashboard_data.moonshot_balance_cny = None
    else:
        if not config.moonshot_api_key:
            logging.info("Skipping Moonshot API: no API key configured")
        else:
            logging.info("Skipping Moonshot API: --no-api flag set")

    # Generate HTML
    try:
        html_content = generate_html(dashboard_data)
    except Exception as e:
        logging.error(f"Error generating HTML: {e}")
        generate_error_dashboard(
            "Failed to generate dashboard HTML. Check logs for details.",
            config.output_file,
        )
        return 1

    # Write output file
    try:
        with open(config.output_file, "w") as f:
            f.write(html_content)
        logging.info(f"Dashboard generated: {config.output_file}")
        logging.info(
            f"Processed {len(sessions)} sessions, "
            f"{dashboard_data.total_messages} messages"
        )
    except (IOError, OSError) as e:
        logging.error(f"Failed to write output file: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
