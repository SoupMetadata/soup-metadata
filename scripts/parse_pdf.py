"""
parse_pdf.py — Download a timeline PDF and extract chapter/date data to CSV.

Usage:
    python parse_pdf.py                          # uses config.yaml
    python parse_pdf.py --config my_config.yaml
    python parse_pdf.py --url https://... --pdf-output out.pdf --csv-output out.csv
"""
from chaplib.config import Config

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Counter

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from chaplib import data


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

PAGE_NUM_START = 5
SPLIT_X = 140       # x position of vertical column divider
LINE_TOL = 2        # tolerance (pts) for grouping words into the same row
GAP_THRESHOLD = 15  # vertical gap (pts) that signals a new entry

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

CHAPTER_PATTERN = re.compile(
    r"\[?\bCh\.?\s*(\d+(?:\s*-\s*\d+|\s*,\s*\d+)*)\]?\s*(?:\.{1,3}|…)?\s*\d*\s*$"
)

DATE_PATTERNS = [
    ("range",       re.compile(r"(?P<m1>\d{1,2})/(?P<d1>\d{1,2})\s*[–-]\s*(?:(?P<wd2>[A-Za-z]{1,2})\s+)?(?P<m2>\d{1,2})/(?P<d2>\d{1,2})$")),
    ("date",        re.compile(r"(?:(?P<wd>[A-Za-z]{1,2})\s+)?(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2}))?(?:\s+(?P<label>[A-Za-z]+(?:\s+[A-Za-z]+){0,2}))?$")),
    ("offset",      re.compile(r"(?P<label>[A-Za-z]+)\s*\+\s*(?P<num>\d+)(?P<suffix>[A-Za-z]?)")),
    ("month_year",  re.compile(r"[A-Za-z]{3}\s+\d{4}\s+CE")),
    ("month_range", re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")),
]

SPECIAL_MAP = {
    "Early 2040 CE": ("date", {"wd": "or", "m": "2", "d": "01", "y": None, "label": None}),
    "Selection- 5-14": ("none", None),
}

NONE_STRINGS = {"Halloween", "", "September"}


# ---------------------------------------------------------------------------
# Chapter parsing
# ---------------------------------------------------------------------------

def shift_corrupted_chapter_string(s: str) -> str:
    """Fix OCR artefacts where a leading chapter number is split from its bracket."""
    m = re.match(r"^\s*(\d+)\]\s*(.*)$", s)
    if not m:
        return s

    num, rest = m.group(1), m.group(2)

    ch_match = re.search(r"\[Ch", rest)
    if not ch_match:
        return s

    prefix = rest[: ch_match.start()].strip()
    suffix = re.sub(r"\[Ch", f"[Ch {num}", rest[ch_match.start():].strip(), count=1)

    return (prefix + " " + suffix).strip()


def parse_chapters(s: str) -> list[tuple[int, ...]]:
    """Return a list of chapter tuples: (n,) for single, (a, b) for ranges."""
    s = shift_corrupted_chapter_string(s)
    m = CHAPTER_PATTERN.search(s)
    if not m:
        raise ValueError(f"Cannot parse chapters from: {s!r}")

    result = []
    for part in (p.strip() for p in m.group(1).split(",")):
        if "-" in part:
            a, b = map(int, part.split("-"))
            result.append((a, b))
        else:
            result.append((int(part),))

    return result


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_date(s: str) -> tuple[str, dict | None]:
    """Classify and parse a date string from the left column."""
    for key, value in SPECIAL_MAP.items():
        if key in s:
            return key, value

    s = s.replace("\u2019", "").replace("'", "")

    for name, pat in DATE_PATTERNS:
        m = pat.search(s.strip())
        if m:
            return name, m.groupdict()

    if re.compile(r"^(\d+)").search(s):
        return "footnote", None

    if s in NONE_STRINGS:
        return "empty", None

    raise ValueError(f"Cannot parse date from: {s!r}")


# ---------------------------------------------------------------------------
# PDF word extraction helpers
# ---------------------------------------------------------------------------

def group_words_into_rows(words: list[dict], tol: int = LINE_TOL) -> list[tuple[float, list[dict]]]:
    rows: dict[float, list[dict]] = defaultdict(list)
    for w in words:
        key = round(w["top"] / tol) * tol
        rows[key].append(w)
    return sorted(rows.items())


def get_body_font_size(page) -> float | None:
    sizes = [round(w["size"], 1) for w in page.chars if "size" in w]
    if not sizes:
        return None
    return Counter(sizes).most_common(1)[0][0]


def shift_words(words: list[dict], y_offset: float) -> list[dict]:
    shifted = []
    for w in words:
        w2 = w.copy()
        w2["top"] += y_offset
        w2["bottom"] += y_offset
        shifted.append(w2)
    return shifted


def extract_single_page_layout(pdf, page_range) -> list[dict]:
    """Merge words from multiple pages into a single coordinate space."""
    all_words: list[dict] = []
    y_offset = 0.0

    for page_num in page_range:
        page = pdf.pages[page_num]
        words = page.extract_words(use_text_flow=True)
        if words:
            all_words.extend(shift_words(words, y_offset))
        y_offset += page.height

    return all_words


def join_words_by_gap(words: list[dict], gap_threshold: float = 1.5) -> str:
    words = sorted(words, key=lambda w: w["x0"])
    if not words:
        return ""

    out = [words[0]["text"]]
    prev = words[0]

    for w in words[1:]:
        gap = w["x0"] - prev["x1"]
        out.append((" " if gap > gap_threshold else "") + w["text"])
        prev = w

    return "".join(out)


# ---------------------------------------------------------------------------
# PDF layout → entry list
# ---------------------------------------------------------------------------

def parse_pdf(pdf, page_range) -> list[dict[str, str]]:
    """Extract {left, right} entry pairs from the given page range."""
    entries: list[dict[str, str]] = []
    words = extract_single_page_layout(pdf, page_range)

    body_size = get_body_font_size(pdf.pages[11])
    print(f"Body font size: {body_size}")
    print(f"Total words extracted: {len(words)}")

    filtered = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    rows = group_words_into_rows(filtered, LINE_TOL)
    print(f"Total row groups: {len(rows)}")

    current = {"left": "", "right": ""}
    last_y: float | None = None

    for y, row_words in rows:
        row_words = sorted(row_words, key=lambda w: w["x0"])
        left_words  = [w for w in row_words if w["x1"] < SPLIT_X]
        right_words = [w for w in row_words if w["x0"] > SPLIT_X]

        if last_y is not None and abs(y - last_y) > GAP_THRESHOLD:
            if current["left"] or current["right"]:
                entries.append({"left": current["left"].strip(), "right": current["right"].strip()})
            current = {"left": "", "right": ""}

        if left_words:
            left_text = join_words_by_gap(left_words)
            current["left"] = (current["left"] + " " + left_text).strip()

        if right_words:
            right_text = join_words_by_gap(right_words)
            current["right"] = (current["right"] + " " + right_text).strip()

        last_y = y

    if current["left"] or current["right"]:
        entries.append({"left": current["left"].strip(), "right": current["right"].strip()})

    return entries


# ---------------------------------------------------------------------------
# Chapter/date expansion helpers
# ---------------------------------------------------------------------------

def iter_chapranges(chap_ranges: list[tuple[int, ...]]):
    for chap_range in chap_ranges:
        if len(chap_range) == 1:
            yield chap_range[0]
        elif len(chap_range) == 2:
            start, end = chap_range
            yield from range(start, end + 1)
        else:
            raise ValueError(f"Unexpected chapter range shape: {chap_range}")


# ---------------------------------------------------------------------------
# Offset base-date lookup
# Maps offset label strings (as they appear in the left column) to the
# datetime that represents offset 0 for that label.  Replace the example
# values below with the real anchor dates for your timeline.
# ---------------------------------------------------------------------------
OFFSET_BASE_DATES: dict[str, datetime] = {
    "sel":  datetime(2040, 2, 9),   # example — replace as needed
    "Summon":    datetime(2040, 2, 13),  # example — replace as needed
    "Summons":    datetime(2040, 2, 13),  # example — replace as needed
    "Chaos":   datetime(2040, 2, 23),   # example — replace as needed
}

HOURS_PER_NORMAL_DAY = 24
HOURS_PER_LONG_DAY   = 26   # suffix 'A'
current_year = 2040
last_month = None

def iter_datetimes(item: tuple[str, dict]):
    global current_year, last_month
    cls, date_data = item

    if cls == "date":
        m, d = int(date_data["m"]), int(date_data["d"])
        if last_month is not None and m < last_month:
            current_year += 1
        last_month = m
        yield datetime(current_year, m, d)

    elif cls == "range":
        m1, d1 = int(date_data["m1"]), int(date_data["d1"])
        m2, d2 = int(date_data["m2"]), int(date_data["d2"])

        if last_month is not None and m1 < last_month:
            current_year += 1
        last_month = m1

        start = datetime(current_year, m1, d1)
        end_year = current_year if m2 >= m1 else current_year + 1
        end = datetime(end_year, m2, d2)

        cur = start
        while cur <= end:
            yield cur
            cur += timedelta(days=1)

    elif cls == "offset":
        label  = date_data["label"]
        num    = int(date_data["num"])
        suffix = date_data.get("suffix", "") or ""

        base = OFFSET_BASE_DATES.get(label)
        if base is None:
            raise ValueError(
                f"Unknown offset label {label!r}. "
                f"Add it to OFFSET_BASE_DATES with an anchor datetime."
            )

        if suffix.upper() == "A":
            delta = timedelta(hours=num * HOURS_PER_LONG_DAY)
        else:
            delta = timedelta(hours=num * HOURS_PER_NORMAL_DAY)

        yield base + delta


def append_entry_to_chapter_data(
    chapter_data: dict[str, list],
    date: tuple[str, dict | None],
    chap_ranges: list[tuple[int, ...]],
) -> None:
    for dt in iter_datetimes(date):
        for chap in iter_chapranges(chap_ranges):
            chapter_data["chapter"].append(chap)
            chapter_data["date"].append(dt)


# ---------------------------------------------------------------------------
# Entry → structured data
# ---------------------------------------------------------------------------

def entries_to_chapter_data(entries: list[dict[str, str]], debug: bool = False) -> dict[str, list]:
    """Walk parsed entries and build chapter/date lists."""
    chapter_data: dict[str, list] = {"chapter": [], "date": []}
    skip = False
    start = False
    try_next = False
    prev_date = None

    for i, entry in enumerate(entries, 1):
        if entry["left"] == "Early 2040 CE":
            start = True
        if not start or skip:
            continue
        if entry["right"] == "Upcoming events:":
            skip = True
            continue

        if debug:
            print(f"\nEntry {i}")
        date_cls, date = parse_date(entry["left"])

        if date_cls == "footnote":
            continue

        if debug:
            print(f"  date : {date_cls} {date}")

        try:
            chap_ranges = parse_chapters(entry["right"])
            if debug:
                print(f"  chaps: {chap_ranges}")

            if try_next:
                # could be triggered by unrelated exception
                assert date_cls == "empty"
                append_entry_to_chapter_data(chapter_data, prev_date, chap_ranges)
                try_next = False
            else:
                append_entry_to_chapter_data(chapter_data, (date_cls, date), chap_ranges)

        except Exception as e:
            if try_next:
                raise
            try_next = True
            prev_date = (date_cls, date)

    return chapter_data


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_pdf(url: str, output_path: str) -> None:
    """Scrape *url* for the first <a> link, download the linked PDF."""
    session = requests.Session()
    res = session.get(url)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")
    a_tag = soup.find("a")
    if a_tag is None:
        raise RuntimeError(f"No <a> tag found on {url}")

    pdf_url = urljoin(url, a_tag["href"])
    print(f"PDF URL: {pdf_url}")

    pdf_res = session.get(pdf_url)
    pdf_res.raise_for_status()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(pdf_res.content)

    print(f"Saved PDF → {output_path}")



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a timeline PDF and extract chapter/date data to CSV."
    )
    parser.add_argument(
        "--config", default="config.yaml", metavar="FILE",
        help="YAML config file (default: config.yaml)",
    )
    pre, _ = parser.parse_known_args()
    cfg = Config.load(pre.config)

    parser.add_argument("--url", type=str, default=cfg.get("fetch.timeline.url"), metavar="URL",  help="Override timeline URL from config")
    parser.add_argument("--pdf-output", type=str, default=cfg.get("path.timeline.latest_pdf"), metavar="FILE", help="Override PDF output path from config")
    parser.add_argument("--csv-output", type=str, default=cfg.get("path.timeline.csv"), metavar="FILE", help="Override CSV output path from config")
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Skip downloading the PDF (use existing file at --pdf-output / config path)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print per-entry parsing details (Entry / date / chaps lines)",
    )
    return parser


# ---------------------------------------------------------------------------
# CSV merge
# ---------------------------------------------------------------------------

def merge_new_chapters(new_df: pd.DataFrame, csv_output: str) -> pd.DataFrame:
    """Merge *new_df* into an existing CSV, adding only chapters not already present.

    Rows whose ``chapter`` value already appears in the existing file are left
    untouched; only rows for brand-new chapters are appended.
    """
    path = Path(csv_output)
    if not path.exists():
        return new_df

    existing = pd.read_csv(path)
    existing_chapters = set(existing["chapter"].unique())

    additions = new_df[~new_df["chapter"].isin(existing_chapters)]
    print(f"Existing chapters: {len(existing_chapters)} | new rows to add: {len(additions)}")

    return pd.concat([existing, additions], ignore_index=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()


    # 1. Download
    if not args.skip_download:
        if not args.url:
            sys.exit("No URL provided. Set timeline.url in config.yaml or pass --url.")
        download_pdf(args.url, args.pdf_output)

    # 2. Parse PDF
    with pdfplumber.open(args.pdf_output) as pdf:
        entries = parse_pdf(pdf, range(PAGE_NUM_START, len(pdf.pages)))

    # 3. Extract structured data
    chapter_data = entries_to_chapter_data(entries, debug=args.debug)
    chapter_df   = pd.DataFrame(chapter_data)
    if args.debug:
        pd.set_option('display.max_rows', None)
        print(chapter_df)

    # 4. Merge with existing CSV (only add new chapters) and save
    Path(args.csv_output).parent.mkdir(parents=True, exist_ok=True)
    merged_df = merge_new_chapters(chapter_df, args.csv_output)
    data.save(merged_df, args.csv_output)
    print(f"\nSaved {len(merged_df)} rows → {args.csv_output}")


if __name__ == "__main__":
    main()
