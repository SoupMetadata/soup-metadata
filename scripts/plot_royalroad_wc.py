import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


def parse_args():
    parser = argparse.ArgumentParser(description="Plot word count statistics from a RoyalRoad CSV.")
    parser.add_argument("--initial-csv", default="data/royalroad/initial.csv",
                        help="Path to the initial CSV.")
    parser.add_argument("-p", "--plot", action="store_true", default=False,
                        help="Show plot interactively after saving.")
    parser.add_argument("--out", default="plots/rr_word_count.png",
                        help="Output path for the plot (default: plots/rr_word_count.png).")
    parser.add_argument("--day-rolling-avg", default=26, type=int,
                        help="Window size in days for the rolling word count average.")
    return parser.parse_args()


def poly_fit_r2(x: np.ndarray, y: np.ndarray, deg: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit a polynomial, return (coeffs, y_pred, r2)."""
    coeffs = np.polyfit(x, y, deg=deg)
    y_pred = np.polyval(coeffs, x)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - np.sum((y - y_pred) ** 2) / ss_tot
    return coeffs, y_pred, r2


def build_word_avg(df: pd.DataFrame, day_rolling: int) -> pd.DataFrame:
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


def plot_word_avg(ax, df_wc: pd.DataFrame, day_rolling: int) -> None:
    x_raw = df_wc.index
    x_num = np.arange(len(x_raw))
    y = df_wc["word_avg"].values

    _, y_poly, r2_poly = poly_fit_r2(x_num, y, deg=6)
    _, y_lin, r2_lin = poly_fit_r2(x_num, y, deg=1)

    sns.lineplot(x=x_num, y=y, ax=ax)
    ax.plot(x_num, y_poly, color="red", linewidth=2, linestyle="--",
            label=f"poly fit (deg 6)  $R^2={r2_poly:.3f}$")
    ax.plot(x_num, y_lin, color="orange", linewidth=2, linestyle="--",
            label=f"linear fit  $R^2={r2_lin:.3f}$")
    ax.set_ylabel(f"words/day ({day_rolling}D rolling avg)")

    tick_indices = list(np.linspace(0, len(x_num) - 1, 8, dtype=int))
    tick_indices = [i for i in tick_indices if 0 <= i < len(x_raw)]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(
        [x_raw[i].strftime("%b %d '%y") for i in tick_indices],
        rotation=45, ha="right",
    )
    ax.legend()


def plot_word_count_by_chapter(ax, df: pd.DataFrame) -> None:
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

    band_height = 2500
    y_band = 0.0
    toggle = True
    while y_band < 25000:
        if toggle:
            ax.axhspan(y_band, y_band + band_height, color="lightgray", alpha=0.3)
        toggle = not toggle
        y_band += band_height


def main() -> None:
    args = parse_args()

    df = pd.read_csv(args.initial_csv, parse_dates=["published"])
    df_wc = build_word_avg(df, args.day_rolling_avg)

    fig, axes = plt.subplots(2, 1, figsize=(12, 9))
    plot_word_avg(axes[0], df_wc, args.day_rolling_avg)
    plot_word_count_by_chapter(axes[1], df)

    fig.tight_layout()
    fig.savefig(args.out, dpi=300)

    if args.plot:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()
