import argparse
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from chaplib.config import Config


def parse_args():
    parser = argparse.ArgumentParser(description="Plot Patreon chapter statistics.")
    parser.add_argument(
        "--config", default="config.yaml", metavar="FILE",
        help="YAML config file (default: config.yaml)",
    )
    pre, _ = parser.parse_known_args()
    cfg = Config.load(pre.config)

    parser.add_argument("-p", "--plot", action="store_true", 
                        help="Show plots interactively after saving.")
    parser.add_argument("--events-csv", default=cfg.get("path.patreon.events_csv"),
                        help="Path to events CSV.")
    parser.add_argument("--intermediary-csv", default=cfg.get("path.intermediary"),
                        help="Path to intermediary CSV.")
    parser.add_argument("--out-histograms", default=cfg.get("plot.patreon.out_histograms"),
                        help="Output path for histograms plot.")
    parser.add_argument("--out-hours-late", default=cfg.get("plot.patreon.out_hours_late"),
                        help="Output path for hours-late scatter plot.")
    parser.add_argument("--out-word-count", default=cfg.get("plot.patreon.out_word_count"),
                        help="Output path for word-count plot.")
    parser.add_argument("--out-monthly-bars", default=cfg.get("plot.patreon.out_monthly_bars"),
                        help="Output path for monthly word count and chapter count bar plot.")
    parser.add_argument("--out-deadline-gap", default=cfg.get("plot.patreon.out_deadline_gap"),
                        help="Output path for deadline-gap vs hours-late scatter plot.")
    try:
        default_out_arcs = cfg.get("plot.patreon.out_arcs")
    except KeyError:
        default_out_arcs = None
    parser.add_argument("--out-arcs", default=default_out_arcs or "patreon_arcs.png",
                        help="Output path for the arc length/frequency/gap plot.")
    parser.add_argument("--deadline-max-gap-days", default=cfg.get("plot.patreon.deadline_max_gap_days"), type=float,
                        help="Exclude deadline gaps larger than this many days (hiatuses).")
    parser.add_argument("--deadline-last-n", default=cfg.get("plot.patreon.deadline_last_n"), type=int,
                        help="Only consider the most recent N entries for the deadline-gap plot.")
    parser.add_argument("--day-rolling-avg", default=cfg.get("plot.patreon.day_rolling_avg"), type=int,
                        help="Window size in days for the rolling words/day average.")
    parser.add_argument("--exclude-gaps", action="store_true", default=cfg.get("plot.patreon.exclude_gaps"),
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


def _add_hours_late_guides(
    ax, stripe_width: float = 2.0, guide_interval: float = 24.0,
) -> None:
    """Add two-hour bands and dotted day-interval guides to an hours-late axis."""
    y_min, y_max = ax.get_ylim()

    # Shade every other two-hour interval. Starting each shaded band on a
    # multiple of four keeps all band edges aligned to exact two-hour marks.
    stripe_period = stripe_width * 2
    first_stripe = np.floor(y_min / stripe_period) * stripe_period
    for band_start in np.arange(first_stripe, y_max, stripe_period):
        visible_start = max(band_start, y_min)
        visible_end = min(band_start + stripe_width, y_max)
        if visible_start < visible_end:
            ax.axhspan(
                visible_start,
                visible_end,
                color="slategray",
                alpha=0.08,
                linewidth=0,
                zorder=0,
            )

    # Draw one-day reference lines only where they fall inside the current
    # view. Zero is handled separately by the stronger dashed baseline.
    first_guide = np.ceil(y_min / guide_interval) * guide_interval
    last_guide = np.floor(y_max / guide_interval) * guide_interval
    for guide_y in np.arange(
        first_guide, last_guide + guide_interval / 2, guide_interval,
    ):
        if not np.isclose(guide_y, 0.0):
            ax.axhline(
                y=guide_y,
                color="dimgray",
                linestyle=":",
                linewidth=1.0,
                alpha=0.75,
                zorder=0.5,
            )

    # Background artists should not change the limits chosen for the data.
    ax.set_ylim(y_min, y_max)


def plot_hours_late(df: pd.DataFrame, df_events: pd.DataFrame, out_path: str, show: bool = False) -> None:
    """Scatter plot of hours_late by chapter, with event annotations."""
    colors = ["red", "blue", "purple", "orange", "black"]

    fig, ax = plt.subplots(figsize=(12, 6))
    sns.scatterplot(data=df, x="chapter", y="hours_late", hue="modifier", ax=ax)
    _add_hours_late_guides(ax)
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


def _add_word_avg_stripes(ax, stripe_width: float = 200.0) -> None:
    """Add alternating horizontal bands to a words/day axis."""
    y_min, y_max = ax.get_ylim()
    stripe_period = stripe_width * 2
    first_stripe = np.floor(y_min / stripe_period) * stripe_period

    for band_start in np.arange(first_stripe, y_max, stripe_period):
        visible_start = max(band_start, y_min)
        visible_end = min(band_start + stripe_width, y_max)
        if visible_start < visible_end:
            ax.axhspan(
                visible_start,
                visible_end,
                color="slategray",
                alpha=0.08,
                linewidth=0,
                zorder=0,
            )

    # Background artists should not change the limits chosen for the data.
    ax.set_ylim(y_min, y_max)


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
    _add_word_avg_stripes(ax, stripe_width=200.0)

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


ROMAN_PART_RE = re.compile(
    r"^(?=[MDCLXVI]+$)M{0,4}(?:CM|CD|D?C{0,3})"
    r"(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$",
    flags=re.IGNORECASE,
)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def _roman_to_int(roman: str) -> int:
    """Convert a validated Roman numeral to an integer."""
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for symbol in reversed(roman.upper()):
        value = values[symbol]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total


def _parse_arc_title(title: str) -> tuple[str, int | None, str | None]:
    """Return (clean arc name, part number, suffix style).

    The title prefix before the first colon is the spelled-out chapter number,
    not part of the arc name. Part suffixes may be Roman numerals, Arabic digits,
    or case-insensitive number words. An unnumbered title returns no part; it may
    later be inferred as part I when immediately followed by part II.
    """
    title = title.strip()
    if ":" in title:
        title = title.split(":", maxsplit=1)[1].strip()

    if " " not in title:
        return title, None, None

    arc_name, label = title.rsplit(maxsplit=1)
    if label.isdigit():
        return arc_name.strip(), int(label), "arabic"
    if label.casefold() in NUMBER_WORDS:
        return arc_name.strip(), NUMBER_WORDS[label.casefold()], "word"
    if ROMAN_PART_RE.fullmatch(label):
        return arc_name.strip(), _roman_to_int(label), "roman"
    return title, None, None


def _chapters_are_consecutive(first: float, second: float) -> bool:
    """Return whether two float chapter numbers are one chapter apart."""
    return bool(np.isclose(float(second) - float(first), 1.0))


def build_arc_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Extract numbered title arcs and their lengths/gaps in chapter order.

    Chapter names come from ``title`` and their numeric chronological positions
    come from ``chapter``. An arc is a consecutive run of chapters whose ending
    labels count upward from 1 through N. Roman numerals, Arabic digits, and
    number words may be mixed freely, and title-name differences are ignored.
    An unnumbered chapter immediately before part 2 is inferred to be part 1.
    Within a run, up to two consecutive unlabeled chapters may bridge numbered
    parts; each may represent one missing part or a two-part combined chapter.
    A combined chapter may also cause the next stored chapter number to jump by
    two, so bridges compare the total chapter-number span with the part span.
    The cleaned name from part N becomes the arc name.
    """
    required_columns = {"title", "chapter"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Arc plotting requires the following columns: {missing}")

    chapters = (
        df.dropna(subset=["chapter"])
        .sort_values("chapter")
        .drop_duplicates(subset=["chapter"], keep="first")
        .reset_index(drop=True)
    )
    chapters["chapter_position"] = np.arange(len(chapters))

    print(f"[arcs] examining {len(chapters)} unique chapters from 'chapter' and 'title'")
    parsed = chapters["title"].fillna("").astype(str).map(_parse_arc_title)
    chapters[["arc_name", "part", "suffix_style"]] = pd.DataFrame(
        parsed.tolist(), index=chapters.index,
    )
    style_counts = chapters["suffix_style"].value_counts().to_dict()
    print(
        "[arcs] recognized numbered suffixes: "
        f"roman={style_counts.get('roman', 0)}, "
        f"arabic={style_counts.get('arabic', 0)}, "
        f"word={style_counts.get('word', 0)}"
    )

    arcs = []
    used_numbered_positions = set()
    position = 0
    while position < len(chapters) - 1:
        first = chapters.iloc[position]
        second = chapters.iloc[position + 1]
        consecutive = _chapters_are_consecutive(first["chapter"], second["chapter"])

        explicit_first = pd.notna(first["part"]) and int(first["part"]) == 1
        implicit_first = pd.isna(first["part"])
        second_is_two = pd.notna(second["part"]) and int(second["part"]) == 2
        if explicit_first:
            run_positions = [position]
            current_part = 1
            next_position = position + 1
        elif implicit_first and consecutive and second_is_two:
            run_positions = [position, position + 1]
            current_part = 2
            next_position = position + 2
            print(
                f"[arcs] inferred unlabeled chapter {first['chapter']} as part 1 "
                f"before explicit part 2"
            )
        else:
            position += 1
            continue

        while next_position < len(chapters):
            unlabeled_positions = []
            scan_position = next_position

            # Collect at most two consecutive unlabeled chapters before the
            # next explicit part label.
            while scan_position < len(chapters) and len(unlabeled_positions) < 2:
                previous_row = chapters.iloc[scan_position - 1]
                scan_row = chapters.iloc[scan_position]
                if not _chapters_are_consecutive(previous_row["chapter"], scan_row["chapter"]):
                    break
                if pd.notna(scan_row["part"]):
                    break
                unlabeled_positions.append(scan_position)
                scan_position += 1

            if scan_position >= len(chapters):
                break

            next_row = chapters.iloc[scan_position]
            if pd.isna(next_row["part"]):
                # More than two consecutive unlabeled chapters.
                break

            next_part = int(next_row["part"])
            previous_numbered_row = chapters.iloc[run_positions[-1]]
            chapter_span = float(next_row["chapter"]) - float(previous_numbered_row["chapter"])
            part_span = next_part - current_part
            if not np.isclose(chapter_span, part_span):
                print(
                    f"[arcs] stopped before chapter {next_row['chapter']}: "
                    f"chapter span {chapter_span:g} does not match part span {part_span}"
                )
                break

            missing_parts = next_part - current_part - 1
            unlabeled_count = len(unlabeled_positions)
            if unlabeled_count == 0:
                if missing_parts != 0:
                    break
            elif not (unlabeled_count <= missing_parts <= 2 * unlabeled_count):
                break

            if unlabeled_positions:
                part_cursor = current_part + 1
                extra_combined_parts = missing_parts - unlabeled_count
                for unlabeled_position in unlabeled_positions:
                    covered_parts = 1 + int(extra_combined_parts > 0)
                    extra_combined_parts -= covered_parts - 1
                    part_end = part_cursor + covered_parts - 1
                    part_label = (
                        str(part_cursor) if part_cursor == part_end
                        else f"{part_cursor}–{part_end}"
                    )
                    print(
                        f"[arcs] inferred unlabeled chapter "
                        f"{chapters.iloc[unlabeled_position]['chapter']} as part(s) "
                        f"{part_label} before explicit part {next_part}"
                    )
                    part_cursor = part_end + 1

            run_positions.extend(unlabeled_positions)
            run_positions.append(scan_position)
            current_part = next_part
            next_position = scan_position + 1

        if current_part < 2:
            position += 1
            continue

        last_part = current_part
        last = chapters.iloc[run_positions[-1]]
        arcs.append({
            "arc_name": last["arc_name"],
            "arc_length": last_part,
            "start_position": int(first["chapter_position"]),
            "end_position": int(last["chapter_position"]),
            "start_chapter": first["chapter"],
        })
        used_numbered_positions.update(
            run_position for run_position in run_positions
            if pd.notna(chapters.iloc[run_position]["part"])
        )
        print(
            f"[arcs] run {first['chapter']}–{last['chapter']}: "
            f"parts 1–{last_part}; using final name {last['arc_name']!r}"
        )
        position = next_position

    numbered_positions = set(chapters.index[chapters["part"].notna()].tolist())
    orphaned_positions = sorted(numbered_positions.difference(used_numbered_positions))
    if orphaned_positions:
        examples = ", ".join(
            f"{chapters.iloc[pos]['chapter']}={int(chapters.iloc[pos]['part'])}"
            for pos in orphaned_positions[:10]
        )
        remainder = " ..." if len(orphaned_positions) > 10 else ""
        print(
            f"[arcs] ignored {len(orphaned_positions)} numbered titles outside "
            f"a consecutive 1..N run: {examples}{remainder}"
        )

    columns = [
        "arc_index", "arc_name", "arc_length", "gap_chapters",
        "start_chapter", "start_position", "end_position",
    ]
    if not arcs:
        print("[arcs] no complete arcs detected")
        return pd.DataFrame(columns=columns)

    result = pd.DataFrame(arcs).sort_values("start_position").reset_index(drop=True)
    result.insert(0, "arc_index", np.arange(1, len(result) + 1))
    previous_end = result["end_position"].shift(fill_value=-1)
    result["gap_chapters"] = (result["start_position"] - previous_end - 1).clip(lower=0).astype(int)
    for arc in result.itertuples():
        print(
            f"[arcs] detected #{arc.arc_index}: {arc.arc_name!r}, "
            f"length={arc.arc_length}, start_chapter={arc.start_chapter}, "
            f"preceding_gap={arc.gap_chapters}"
        )
    print(f"[arcs] detected {len(result)} complete arcs")
    return result[columns]


def plot_arcs(df: pd.DataFrame, out_path: str, show: bool = False) -> None:
    """Plot arc length over time, its frequency, and gaps between arcs."""
    arcs = build_arc_stats(df)

    fig, axes = plt.subplots(3, 1, figsize=(12, 12))
    if arcs.empty:
        for ax in axes:
            ax.axis("off")
        axes[1].text(0.5, 0.5, "No complete numbered arcs found",
                     ha="center", va="center", transform=axes[1].transAxes)
    else:
        x = arcs["arc_index"].to_numpy()

        axes[0].plot(x, arcs["arc_length"], marker="o", color="steelblue")
        axes[0].set_ylabel("chapters in arc")
        axes[0].set_title("Arc length over chronological arc index")

        frequency = arcs["arc_length"].value_counts().sort_index()
        axes[1].bar(frequency.index, frequency.values, color="seagreen")
        axes[1].set_xticks(frequency.index)
        axes[1].set_xlabel("chapters in arc")
        axes[1].set_ylabel("number of arcs")
        axes[1].set_title("Arc-length frequency")

        axes[2].bar(x, arcs["gap_chapters"], color="darkorange")
        axes[2].set_xlabel("chronological arc index")
        axes[2].set_ylabel("chapters in preceding gap")
        axes[2].set_title("Chapters before each arc (first bar is before the first arc)")

        for ax in (axes[0], axes[2]):
            ax.set_xticks(x)
            ax.grid(axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    if not show:
        plt.close(fig)


def _plot_lateness_categories(ax, df_gap: pd.DataFrame) -> None:
    """Stacked bar chart: for each discrete days-since-previous-deadline bucket,
    show the percentage of chapters that fall into three lateness categories
    (<12h, 12-36h, >36h)."""
    df_late = df_gap.dropna(subset=["hours_late", "deadline_gap_days"]).copy()
    # Discrete bucket for the independent variable: rounded days since previous deadline.
    df_late["gap_bucket"] = df_late["deadline_gap_days"].round().astype(int)

    def categorize(h: float) -> str:
        if h < 12:
            return "<12h late"
        elif h < 36:
            return "12-36h late"
        return ">36h late"

    df_late["category"] = df_late["hours_late"].apply(categorize)

    categories = ["<12h late", "12-36h late", ">36h late"]
    cat_colors = {"<12h late": "seagreen", "12-36h late": "goldenrod", ">36h late": "firebrick"}

    buckets = sorted(df_late["gap_bucket"].unique())
    pct = {cat: [] for cat in categories}
    for b in buckets:
        sub = df_late[df_late["gap_bucket"] == b]
        total = len(sub)
        for cat in categories:
            pct[cat].append(100.0 * (sub["category"] == cat).sum() / total if total else 0.0)

    x = np.arange(len(buckets))
    bottom = np.zeros(len(buckets))
    for cat in categories:
        vals = np.array(pct[cat])
        ax.bar(x, vals, bottom=bottom, color=cat_colors[cat], label=cat)
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels([str(b) for b in buckets])
    ax.set_xlabel("days since previous deadline")
    ax.set_ylabel("% of chapters in bucket")
    ax.set_ylim(0, 100)
    ax.set_title("lateness category breakdown per days-since-previous-deadline bucket")
    ax.legend()


def _plot_lateness_boxplot(ax, df_gap: pd.DataFrame, last_n: int) -> None:
    """Box-and-whisker of hours_late grouped by days-since-previous-deadline bucket,
    with the raw points overlaid so exact values are visible alongside
    median/quartiles."""
    df_late = df_gap.dropna(subset=["hours_late", "deadline_gap_days"]).copy()
    df_late["gap_bucket"] = df_late["deadline_gap_days"].round().astype(int)

    order = sorted(df_late["gap_bucket"].unique())
    sns.boxplot(data=df_late, x="gap_bucket", y="hours_late", order=order,
                ax=ax, color="lightsteelblue", showmeans=True,
                meanprops={"marker": "D", "markerfacecolor": "black", "markeredgecolor": "black"})
    sns.stripplot(data=df_late, x="gap_bucket", y="hours_late", order=order,
                  ax=ax, hue="modifier", size=9, alpha=0.5, jitter=0.1)

    ax.axhline(y=12, color="goldenrod", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.axhline(y=36, color="firebrick", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_xlabel("days since previous deadline")
    ax.set_ylabel("hours late")
    ax.set_title(f"hours late distribution per days-since-previous-deadline bucket (boxplot, diamond = mean) (past {last_n} chapters)")


def plot_deadline_gap(df: pd.DataFrame, out_path: str, show: bool = False,
                      max_gap_days: float = 20.0, last_n: int | None = None) -> None:
    """Scatter of days-between-consecutive-deadlines vs hours_late, with fit,
    a box-and-whisker of hours_late per days-late bucket,
    plus a stacked bar chart of lateness-category percentages per days-late bucket.

    Gaps larger than max_gap_days (e.g. hiatuses) are excluded. When last_n is set,
    only the most recent last_n entries (by deadline) are considered.
    """
    df_sorted = (
        df.dropna(subset=["deadline", "hours_late"])
        .sort_values("deadline")
        .copy()
    )
    if last_n is not None:
        df_sorted = df_sorted.tail(last_n)
    df_sorted["deadline_gap_days"] = (
        df_sorted["deadline"].diff().dt.total_seconds() / 86400.0
    )
    df_gap = df_sorted.dropna(subset=["deadline_gap_days"])
    if max_gap_days is not None:
        df_gap = df_gap[df_gap["deadline_gap_days"] <= max_gap_days]

    fig, axes = plt.subplots(2, 1, figsize=(12, 12))

    # sns.scatterplot(data=df_gap, x="deadline_gap_days", y="hours_late",
    #                 hue="modifier", ax=axes[0])
    # axes[0].axhline(y=0, color="black", linestyle="--", linewidth=1.0)
    # axes[0].legend()
    # axes[0].set_xlabel("days since previous deadline")
    # axes[0].set_ylabel("hours late")
    # axes[0].set_title(f"deadline gap vs hours late (last {last_n} chapters)")

    _plot_lateness_boxplot(axes[0], df_gap, last_n)
    _plot_lateness_categories(axes[1], df_gap)

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
    plot_deadline_gap(df, args.out_deadline_gap, show=args.plot,
                      max_gap_days=args.deadline_max_gap_days, last_n=args.deadline_last_n)
    plot_arcs(df, args.out_arcs, show=args.plot)

    if args.plot:
        plt.show()


if __name__ == "__main__":
    main()
