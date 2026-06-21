import re
import pandas as pd
from bs4 import BeautifulSoup

chapter_maps = [
        {
            "THREE HUNDRED": 300,
            "TWO HUNDRED": 200,
            "ONE HUNDRED": 100,
            },
        {
            "TEN": 10,
            "ELEVEN": 11,
            "TWELVE": 12,
            "THIRTEEN": 13,
            "FOURTEEN": 14,
            "FIFTEEN": 15,
            "SIXTEEN": 16,
            "SEVENTEEN": 17,
            "EIGHTEEN": 18,
            "NINETEEN": 19,
            "TWENTY": 20,
            "THIRTY": 30,
            "FOURTY": 40,
            "FORTY": 40,
            "FIFTY": 50,
            "SIXTY": 60,
            "SEVENTY": 70,
            "EIGHTY": 80,
            "NINETY": 90,
            },
        {
            "ONE": 1,
            "TWO": 2,
            "THREE": 3,
            "FOUR": 4,
            "FIVE": 5,
            "SIX": 6,
            "SEVEN": 7,
            "EIGHT": 8,
            "NINE": 9,
            }
        ]

def title_to_chapter(title):
    num = 0
    title = title.lower()
    if "ripples iii" in title:
        return 132
    if "ripples ii" in title:
        return 131
    if "ripples iv" in title:
        return 133
    title = title.split(":", 1)[0]
    for chapter_map in chapter_maps:
        for key, val in chapter_map.items():
            idx = title.find(key.lower())
            if idx != -1:
                num += val
                title = title[:idx] + title[idx + len(key):]
    if num != 0:
        return num
    result = re.search(r"(\d+)", title)
    if result is not None:
        return int(result.group(1))
    return None



def count_english_words(text):
    if pd.isna(text):
        return None
    return len(text.split())

def format_text(html_text):
    if html_text is None:
        return None
    soup = BeautifulSoup(html_text, 'html.parser')
    text = soup.get_text(separator=' ')
    return str(text)


