from datetime import datetime, timedelta
import re
import pandas as pd
from typing import Counter
import pdfplumber
from pypdf import PdfReader
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from collections import defaultdict
import seaborn as sns
import matplotlib.pyplot as plt

url = "https://terrestrialbiped.github.io/Super-Supportive-Timeline/patreon-latest.html"
output = "data/patreon/latest.pdf"

# session = requests.Session()
# res = session.get(url)
#
# soup = BeautifulSoup(res.text, "html.parser")
#
# # find the link (adjust selector as needed)
# a_tag = soup.find("a")
#
# pdf_url = urljoin(url, a_tag["href"])
# print("PDF URL:", pdf_url)
#
# # now download it
# pdf_res = session.get(pdf_url)
#
# with open(output, "wb") as f:
#     f.write(pdf_res.content)

pattern = re.compile(r"\[?\bCh\.?\s*(\d+(?:\s*-\s*\d+|\s*,\s*\d+)*)\]?\s*(?:\.{1,3}|…)?\s*\d*\s*$")

def shift_corrupted_chapter_string(s: str) -> str:
        # 1. match leading pattern like "27]"
    m = re.match(r"^\s*(\d+)\]\s*(.*)$", s)
    if not m:
        return s

    num = m.group(1)
    rest = m.group(2)

    # 2. find first broken [Ch somewhere in string
    ch_match = re.search(r"\[Ch", rest)
    if not ch_match:
        return s

    prefix = rest[:ch_match.start()].strip()
    suffix = rest[ch_match.start():].strip()

    # 3. replace only FIRST "[Ch" with "[Ch <num>"
    suffix = re.sub(r"\[Ch", f"[Ch {num}", suffix, count=1)

    # 4. rebuild
    return (prefix + " " + suffix).strip()

def parse_chapters(s):
    s = shift_corrupted_chapter_string(s)
    m = pattern.search(s)
    if not m:
        raise ValueError(s)

    raw = m.group(1)

    parts = [p.strip() for p in raw.split(",")]

    result = []

    for p in parts:
        if "-" in p:
            a, b = map(int, p.split("-"))
            result.append((a, b))
        else:
            result.append((int(p),))

    return result

special_map = {
    "Early 2040 CE": ("date", {'wd': 'or', 'm': '2', 'd': '01', 'y': None, 'label': None}),
    "Selection- 5-14": ("none", None),
}

patterns = [
    ("range", re.compile(r"(?P<m1>\d{1,2})/(?P<d1>\d{1,2})\s*[–-]\s*(?:(?P<wd2>[A-Za-z]{1,2})\s+)?(?P<m2>\d{1,2})/(?P<d2>\d{1,2})$")),
    ("date", re.compile(r"(?:(?P<wd>[A-Za-z]{1,2})\s+)?(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2}))?(?:\s+(?P<label>[A-Za-z]+(?:\s+[A-Za-z]+){0,2}))?$")),
    ("offset", re.compile(r"(?P<label>[A-Za-z]+)\s*\+\s*(?P<num>\d+)(?P<suffix>[A-Za-z]?)")),
    ("month_year", re.compile(r"[A-Za-z]{3}\s+\d{4}\s+CE")),
    ("month_range", re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")),
]

none_str = ["Halloween", "", "September"]

def parse_date(s: str):
    for key in special_map:
        if key in s:
            return key, special_map[key]
    s = s.replace("’","")
    for name, pat in patterns:
        m = pat.search(s.strip())
        if m:
            return name, m.groupdict()
    m = re.compile(r"^(\d+)").search(s)
    if m is not None:
        return ("footnote", None)
    if s in none_str:
        return ("empty", None)
    raise ValueError(s)

PAGE_NUM_START = 5

# tweak these based on your PDF
SPLIT_X = 140     # x position of vertical divider
LINE_TOL = 2      # how tightly to group words into same row
GAP_THRESHOLD = 15  # vertical gap that indicates a new entry


def group_words_into_rows(words, tol=2):
    rows = defaultdict(list)

    for w in words:
        key = round(w["top"] / tol) * tol
        rows[key].append(w)

    return sorted(rows.items(), key=lambda x: x[0])


def get_body_font_size(page):
    """
    Estimate main body font size using frequency.
    Most common font size = body text.
    """
    sizes = [round(w["size"], 1) for w in page.chars if "size" in w]

    if not sizes:
        return None

    freq = Counter(sizes)
    body_size = freq.most_common(1)[0][0]

    return body_size

def shift_words(words, y_offset):
    """
    Shift all word coordinates so pages become one continuous page.
    """
    shifted = []

    for w in words:
        w2 = w.copy()

        w2["top"] += y_offset
        w2["bottom"] += y_offset

        shifted.append(w2)

    return shifted


def extract_single_page_layout(pdf, page_range):
    all_words = []
    y_offset = 0


    for page_num in page_range:
        page = pdf.pages[page_num]
        words = page.extract_words(use_text_flow=True)

        if not words:
            y_offset += page.height
            continue

        # shift page into global coordinate space
        shifted = shift_words(words, y_offset)
        all_words.extend(shifted)

        # move offset down by page height
        y_offset += page.height

    return all_words

def join_words_by_gap(words, gap_threshold=1.5):
    words = sorted(words, key=lambda w: w["x0"])

    if not words:
        return ""

    out = [words[0]["text"]]
    prev = words[0]

    for w in words[1:]:
        gap = w["x0"] - prev["x1"]

        if gap > gap_threshold:
            out.append(" " + w["text"])
        else:
            out.append(w["text"])

        prev = w

    return "".join(out)

def parse_pdf(pdf, page_range):
    entries = []

    words = extract_single_page_layout(pdf, page_range)

    body_size = get_body_font_size(pdf.pages[11])
    print(body_size)
    print(len(words), words[0])
    filtered = words 
    filtered = sorted(filtered, key=lambda w: (round(w["top"], 1), w["x0"]))
    rows = group_words_into_rows(filtered, LINE_TOL)
    print(len(rows))

    current = {"left": "", "right": ""}
    last_y = None


    for y, row_words in rows:

        # sort words left → right
        row_words = sorted(row_words, key=lambda w: w["x0"])

        # split into columns (still valid)
        left_words = [w for w in row_words if w["x1"] < SPLIT_X]
        right_words = [w for w in row_words if w["x0"] > SPLIT_X]

        # detect vertical gap → new entry
        if last_y is not None and abs(y - last_y) > GAP_THRESHOLD:
            if current["left"] or current["right"]:
                entries.append({
                    "left": current["left"].strip(),
                    "right": current["right"].strip()
                })
            current = {"left": "", "right": ""}

        # FIX: reconstruct properly instead of naive join
        if left_words:
            left_text = join_words_by_gap(left_words)
            current["left"] += " " + left_text if current["left"] else left_text

        if right_words:
            right_text = join_words_by_gap(right_words)
            current["right"] += " " + right_text if current["right"] else right_text

        last_y = y


    # append last entry
    if current["left"] or current["right"]:
        entries.append({
            "left": current["left"].strip(),
            "right": current["right"].strip()
        })

    print(entries)
    return entries

def iter_chapranges(chap_range):
    for chap_range in chap_ranges:
        if len(chap_range) == 1:
            start_chap = chap_range[0]
            end_chap = chap_range[0]
        elif len(chap_range) == 2:
            start_chap = chap_range[0]
            end_chap = chap_range[1]
        else:
            raise ValueError(chap_range)

        for chap in range(start_chap, end_chap+1):
            yield chap

def iter_datetimes(item, start_year=2040):
    current_year = start_year
    last_month = None
    cls, data = item

    if cls == "date":
        m = int(data["m"])
        d = int(data["d"])

        # detect year rollover
        if last_month is not None and m < last_month:
            current_year += 1

        dt = datetime(current_year, m, d)
        last_month = m

        yield dt

    elif cls == "range":
        m1, d1 = int(data["m1"]), int(data["d1"])
        m2, d2 = int(data["m2"]), int(data["d2"])

        # detect rollover at start
        if last_month is not None and m1 < last_month:
            current_year += 1

        start = datetime(current_year, m1, d1)

        # detect if range crosses year boundary
        end_year = current_year if m2 >= m1 else current_year + 1
        end = datetime(end_year, m2, d2)

        # yield every day in the range (inclusive)
        cur = start
        while cur <= end:
            yield cur
            cur += timedelta(days=1)

        last_month = m2

def append_entry_to_chapter_data(chapter_data, date, chap_ranges):
    for date in iter_datetimes(date):
        for chap in iter_chapranges(chap_ranges):
            chapter_data["chapter"].append(chap)
            chapter_data["date"].append(date)

def filter_almost_monotonic(df, col, max_jump=5):
    keep_indices = []
    
    last_val = None
    
    for i, val in df[col].items():
        if last_val is None:
            keep_indices.append(i)
            last_val = val
        else:
            if abs(val - last_val) <= max_jump:
                keep_indices.append(i)
                last_val = val
            # else: skip this row (do NOT update last_val)

    return df.loc[keep_indices]

if __name__ == "__main__":
    with pdfplumber.open(output) as pdf:
        results = parse_pdf(pdf, range(PAGE_NUM_START, len(pdf.pages)))

    skip = False
    start = False
    try_next = False
    prev_date = None
    parsed = []
    chapter_data = {"chapter": [], "date": []}

    for i, entry in enumerate(results, 1):
        if entry["left"] == "Early 2040 CE":
            start = True
        if not start:
            continue
        if skip:
            continue
        if entry["right"] == "Upcoming events:":
            skip = True
            continue
        print(f"\nEntry {i}")
        # print("LEFT :", entry["left"])
        date_cls, date = parse_date(entry["left"])
        if date_cls == "footnote":
            continue
        print("parse date:", date_cls, date)
        # print("RIGHT:", entry["right"])
        try:
            chap_ranges = parse_chapters(entry["right"])
            print("parse chapter:", chap_ranges)
            if try_next:
                assert date_cls == "empty"
                append_entry_to_chapter_data(chapter_data, prev_date, chap_ranges)
                try_next = False
            else:
                append_entry_to_chapter_data(chapter_data, (date_cls, date), chap_ranges)

        except Exception as e:
            if try_next:
                raise e
            else:
                try_next = True
                prev_date = (date_cls, date)
                continue



    chapter_df = pd.DataFrame(chapter_data)
    filtered = chapter_df[chapter_df['chapter'].diff().le(29) | chapter_df['chapter'].diff().isna()]
    filtered = filtered.sort_values(by='date')
    agg_num_days = 10
    rate = (
    filtered.set_index('date')
      .rolling(f'{agg_num_days}D')['chapter']
      .count()
      .rename(f'chapters_per_{agg_num_days}d')
      .reset_index()
    )
    sns.lineplot(data=rate, x='date', y=f'chapters_per_{agg_num_days}d')
    plt.title(f"In-Story Time (Chapters per Previous {agg_num_days} Days)")
    plt.show()

