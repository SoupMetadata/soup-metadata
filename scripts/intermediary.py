import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from chaplib import data
from chaplib.config import Config


def parse_args():
    parser = argparse.ArgumentParser(description="Build intermediary Patreon CSV.")
    parser.add_argument(
        "--config", default="config.yaml", metavar="FILE",
        help="YAML config file (default: config.yaml)",
    )
    pre, _ = parser.parse_known_args()
    cfg = Config.load(pre.config)

    parser.add_argument("--chapters-csv", default=cfg.get("path.patreon.chapters_csv"),
                        help="Path to patreon chapters CSV.")
    parser.add_argument("--deadlines-csv", default=cfg.get("path.patreon.deadlines_csv"),
                        help="Path to patreon deadlines CSV.")
    parser.add_argument("--rr-path", default=cfg.get("path.royalroad.chapters_csv"),
                        help="Path to RR chapters CSV.")
    parser.add_argument("--out-path", default=cfg.get("path.intermediary"),
                        help="Output path for intermediary CSV.")
    return parser.parse_args()


def load_data(
    initial_csv: str,
    deadlines_csv: str,
    rr_csv: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(initial_csv, parse_dates=["published"])
    df_deadlines = pd.read_csv(deadlines_csv)
    df = df.merge(df_deadlines, on="id", how="outer")

    df_rr = pd.read_csv(rr_csv, parse_dates=["published"])
    df_rr = df_rr.sort_values("published")
    df_rr["published"] = df_rr["published"].astype("datetime64[us, UTC]")

    return df, df_rr


def pacific_to_utc(date_str: str | None) -> datetime | None:
    """Parse a Pacific-time string (possibly containing 'PST') and return a UTC datetime."""
    if pd.isna(date_str):
        return None
    date_str = date_str.replace("PST", "").strip()
    naive_dt = datetime.strptime(date_str, "%B %d %Y %H:%M")
    pacific_dt = naive_dt.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    return pacific_dt.astimezone(ZoneInfo("UTC"))


def latest_rr_hour_before(deadline: datetime, rr_times: pd.Series) -> int | None:
    """Return the hour of the latest RR publication strictly before *deadline*, or None."""
    candidates = rr_times[rr_times < deadline]
    return int(candidates.max().hour) if not candidates.empty else None


def build_intermediary(df: pd.DataFrame, df_rr: pd.DataFrame) -> pd.DataFrame:
    rr_times = df_rr["published"]

    df["deadline"] = df["deadline"].map(pacific_to_utc)
    df["rr_closest_hour"] = df["deadline"].apply(latest_rr_hour_before, rr_times=rr_times)
    df["hours_late"] = (df["published"] - df["deadline"]).apply(
        lambda x: x.total_seconds() / 3600
    )
    df["deadline_weekday"] = df["deadline"].apply(lambda x: x.weekday())

    return df


def main() -> None:
    args = parse_args()

    df, df_rr = load_data(args.chapters_csv, args.deadlines_csv, args.rr_path)
    df = build_intermediary(df, df_rr)
    data.save(df, args.out_path)
    print(f"Wrote {len(df)} rows to {args.out_path}")


if __name__ == "__main__":
    main()
