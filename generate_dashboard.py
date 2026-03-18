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
from datetime import datetime, date, timedelta
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


# ============================================================================
# SLICE 1: DATA PARSING
# ============================================================================


def detect_session_type(message_content: str) -> str:
    """
    Detect if session is cron or interactive.

    Cron sessions have "[cron:" prefix in message content.

    Args:
        message_content: Message content string

    Returns:
        "cron" or "interactive"
    """
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

                # Extract provider and model (use first message's values)
                if provider is None:
                    provider = message.get("provider", "unknown")
                if model is None:
                    model = message.get("model", "unknown")

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

    return SessionData(
        session_id=session_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        session_type=session_type or "interactive",
        provider=provider or "unknown",
        model=model or "unknown",
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
    cutoff_date = datetime.now() - timedelta(days=config.days_back)

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
    moonshot_balance_cny_display = (
        "N/A"
        if data.moonshot_balance_cny is None
        else f"¥{data.moonshot_balance_cny:,.0f}"
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
        timestamp_display = session.start_timestamp.strftime("%Y-%m-%d %H:%M")
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
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"><\/script>
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
                    <div class="card-label">Moonshot Balance</div>
                    <div class="card-value">{html.escape(moonshot_balance_display)}</div>
                    <div class="card-label" style="margin-top: 0.5rem;">{html.escape(moonshot_balance_cny_display)}</div>
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
                <div class="budget-bar{' warning' if data.monthly_spend >= data.warning_threshold else ''}" style="width: {budget_percent}%"><\/div>
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
                <canvas id="daily-chart"><\/canvas>
            </div>
        </section>

        <!-- Section 4: Model Breakdown -->
        <section id="model-breakdown">
            <h2>Model Breakdown</h2>
            <div class="charts-grid">
                <div class="chart-container">
                    <canvas id="model-pie-chart"><\/canvas>
                </div>
                <div class="chart-container">
                    <canvas id="model-bar-chart"><\/canvas>
                </div>
            </div>
        </section>

        <!-- Section 5: Session Type -->
        <section id="session-type">
            <h2>Session Type Summary</h2>
            <div class="chart-container">
                <canvas id="session-type-chart"><\/canvas>
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
    <\/script>
</body>
</html>"""

    return html_content


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    """Main entry point."""
    setup_logging()
    logging.info("Starting token usage dashboard generation")

    # For now, just implement Slice 1 parsing
    # Return success
    return 0


if __name__ == "__main__":
    sys.exit(main())
