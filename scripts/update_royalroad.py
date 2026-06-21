from chaplib import fetch, data
import argparse
import yaml

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default="config.yaml")
    parser.add_argument('--initial-path', type=str, default="data/royalroad/initial.csv")
    parser.add_argument('--cache-path', type=str, default="data/royalroad/cache")
    parser.add_argument('--cache-refresh', action="store_true")
    parser.add_argument('--lock-path', type=str, default="data/royalroad/lock")
    return parser.parse_args()

def load_config(config_path):
    with open(config_path) as f:
        config = yaml.safe_load(f)
    settings = config['royalroad_fetch']
    return settings['url']

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
    url = load_config(args.config)

    locker = fetch.ChapterLock(args.lock_path)
    fetcher = fetch.RoyalRoadFetch(url, cache_path=args.cache_path, cache_refresh=args.cache_refresh)
    fetcher.apply_function_map({
        "word_count": locker.make_gated_function(soup_to_word_count)
        })
    df = fetcher.get_data()
    df_updated_initial = data.merge_initial(
        data.load(args.initial_path),
        df
    )
    data.save(df_updated_initial, args.initial_path)

if __name__ == "__main__":
    main()

