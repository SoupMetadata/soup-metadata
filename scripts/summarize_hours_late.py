#!/usr/bin/env python3
"""Print recent chapter data and optionally summarize hours_late values."""

import argparse
import sys

import pandas as pd
from chaplib.config import Config


DATA_COLUMNS = ["hours_late", "modifier", "word_count", "chapter"]


def positive_int(value: str) -> int:
    """Parse a positive integer for a command-line argument."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def load_recent_data(csv_path: str) -> pd.DataFrame:
    """Read the columns used by the recent-entry table and summary."""
    return pd.read_csv(csv_path, usecols=DATA_COLUMNS)[DATA_COLUMNS]


def exclude_trailing_entry_without_chapter(data: pd.DataFrame) -> pd.DataFrame:
    """Drop the final row when it does not contain a numeric chapter value."""
    if data.empty:
        return data

    final_chapter = pd.to_numeric(data.iloc[-1]["chapter"], errors="coerce")
    if pd.isna(final_chapter):
        return data.iloc[:-1]
    return data


def format_hours_late(value: float) -> str:
    """Format lateness with a sign, two decimals, and an hour suffix."""
    return f"{value:+.2f} h"


def format_word_count(value: float) -> str:
    """Format word counts with thousands separators and no decimal places."""
    return f"{value:,.0f}"


def format_chapter(value: float) -> str:
    """Format integer chapter numbers without a trailing decimal."""
    return f"{value:g}"


def format_recent_entries(data: pd.DataFrame, last_n: int) -> str:
    """Return a display-ready table containing the most recent N rows."""
    recent = data.tail(last_n).copy()
    recent["hours_late"] = pd.to_numeric(recent["hours_late"], errors="coerce")
    recent["word_count"] = pd.to_numeric(recent["word_count"], errors="coerce")
    recent["chapter"] = pd.to_numeric(recent["chapter"], errors="coerce")
    recent["modifier"] = recent["modifier"].fillna("none")
    recent = recent.rename(columns={
        "hours_late": "Hours late",
        "modifier": "Modifier",
        "word_count": "Word count",
        "chapter": "Chapter",
    })
    return recent.to_string(
        index=False,
        na_rep="—",
        formatters={
            "Hours late": format_hours_late,
            "Word count": format_word_count,
            "Chapter": format_chapter,
        },
    )


def parse_args() -> argparse.Namespace:
    """Parse output selections and load the default CSV path from config."""
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="YAML config file (default: config.yaml)",
    )
    pre, _ = config_parser.parse_known_args()
    cfg = Config.load(pre.config)

    parser = argparse.ArgumentParser(
        parents=[config_parser],
        description=(
            "Print recent chapter data and optionally summarize recent "
            "hours_late values."
        ),
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=cfg.get("path.intermediary"),
        help="CSV file to read (default: path.intermediary from config)",
    )
    parser.add_argument(
        "--last-n",
        "--last-k",
        dest="last_n",
        type=positive_int,
        metavar="N",
        help=(
            "number of recent entries to print; --last-k is retained as an "
            "alias for compatibility"
        ),
    )
    parser.add_argument(
        "--summary-n",
        type=positive_int,
        metavar="N",
        help="print hours_late statistics for the most recent N entries",
    )
    args = parser.parse_args()
    if args.last_n is None and args.summary_n is None:
        parser.error("at least one of --last-n/--last-k or --summary-n is required")
    return args


def main() -> int:
    args = parse_args()

    try:
        data = load_recent_data(args.csv_file)
    except (FileNotFoundError, PermissionError, pd.errors.ParserError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    data = exclude_trailing_entry_without_chapter(data)

    if args.last_n is not None:
        print(f"Last {args.last_n} entries:")
        print(format_recent_entries(data, args.last_n))

    if args.summary_n is not None:
        if args.last_n is not None:
            print()
        summary_values = pd.to_numeric(
            data["hours_late"].tail(args.summary_n), errors="coerce"
        )
        print(f"Hours-late statistics for the last {args.summary_n} entries:")
        summary = summary_values.describe()
        print(summary.to_string(float_format=lambda value: f"{value:.2f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
