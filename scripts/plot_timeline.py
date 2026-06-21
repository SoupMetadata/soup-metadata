"""
plot_timeline.py — Plot chapter release rate from a timeline CSV.

All parameters are read from config.yaml by default; CLI flags override them.

Config keys (under the `plot` section):
    plot:
      csv: data/patreon/timeline.csv
      chapters_csv: data/chapters.csv   # optional; enables the second and third plots
      window: 10                        # rolling window in IRL days for chapters/day plot
      pacing_window: 10                 # rolling window in in-story days for pacing-rate plot
      output: chart.png                 # omit to display interactively

Plots produced:
  1. Chapters/day release rate (SMA over --window IRL days) — always shown.
  2. IRL publish date vs. in-story date — requires --chapters-csv.
  3. Pacing rate (IRL days / in-story day, derivative of plot 2) — requires --chapters-csv.

Usage:
    python plot_timeline.py                          # fully driven by config.yaml
    python plot_timeline.py --csv data/patreon/timeline.csv
    python plot_timeline.py --csv data/patreon/timeline.csv --window 14 --output chart.png
    python plot_timeline.py --chapters-csv data/chapters.csv --pacing-window 30
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from chaplib.config import Config


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def filter_monotonic_chapters(df: pd.DataFrame, max_jump: int = 29) -> pd.DataFrame:
    """Drop rows where chapter number jumps by more than *max_jump* (likely noise)."""
    mask = df["chapter"].diff().le(max_jump) | df["chapter"].diff().isna()
    return df[mask].sort_values("date")


def plot_chapter_rate(
    df: pd.DataFrame,
    window_days: int = 10,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """Plot rolling chapters-per-day release rate onto *ax* (creates one if not given)."""
    df = filter_monotonic_chapters(df)

    rate = (
        df.set_index("date")
        .rolling(f"{window_days}D")["chapter"]
        .apply(lambda x: x.nunique() / window_days, raw=False)
        .rename(f"chapters_per_day_sma_{window_days}d")
        .reset_index()
    )

    if ax is None:
        _, ax = plt.subplots(figsize=(12, 5))

    sns.lineplot(data=rate, x="date", y=f"chapters_per_day_sma_{window_days}d", ax=ax)
    ax.set_title(f"In-Story Time (Chapters/Day SMA over {window_days} Days)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Chapters / Day")
    return ax


def _build_merged(
    timeline_df: pd.DataFrame,
    chapters_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge timeline and chapters CSVs on chapter number.

    Returns a DataFrame with columns ``story_date`` and ``published``,
    sorted by ``story_date``, with one row per unique story date.
    """
    timeline_df = filter_monotonic_chapters(timeline_df)

    chapters_df = chapters_df.copy()
    chapters_df["published"] = pd.to_datetime(chapters_df["published"], errors="coerce")
    chapters_df = chapters_df.dropna(subset=["published", "chapter"]).sort_values("published")

    merged = pd.merge(
        chapters_df[["chapter", "published"]],
        timeline_df[["date", "chapter"]].rename(columns={"date": "story_date"}),
        on="chapter",
        how="inner",
    ).sort_values("story_date").drop_duplicates(subset="story_date")

    if merged.empty:
        raise ValueError(
            "No rows matched between the timeline CSV and chapters CSV on the "
            "'chapter' column. Check that chapter numbers overlap."
        )
    return merged


def plot_story_vs_irl(
    timeline_df: pd.DataFrame,
    chapters_df: pd.DataFrame,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """Plot IRL publish date (Y) against in-story date (X).

    Joins the chapters CSV (``id, title, published, word_count, chapter``) with
    the timeline CSV on ``chapter``, mapping each in-story date to the IRL
    publish date of the chapter that reaches it.
    """
    merged = _build_merged(timeline_df, chapters_df)

    if ax is None:
        _, ax = plt.subplots(figsize=(12, 5))

    sns.lineplot(data=merged, x="story_date", y="published", ax=ax)
    ax.set_title("IRL Publish Date vs. In-Story Date")
    ax.set_xlabel("In-Story Date")
    ax.set_ylabel("IRL Publish Date")
    return ax


def plot_pacing_rate(
    timeline_df: pd.DataFrame,
    chapters_df: pd.DataFrame,
    pacing_window_days: int = 10,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """Plot the derivative of IRL-publish-date vs in-story-date.

    The slope is ``Δirl_days / Δstory_days`` — how many real-world days
    the author takes per in-story day — computed as a rolling rise-over-run
    over a window of *pacing_window_days* in-story days.  A higher value
    means real time is passing faster relative to story time (slow arc);
    lower means the story is moving quickly.

    In-story date is on the X axis, consistent with the other plots.
    """
    merged = _build_merged(timeline_df, chapters_df)

    # Convert both axes to float days for differentiation.
    merged["story_days"] = (
        merged["story_date"] - merged["story_date"].min()
    ).dt.total_seconds() / 86400

    merged["published_days"] = (
        merged["published"] - merged["published"].min()
    ).dt.total_seconds() / 86400

    merged = merged.set_index("story_date").sort_index()

    # Rolling slope: Δirl_days / Δstory_days over a story-time window.
    slopes = []
    idx = merged.index
    window_td = pd.Timedelta(days=pacing_window_days)
    for ts in idx:
        mask = (idx >= ts - window_td) & (idx <= ts)
        x = merged["story_days"][mask].values   # in-story days (independent)
        y = merged["published_days"][mask].values  # IRL days (dependent)
        if len(x) < 2 or (x[-1] - x[0]) == 0:
            slopes.append(float("nan"))
        else:
            slopes.append((y[-1] - y[0]) / (x[-1] - x[0]))

    merged["pacing_rate"] = slopes

    if ax is None:
        _, ax = plt.subplots(figsize=(12, 5))

    sns.lineplot(data=merged.reset_index(), x="story_date", y="pacing_rate", ax=ax)
    ax.set_title(
        f"Inverse Pacing Rate (IRL Days / In-Story Day, {pacing_window_days}d story-time window)"
    )
    ax.set_xlabel("In-Story Date")
    ax.set_ylabel("IRL Days per In-Story Day")
    ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, label="1:1 pacing")
    ax.legend()
    return ax


def build_figure(
    timeline_df: pd.DataFrame,
    chapters_df: pd.DataFrame | None,
    window_days: int = 10,
    pacing_window_days: int = 10,
    output: str | None = None,
    show: bool = False,
) -> None:
    """Build and display/save the combined figure."""
    n_rows = 3 if chapters_df is not None else 1
    fig, axes = plt.subplots(n_rows, 1, figsize=(12, 5 * n_rows))

    if n_rows == 1:
        axes = [axes]  # normalise to a list for uniform indexing

    plot_chapter_rate(timeline_df, window_days=window_days, ax=axes[0])

    if chapters_df is not None:
        plot_story_vs_irl(timeline_df, chapters_df, ax=axes[1])
        plot_pacing_rate(timeline_df, chapters_df, pacing_window_days=pacing_window_days, ax=axes[2])

    plt.tight_layout()

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=150)
        print(f"Chart saved → {output}")

    if show or not output:
        plt.show()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot chapter release rate from a timeline CSV. "
                    "All options default to values from config.yaml (plot section); "
                    "CLI flags override them."
    )
    parser.add_argument(
        "--config", default="config.yaml", metavar="FILE",
        help="YAML config file (default: config.yaml)",
    )
    pre, _ = parser.parse_known_args()
    cfg = Config.load(pre.config)

    parser.add_argument(
        "--csv", metavar="FILE", default=cfg.get("path.timeline.csv"),
        help="Path to the timeline CSV.",
    )
    parser.add_argument(
        "--chapters-csv", metavar="FILE", default=cfg.get("path.patreon.chapters_csv"),

        help=(
            "Path to a patreon chapters CSV with headers"
        ),
    )
    parser.add_argument(
        "--window", type=int, metavar="DAYS", default=cfg.get("plot.timeline.window"),
        help="Rolling window size in days for the chapters/day plot.",
    )
    parser.add_argument(
        "--pacing-window", type=int, metavar="DAYS", default=cfg.get("plot.timeline.pacing_window"),
        help=(
            "Rolling window in in-story days for the pacing-rate derivative plot."
        ),
    )
    parser.add_argument(
        "--output", metavar="FILE", default=cfg.get("plot.timeline.output"),
        help="Save chart to this file.",
    )
    parser.add_argument(
        "--plot", action="store_true", default=False,
        help="Display the chart interactively.",
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if not args.csv:
        sys.exit(
            "No CSV path provided. Pass --csv or set plot.csv in config.yaml."
        )
    if not Path(args.csv).exists():
        sys.exit(f"CSV file not found: {args.csv}")

    print(f"Loading {args.csv} …")
    df = pd.read_csv(args.csv, parse_dates=["date"])

    chapters_df: pd.DataFrame | None = None
    if args.chapters_csv:
        chapters_path = args.chapters_csv
        if not Path(chapters_path).exists():
            sys.exit(f"Chapters CSV not found: {chapters_path}")
        print(f"Loading {chapters_path} …")
        chapters_df = pd.read_csv(chapters_path)

    build_figure(
        df, chapters_df,
        window_days=args.window,
        pacing_window_days=args.pacing_window,
        output=args.output,
        show=args.plot,
    )


if __name__ == "__main__":
    main()
