from chaplib import fetch, data
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import pytz
import re
import pandas as pd
import argparse
import yaml

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default="config.yaml")
    parser.add_argument('--initial-path', type=str, default="data/patreon/initial.csv")
    parser.add_argument('--deadlines-path', type=str, default="data/patreon/deadlines.csv")
    parser.add_argument('--lock-path', type=str, default="data/patreon/lock")
    return parser.parse_args()

def load_config(config_path):
    with open(config_path) as f:
        config = yaml.safe_load(f)
    settings = config['email_settings']
    return (
        settings['imap_server'],
        settings['imap_port'],
        settings['email'],
        settings['password']
    )

def soup_to_id(soup):
    arr = soup.select('a[href*="post_id="]')
    if len(arr) != 0:
        href = arr[0]["href"]
        qs = parse_qs(urlparse(href).query)
        post_id = int(qs.get('post_id')[0])
        return post_id
    
    links = soup.select('a[href*="patreon.com/posts/"]')
    if len(links) != 0:
        path = urlparse(links[0]["href"]).path
        post_id = path.split("-")[-1]
        return int(post_id)
    return None


def soup_to_word_count(soup):
    content = soup.select(".post-content")
    if len(content) != 0:
        text = content[0].get_text(separator=" ", strip=True)
        word_count = len(text.split(" "))
        return word_count
    content = soup.select(".dys-column-per-100 table")
    if len(content) != 0:
        max_word_count = 0
        for table in content:
            word_count = sum(len(p.get_text().split()) for p in table.find_all('p'))
            max_word_count = max(max_word_count, word_count)
        return max_word_count
    content = soup.select("span")
    if len(content) != 0:
        max_word_count = 0
        for table in content:
            word_count = sum(len(p.get_text().split()) for p in table.find_all('p'))
            max_word_count = max(max_word_count, word_count)
        return max_word_count
    return None

date_pattern = re.compile(
    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    r'\s+(\d{1,2}),\s+(\d{4})\b'
)
next_chapter_pattern = re.compile(
        r"Next Chapter\s?:\s+([A-Za-z]+\s+\d+)(?:\s*\(([^)]+)\))?"
)
def soup_to_next_chapter(soup):
    next_match = next_chapter_pattern.search(str(soup))
    if next_match is None:
        return None
    # Next Chapter: April 7 (approximate)
    deadline_str = next_match.group(1)
    parsed = None
    for fmt in ('%B %d', '%b %d'):
        try:
            parsed = datetime.strptime(deadline_str, fmt)
        except ValueError:
            continue
    candidate = datetime(
        year=datetime.now().year,
        month=parsed.month,
        day=parsed.day,
        hour=23,
        minute=59
    )
    pst = pytz.timezone("America/Los_Angeles")
    candidate = pst.localize(candidate)

    sent_pst = None
    for tag in soup.find_all(string=date_pattern):
        matches = date_pattern.findall(tag)
        for match in matches:
            month, day, year = match
            dt = datetime.strptime(f"{month} {day}, {year}", "%b %d, %Y")
            sent_pst = pst.localize(dt)


    if sent_pst is not None and candidate <= sent_pst:
        candidate = candidate.replace(year=candidate.year + 1)
    return candidate.strftime("%B %d %Y %H:%M")

def soup_to_modifier(soup):
    next_match = next_chapter_pattern.search(str(soup))
    if next_match is None:
        return None
    # Next Chapter: April 7 (approximate)
    return next_match.group(2)

def main():
    # setup
    args = parse_args()
    imap_server, imap_port, email, password = load_config(args.config)
    locker = fetch.ChapterLock(args.lock_path)
    fetcher = fetch.PatreonEmailFetch(imap_server, imap_port, email, password)

    # apply function to soup
    fetcher.apply_function_map({
        "id": locker.make_ungated_function(soup_to_id),
        "word_count": locker.make_gated_function(soup_to_word_count),
        "next_deadline": locker.make_gated_function(soup_to_next_chapter),
        "reference_id": locker.make_gated_function(lambda x: None),
        "next_modifier": locker.make_gated_function(soup_to_modifier),
        })

    # post-processing
    df = fetcher.get_data()
    df = df.sort_values("published").reset_index(drop=True)

    df["reference_id"] = df["id"].shift(-1)
    df["reference_id"] = df["reference_id"].where(df["title"].str.contains(r"\(preview\)", case=False))

    df = pd.concat([df, pd.DataFrame([{col: None for col in df.columns}])], ignore_index=True)
    df["deadline"] = df["next_deadline"].shift(1)
    df["modifier"] = df["next_modifier"].shift(1)

    pd.set_option('display.max_columns', None)
    # merge with original files
    df_updated_initial = data.merge_initial(
        data.load(args.initial_path),
        df
    )
    data.save(df_updated_initial, args.initial_path)
    df_updated_deadlines = data.merge_deadlines(
        data.load(args.deadlines_path),
        df
    )
    data.save(df_updated_deadlines, args.deadlines_path)

if __name__ == "__main__":
    main()
