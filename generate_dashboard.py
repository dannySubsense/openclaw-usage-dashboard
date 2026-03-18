#!/usr/bin/env python3
"""
OpenClaw Token Usage Dashboard Generator

A single-file Python script that parses session JSONL files and generates
a static HTML dashboard with token usage analytics.
"""

import argparse
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
