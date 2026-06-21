from collections import defaultdict
from email import policy
from email.parser import BytesParser
import re
from typing import Callable, Any
import os
import logging
import requests
import email
from email.header import decode_header, make_header
from urllib.parse import urlparse, urljoin
import chaplib.parse
import bs4
import pandas as pd
import pickle
import imaplib

logger = logging.getLogger(__name__)


def _get_soup(url):
    html = requests.get(url).text
    soup = bs4.BeautifulSoup(html, "html.parser")
    return soup

class ChapterLock:
    def __init__(self, lock_path: str):
        parent_dir = os.path.dirname(lock_path)
        if parent_dir and not os.path.exists(parent_dir):
            raise ValueError(f"parent directory does not exist: {parent_dir}")

        self.lock_path = lock_path
        if not os.path.exists(lock_path):
            logger.info(f"Lock file not found, initializing at {lock_path}")
            self._chapter = -1
            self._write(-1)
        else:
            self._chapter = self._read()
            logger.info(f"Loaded existing lock at {lock_path} (chapter {self._chapter})")

    def _write(self, chapter: int):
        with open(self.lock_path, "w") as f:
            f.write(str(chapter))

    def _read(self) -> int:
        with open(self.lock_path, "r") as f:
            return int(f.readline())

    def lock(self, chapter: int):
        if chapter < self._chapter:
            logger.warning(f"Attempted to lock chapter {chapter}, but current lock chapter is {self._chapter}. Exiting.")
            return
        logger.info(f"Locking chapter {chapter} (previously {self._chapter})")
        self._chapter = chapter
        self._write(chapter)

    def get_lock(self) -> int:
        logger.debug(f"Getting lock: chapter {self._chapter}")
        return self._chapter

    def make_gated_function(self, func: Callable[[bs4.BeautifulSoup], Any]):
        def gated_function(soup: bs4.BeautifulSoup, chapter: int):
            if chapter <= self._chapter:
                return None
            res = func(soup)
            return res
        return gated_function

    def make_ungated_function(self, func: Callable[[bs4.BeautifulSoup], Any]):
        def ungated_function(soup: bs4.BeautifulSoup, chapter: int):
            return func(soup)
        return ungated_function


_chapter_id_pattern = re.compile(r'/chapter/(\d+)/')
class RoyalRoadFetch:
    def __init__(self, fiction_url: str, cache_path: str | None = None, cache_refresh=False):
        self._fiction_url = fiction_url
        parsed = urlparse(fiction_url)
        self._root_url = f"{parsed.scheme}://{parsed.netloc}"
        self._data = self._get_chapter_overview()
        self._soup_col = "_soup"
        self._cache_path = cache_path
        self._cache_refresh = cache_refresh
        if self._cache_path is not None and not self._cache_refresh and not os.path.exists(self._cache_path):
            raise ValueError(f"cache path must exist: {self._cache_path}")

    def _get_chapter_overview(self):

        soup = _get_soup(self._fiction_url)
        chapters = soup.select(".chapter-row")
        data = defaultdict(list)
        for chapter in chapters:
            title = chapter.find("a").get_text().strip()
            data["title"].append(title)
            data["chapter"].append(chaplib.parse.title_to_chapter(title))
            data["published"].append(
                    pd.to_datetime(chapter.find("time")["datetime"],
                                   utc=True))
            url = urljoin(self._root_url, chapter.find("a")["href"])
            data["url"].append(url)
            chapter_id_match = _chapter_id_pattern.search(url)
            if chapter_id_match is None:
                raise RuntimeError(f"could not match pattern {_chapter_id_pattern} to url {url}")
            data["id"].append(int(chapter_id_match.group(1)))

        return pd.DataFrame(data)

    def apply_function_map(self, fmap: dict[str, Callable[[bs4.BeautifulSoup, int], Any]]):
        for name in fmap.keys():
            if name == self._soup_col or name in self._data.index:
                raise ValueError(f"name in fmap {name} cannot be {self._soup_col} or in {self._data.index}")

        if self._soup_col not in self._data.columns:
            self._get_urls()
        for name, func in fmap.items():
            self._data[name] = [func(a, b) for a, b in zip(self._data[self._soup_col], self._data["chapter"])]
        return self._data

    def _get_urls(self):
        if self._cache_path is not None:
            # Load existing cache or start fresh
            if not self._cache_refresh:
                with open(self._cache_path, "rb") as f:
                    cache = pickle.load(f)
            else:
                cache = {}

            def _get_soup_cached(url):
                if url not in cache:
                    print("cache miss")
                    cache[url] = _get_soup(url)
                return cache[url]

            self._data[self._soup_col] = self._data["url"].apply(_get_soup_cached)

            # Persist cache once after all URLs are processed
            with open(self._cache_path, "wb") as f:
                pickle.dump(cache, f)
        else:
            self._data[self._soup_col] = self._data["url"].apply(_get_soup)


    def get_data(self):
        if self._soup_col in self._data.columns:
            ret = self._data.drop([self._soup_col, "url"], axis=1)
        else:
            ret = self._data.drop(["url"], axis=1)
        return ret

class PatreonEmailFetch:
    def __init__(self, imap_server, imap_port, email_name, password, search_inbox="inbox", search_string="sleyca"):
        self._soup_col = "_soup"

        imap = imaplib.IMAP4(imap_server, port=imap_port)
        imap.login(email_name, password)
        imap.select(search_inbox)
        _, messages = imap.search(None, f'(TEXT "{search_string}")')
        data = defaultdict(list)
        mail_ids = messages[0].split()
        for mail_id in mail_ids:
            _, msg_data = imap.fetch(mail_id, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            decoded = str(make_header(decode_header(msg["Subject"])))
            decoded = decoded.replace("\r\n", "")
            match = re.search(r'"(.+?)"', decoded, re.DOTALL)
            if match is not None:
                decoded = match.group(1)
            data["title"].append(decoded.strip())
            data["chapter"].append(chaplib.parse.title_to_chapter(decoded))
            data["published"].append(pd.to_datetime(msg["Date"]))

            html_content = None
            msg = BytesParser(policy=policy.default).parsebytes(raw_email)
            html_part = msg.get_body(preferencelist=('html',))
            if html_part:
                html_content = html_part.get_content()
            else:
                raise RuntimeError(f"{decoded}")

            if html_content is not None:
                soup = bs4.BeautifulSoup(html_content, "html.parser")
                data[self._soup_col].append(soup)
            else:
                raise RuntimeError(f"no html_content found in message with subject {decoded}")

            self._data = pd.DataFrame(data)
        imap.logout()

    def apply_function_map(self, fmap: dict[str, Callable[[bs4.BeautifulSoup, int], Any]]):
        for name in fmap.keys():
            if name == self._soup_col or name in self._data.index:
                raise ValueError(f"name in fmap {name} cannot be {self._soup_col} or in {self._data.index}")

        for name, func in fmap.items():
            self._data[name] = [func(a, b) for a, b in zip(self._data[self._soup_col], self._data["chapter"])]
        return self._data


    def get_data(self):
        if self._soup_col in self._data.columns:
            ret = self._data.drop(self._soup_col, axis=1)
        else:
            ret = self._data.copy()
        return ret










