from chaplib import fetch, data
from chaplib.config import Config
import argparse

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="config.yaml", metavar="FILE",
        help="YAML config file (default: config.yaml)",
    )
    pre, _ = parser.parse_known_args()
    cfg = Config.load(pre.config)
    parser.add_argument('--chapters-csv', type=str, default=cfg.get("path.royalroad.chapters_csv"))
    parser.add_argument('--cache-path', type=str, default=cfg.get("path.royalroad.cache"))
    parser.add_argument('--cache-refresh', action="store_true", default=cfg.get("fetch.royalroad.cache_refresh"))
    parser.add_argument('--lock-path', type=str, default=cfg.get("path.royalroad.lock"))
    parser.add_argument('--url', type=str, default=cfg.get("fetch.royalroad.url"))
    return parser.parse_args()


def soup_to_word_count(soup):
    content = soup.select_one(".chapter-inner")
    paragraphs = [span.get_text() for span in content.find_all("span") if "style" in span.attrs and "italic" not in span["style"]]
    if len(paragraphs) < 10:
        paragraphs = [span.get_text() for span in content.find_all("p")]
    text = "\n\n".join(paragraphs)
    word_count = len(text.split())
    return word_count

def main():
    args = parse_args()

    locker = fetch.ChapterLock(args.lock_path)
    fetcher = fetch.RoyalRoadFetch(args.url, cache_path=args.cache_path, cache_refresh=args.cache_refresh)
    fetcher.apply_function_map({
        "word_count": locker.make_gated_function(soup_to_word_count)
        })
    df = fetcher.get_data()
    df_updated_chapters = data.merge_initial(
        data.load(args.chapters_csv),
        df
    )
    data.save(df_updated_chapters, args.chapters_csv)

if __name__ == "__main__":
    main()
