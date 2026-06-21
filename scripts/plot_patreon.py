import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


def parse_args():
    parser = argparse.ArgumentParser(description="Plot Patreon chapter statistics.")
    parser.add_argument("-p", "--plot", action="store_true", 
                        help="Show plots interactively after saving.")
    parser.add_argument("--events-csv", default="data/patreon/events.csv",
                        help="Path to events CSV (default: data/patreon/events.csv).")
    parser.add_argument("--intermediary-csv", default="data/temp/intermediary.csv",
                        help="Path to intermediary CSV (default: data/temp/intermediary.csv).")
    parser.add_argument("--out-histograms", default="plots/histograms.png",
                        help="Output path for histograms plot.")
    parser.add_argument("--out-hours-late", default="plots/hours_late.png",
                        help="Output path for hours-late scatter plot.")
    parser.add_argument("--out-word-count", default="plots/word_count.png",
                        help="Output path for word-count plot.")
    parser.add_argument("--out-monthly-bars", default="plots/monthly_bars.png",
                        help="Output path for monthly word count and chapter count bar plot.")
    parser.add_argument("--day-rolling-avg", default=26, type=int,
                        help="Window size in days for the rolling words/day average (default: 26).")
    parser.add_argument("--exclude-gaps", action="store_true", default=False,
                        help="Exclude hiatus gaps from the word avg plot.")
    return parser.parse_args()


def load_data(intermediary_csv: str, events_csv: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(intermediary_csv, parse_dates=["published", "deadline"])
    df["modifier"] = df["modifier"].fillna("none")
    df_events = pd.read_csv(events_csv)
    return df, df_events


def print_summary(df: pd.DataFrame) -> None:
    print(df[df["chapter"] >= 259]["hours_late"].mean())
    print(df[(df["chapter"] > 220) & (df["chapter"] < 259)]["hours_late"].mean())
    print("Top late:")
    print(
        df[["chapter", "modifier", "hours_late"]]
        .sort_values(by="hours_late", ascending=False)
        .head(10)
    )


def id_to_chapter(df: pd.DataFrame, target_id) -> float:
    return df.loc[df["id"] == target_id, "chapter"].iloc[0]


def poly_fit_r2(x: np.ndarray, y: np.ndarray, deg: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit a polynomial, return (coeffs, y_pred, r2)."""
    coeffs = np.polyfit(x, y, deg=deg)
    y_pred = np.polyval(coeffs, x)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - np.sum((y - y_pred) ** 2) / ss_tot
    return coeffs, y_pred, r2


def draw_break(ax, x_pos: float, y_min: float, y_max: float) -> None:
    """Draw a jagged axis-break indicator at x_pos."""
    amplitude = (y_max - y_min) * 0.05
    mid = (y_min + y_max) / 2
    xs = [x_pos - 0.5, x_pos - 0.3, x_pos + 0.3, x_pos + 0.5]
    ys = [mid - amplitude, mid + amplitude, mid - amplitude, mid + amplitude]
    ax.plot(xs, ys, color="black", linewidth=1.5, clip_on=False, zorder=5)
    ax.axvline(x_pos, color="gray", linewidth=1, linestyle=":", alpha=0.5)


def plot_histograms(df: pd.DataFrame, out_path: str, show: bool = False) -> None:
    """Four stacked histograms of hours_late for different chapter subsets."""
    subsets = [
        (df[df["deadline"] > "2024-01-01"], "Normal"),
        (df[df["reference_id"].notna()], "Preview Chapters"),
        (df[df["id"].isin(df["reference_id"])], "Post-Preview Chapters"),
        (df[df["modifier"] == "approximate"], '"Approximate"'),
    ]

    fig, axes = plt.subplots(nrows=len(subsets), sharex=True, figsize=(6, 6))
    for ax, (subset_df, title) in zip(axes, subsets):
        sns.histplot(data=subset_df, x="hours_late", binwidth=1, ax=ax)
        ax.set_title(title)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    if not show:
        plt.close(fig)


def plot_hours_late(df: pd.DataFrame, df_events: pd.DataFrame, out_path: str, show: bool = False) -> None:
    """Scatter plot of hours_late by chapter, with event annotations."""
    colors = ["red", "blue", "purple", "orange", "black"]

    fig, ax = plt.subplots(figsize=(12, 6))
    sns.scatterplot(data=df, x="chapter", y="hours_late", hue="modifier", ax=ax)
    ax.axhline(y=0, color="black", linestyle="--", linewidth=1.0)

    for i, row in enumerate(df_events.itertuples()):
        chapter = id_to_chapter(df, row.id)
        ax.axvline(x=chapter, color=colors[i % len(colors)], linestyle="--", linewidth=1.5)
        y_mult = [0.9, 0.8, 0.7][i % 3]
        ax.text(
            chapter + 0.2,
            ax.get_ylim()[0] * y_mult,
            row.description,
            bbox=dict(facecolor="white", edgecolor="red", boxstyle="round,pad=0.3"),
        )

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    if not show:
        plt.close(fig)


def _build_word_avg(df: pd.DataFrame, day_rolling: int = 26) -> pd.DataFrame:
    """Resample published timestamps to hourly and compute a rolling words/day average."""
    df_chapexists = df[~df["chapter"].isna()]
    df_wc = (
        df_chapexists
        .set_index("published")[["word_count", "chapter"]]
        .resample("1h")
        .sum()
        .fillna(0)
    )
    df_wc["word_avg"] = df_wc["word_count"].rolling(f"{day_rolling}D").sum() / day_rolling
    return df_wc


GAPS = [
    ("2025-01-30", "2025-03-20"),
    ("2025-09-20", "2025-11-15"),
]


def _plot_word_avg(ax, df_wc: pd.DataFrame, day_rolling: int, exclude_gaps: bool = False) -> None:
    """Upper subplot: rolling words/day average over time with poly + linear fits.

    When exclude_gaps is True, gap periods are dropped before plotting and fitting.
    The remaining points are mapped to contiguous integer x positions so fitted
    lines are smooth, but tick labels reflect the original dates so the jump is
    visible on the x-axis.
    """
    if exclude_gaps:
        tz = df_wc.index.tz
        mask = pd.Series(True, index=df_wc.index)
        for start_str, end_str in GAPS:
            gap_start = pd.Timestamp(start_str, tz=tz)
            gap_end = pd.Timestamp(end_str, tz=tz)
            mask &= ~((df_wc.index >= gap_start) & (df_wc.index <= gap_end))
        df_plot = df_wc[mask]
    else:
        df_plot = df_wc

    x_raw = df_plot.index
    x_num = np.arange(len(x_raw))
    y = df_plot["word_avg"].values

    _, y_poly, r2_poly = poly_fit_r2(x_num, y, deg=6)
    _, y_lin, r2_lin = poly_fit_r2(x_num, y, deg=1)

    sns.lineplot(x=x_num, y=y, ax=ax)
    ax.plot(x_num, y_poly, color="red", linewidth=2, linestyle="--",
            label=f"poly fit (deg 6)  $R^2={r2_poly:.3f}$")
    ax.plot(x_num, y_lin, color="orange", linewidth=2, linestyle="--",
            label=f"linear fit  $R^2={r2_lin:.3f}$")
    ax.set_ylabel(f"words/day ({day_rolling}D rolling avg)")

    # If gaps are excluded, mark jump boundaries with vertical dotted lines.
    if exclude_gaps:
        tz = df_wc.index.tz
        for start_str, end_str in GAPS:
            gap_end = pd.Timestamp(end_str, tz=tz)
            # Find the first kept point at or after the gap end.
            pos = np.searchsorted(x_raw, gap_end)
            if 0 < pos < len(x_raw):
                ax.axvline(pos - 0.5, color="gray", linewidth=1, linestyle=":", alpha=0.7)

    tick_indices = list(np.linspace(0, len(x_num) - 1, 8, dtype=int))
    tick_indices = [i for i in tick_indices if 0 <= i < len(x_raw)]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(
        [x_raw[i].strftime("%b %d '%y") for i in tick_indices],
        rotation=45, ha="right",
    )
    ax.legend()


def _plot_word_count_by_chapter(ax, df: pd.DataFrame) -> None:
    """Lower subplot: word count per chapter with poly + linear fits and banded background."""
    df_sorted = (
        df[~df["chapter"].isna()]
        .sort_values("chapter")
        .dropna(subset=["chapter", "word_count"])
    )
    x = df_sorted["chapter"].values.astype(float)
    y = df_sorted["word_count"].values

    coeffs_poly, _, r2_poly = poly_fit_r2(x, y, deg=6)
    coeffs_lin, _, r2_lin = poly_fit_r2(x, y, deg=1)

    x_fit = np.linspace(x.min(), x.max(), 300)

    sns.lineplot(data=df_sorted, x="chapter", y="word_count", ax=ax)
    ax.plot(x_fit, np.polyval(coeffs_poly, x_fit), color="red", linewidth=2,
            linestyle="--", label=f"poly fit (deg 6)  $R^2={r2_poly:.3f}$")
    ax.plot(x_fit, np.polyval(coeffs_lin, x_fit), color="orange", linewidth=2,
            linestyle="--", label=f"linear fit  $R^2={r2_lin:.3f}$")
    ax.set_ylabel("word count")
    ax.legend()

    # Alternating horizontal bands
    band_height = 2500
    y_band = 0.0
    toggle = True
    while y_band < 25000:
        if toggle:
            ax.axhspan(y_band, y_band + band_height, color="lightgray", alpha=0.3)
        toggle = not toggle
        y_band += band_height


def plot_word_count(df: pd.DataFrame, out_path: str, day_rolling: int = 26, show: bool = False, exclude_gaps: bool = False) -> None:
    """Two-panel figure: rolling words/day average (top) and per-chapter word count (bottom)."""
    df_wc = _build_word_avg(df, day_rolling)

    fig, axes = plt.subplots(2, 1, figsize=(12, 9))
    _plot_word_avg(axes[0], df_wc, day_rolling, exclude_gaps=exclude_gaps)
    _plot_word_count_by_chapter(axes[1], df)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    if not show:
        plt.close(fig)


def plot_monthly_bars(df: pd.DataFrame, out_path: str, show: bool = False) -> None:
    """Two-panel bar chart: total word count (top) and chapter count (bottom) by month."""
    df_chapexists = df[~df["chapter"].isna()].copy()
    df_chapexists["month"] = df_chapexists["published"].dt.to_period("M")

    monthly = (
        df_chapexists
        .groupby("month")
        .agg(word_count=("word_count", "sum"), chapter_count=("chapter", "count"))
        .reset_index()
    )
    monthly["month_str"] = monthly["month"].astype(str)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    axes[0].bar(monthly["month_str"], monthly["word_count"], color="steelblue")
    axes[0].set_ylabel("total word count")

    axes[1].bar(monthly["month_str"], monthly["chapter_count"], color="darkorange")
    axes[1].set_ylabel("chapter count")

    for ax in axes:
        ax.set_xticks(range(len(monthly)))
        ax.set_xticklabels(monthly["month_str"], rotation=45, ha="right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    if not show:
        plt.close(fig)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    df, df_events = load_data(args.intermediary_csv, args.events_csv)
    print_summary(df)

    plot_histograms(df, args.out_histograms, show=args.plot)
    plot_hours_late(df, df_events, args.out_hours_late, show=args.plot)
    plot_word_count(df, args.out_word_count, day_rolling=args.day_rolling_avg, show=args.plot, exclude_gaps=args.exclude_gaps)
    plot_monthly_bars(df, args.out_monthly_bars, show=args.plot)

    if args.plot:
        plt.show()


if __name__ == "__main__":
    main()
