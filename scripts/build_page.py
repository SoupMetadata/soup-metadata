#!/usr/bin/env python3
"""Build a self-contained static dashboard for the Patreon plots.

The generated page has no runtime dependencies and is suitable for deployment
to GitHub Pages.  Plot descriptions in ``PLOTS`` mirror the figures produced by
``scripts/plot_patreon.py``.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Plot:
    filename: str
    title: str
    summary: str


PLOTS = (
    Plot(
        filename="patreon_hours_late.png",
        title="Hours late by chapter",
        summary=(
            "Publication timing by chapter, colored by modifier. Zero separates "
            "early and late releases; dotted guides mark 24-hour intervals and "
            "vertical annotations show configured events."
        ),
    ),
    Plot(
        filename="patreon_histograms.png",
        title="Lateness distributions",
        summary=(
            "One-hour histograms for recent normal chapters, previews, chapters "
            "following previews, and entries marked approximate. All panels share "
            "the same hours-late axis."
        ),
    ),
    Plot(
        filename="patreon_word_count.png",
        title="Writing pace and chapter length",
        summary=(
            "Rolling words per day above and word count per chapter below. Orange "
            "lines show linear fits; red lines show sixth-degree polynomial fits."
        ),
    ),
    Plot(
        filename="patreon_monthly_bars.png",
        title="Monthly output",
        summary=(
            "Total published words and chapter count by month. Comparing the two "
            "panels distinguishes more frequent releases from longer chapters."
        ),
    ),
    Plot(
        filename="patreon_deadline_gap.png",
        title="Deadline spacing and lateness",
        summary=(
            "Hours late grouped by rounded days since the previous deadline. Boxes "
            "show quartiles, diamonds show means, and the lower panel gives the share "
            "of chapters in each lateness category. Shows if a specific deadline gap is "
            "advantageous or not."
        ),
    ),
    Plot(
        filename="patreon_arcs.png",
        title="Story arcs",
        summary=(
            "Length of detected numbered arcs over time, frequency of each arc length, "
            "and chapters between successive arcs."
        ),
    ),
)


ENTRY_RE = re.compile(
    r"^\s*(?P<hours>[+\-]?\d+(?:\.\d+)?\s*h|[—–-])"
    r"\s+(?P<modifier>.+?)"
    r"\s+(?P<words>\d[\d,]*|[—–-])"
    r"\s+(?P<chapter>\d+(?:\.\d+)?|[—–-])\s*$"
)
STAT_RE = re.compile(
    r"^\s*(?P<label>count|mean|std|min|25%|50%|75%|max)"
    r"\s+(?P<value>[+\-]?\d+(?:\.\d+)?|[—–-])\s*$",
    flags=re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the static Patreon statistics dashboard.",
    )
    parser.add_argument(
        "--recent-entries",
        required=True,
        metavar="FILE",
        help="Text file containing the recent-entry table from summarize.py.",
    )
    parser.add_argument(
        "--summary-stats",
        required=True,
        metavar="FILE",
        help="Text file containing summary statistics from summarize.py.",
    )
    parser.add_argument(
        "--images",
        default="build/images",
        metavar="DIR",
        help="Directory containing the six generated PNG files.",
    )
    parser.add_argument(
        "--output",
        default="build/index.html",
        metavar="FILE",
        help="Destination HTML file (default: build/index.html).",
    )
    parser.add_argument(
        "--title",
        default="Soup Chapter Metadata",
        help="Title displayed at the top of the page.",
    )
    parser.add_argument(
        "--allow-missing-images",
        action="store_true",
        help="Build the page even when one or more expected images are absent.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Could not read {path}: {exc}") from exc


def extract_heading(text: str, fallback: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if candidate and candidate.endswith(":"):
            return candidate[:-1]
    return fallback


def parse_entries(text: str) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    unparsed: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.endswith(":") or line.casefold().startswith("hours late"):
            continue
        match = ENTRY_RE.match(raw_line)
        if match:
            rows.append(match.groupdict())
        else:
            unparsed.append(raw_line)
    return rows, unparsed


def parse_stats(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    stats: list[tuple[str, str]] = []
    unparsed: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.endswith(":"):
            continue
        match = STAT_RE.match(raw_line)
        if match:
            stats.append((match.group("label").casefold(), match.group("value")))
        else:
            unparsed.append(raw_line)
    return stats, unparsed


def e(value: object) -> str:
    return html.escape(str(value), quote=True)


def display_chapter(value: str) -> str:
    if re.fullmatch(r"\d+\.0", value):
        return value[:-2]
    return value


def lateness_class(value: str) -> str:
    """Return the 12-hour color band for a formatted hours-late value."""
    match = re.search(r"[+\-]?\d+(?:\.\d+)?", value)
    if not match:
        return "timing-unknown"
    hours = float(match.group())
    if hours < -12:
        return "timing-early"
    if hours < 0:
        return "timing-slightly-early"
    if hours < 12:
        return "timing-under-12"
    if hours < 24:
        return "timing-under-24"
    if hours < 36:
        return "timing-under-36"
    return "timing-over-36"


def relative_url(path: Path, output_dir: Path) -> str:
    return Path(os.path.relpath(path, output_dir)).as_posix()


def chapter_sort_key(row: dict[str, str]) -> tuple[bool, float]:
    """Sort parsed chapters numerically, with unknown chapters at the end."""
    chapter = row["chapter"]
    if re.fullmatch(r"\d+(?:\.\d+)?", chapter):
        return True, float(chapter)
    return False, float("-inf")


def render_entries(text: str) -> str:
    heading = extract_heading(text, "Recent entries")
    rows, unparsed = parse_entries(text)
    if not rows:
        return f"""
        <section class="panel" id="recent">
          <div class="section-heading">
            <h2>{e(heading)}</h2>
          </div>
          <pre class="source-text">{e(text.strip())}</pre>
        </section>
        """

    rows.sort(key=chapter_sort_key, reverse=True)
    body = "\n".join(
        f'<tr data-chapter="{e(row["chapter"])}">'
        f"<td class=\"numeric\"><span class=\"timing {lateness_class(row['hours'])}\">{e(row['hours'])}</span></td>"
        f"<td><span class=\"tag\">{e(row['modifier'])}</span></td>"
        f"<td class=\"numeric\">{e(row['words'])}</td>"
        f"<td class=\"numeric chapter\">{e(display_chapter(row['chapter']))}</td>"
        "</tr>"
        for row in rows
    )
    fallback = ""
    if unparsed:
        fallback = (
            '<details class="source-details"><summary>Unparsed source lines</summary>'
            f'<pre class="source-text">{e(chr(10).join(unparsed))}</pre></details>'
        )
    return f"""
    <section class="panel" id="recent">
      <div class="section-heading">
        <h2>{e(heading)}</h2>
        <button class="order-toggle" type="button" data-order-toggle aria-controls="recent-entries-body">
          Show oldest first
        </button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Hours late</th><th>Modifier</th><th>Word count</th><th>Chapter</th></tr></thead>
          <tbody id="recent-entries-body">{body}</tbody>
        </table>
      </div>
      <div class="timing-legend" aria-label="Hours-late color scale">
        <span><i class="timing-early"></i>&lt; −12 h</span>
        <span><i class="timing-slightly-early"></i>−12–0 h</span>
        <span><i class="timing-under-12"></i>0–12 h</span>
        <span><i class="timing-under-24"></i>12–24 h</span>
        <span><i class="timing-under-36"></i>24–36 h</span>
        <span><i class="timing-over-36"></i>36+ h</span>
      </div>
      {fallback}
    </section>
    """


STAT_NAMES = {
    "count": "Entries",
    "mean": "Mean",
    "std": "Std. deviation",
    "min": "Minimum",
    "25%": "25th percentile",
    "50%": "Median",
    "75%": "75th percentile",
    "max": "Maximum",
}


def render_stats(text: str) -> str:
    heading = extract_heading(text, "Hours-late statistics")
    stats, unparsed = parse_stats(text)
    if not stats:
        return f"""
        <section class="panel" id="statistics">
          <div class="section-heading">
            <h2>{e(heading)}</h2>
          </div>
          <pre class="source-text">{e(text.strip())}</pre>
        </section>
        """

    items = []
    for key, value in stats:
        suffix = "" if key == "count" or value in {"—", "–", "-"} else " h"
        items.append(
            '<div class="stat">'
            f'<dt>{e(STAT_NAMES.get(key, key))}</dt>'
            f'<dd>{e(value)}{suffix}</dd>'
            "</div>"
        )
    fallback = ""
    if unparsed:
        fallback = (
            '<details class="source-details"><summary>Unparsed source lines</summary>'
            f'<pre class="source-text">{e(chr(10).join(unparsed))}</pre></details>'
        )
    return f"""
    <section class="panel" id="statistics">
      <div class="section-heading">
        <h2>{e(heading)}</h2>
      </div>
      <dl class="stats-list">{''.join(items)}</dl>
      {fallback}
    </section>
    """


def render_plots(images_dir: Path, output_dir: Path) -> str:
    figures = []
    for number, plot in enumerate(PLOTS, start=1):
        path = images_dir / plot.filename
        if not path.is_file():
            figures.append(
                f"""
                <article class="plot-card missing-plot">
                  <div class="plot-copy">
                    <h3>{e(plot.title)}</h3>
                    <p>{e(plot.summary)}</p>
                    <p class="missing-note">Plot unavailable: {e(plot.filename)}</p>
                  </div>
                </article>
                """
            )
            continue

        src = relative_url(path, output_dir)
        figures.append(
            f"""
            <article class="plot-card" id="plot-{number}">
              <div class="plot-copy">
                <h3>{e(plot.title)}</h3>
                <p>{e(plot.summary)}</p>
              </div>
              <figure>
                <a href="{e(src)}" aria-label="Open {e(plot.title)} at full size">
                  <img src="{e(src)}" alt="{e(plot.title)}" loading="lazy" decoding="async">
                </a>
              </figure>
            </article>
            """
        )
    return "\n".join(figures)


CSS = r"""
:root {
  --ink: #17243b;
  --muted: #64748b;
  --paper: #ffffff;
  --page: #f6f7f9;
  --line: #dfe3e8;
  --blue: #335caa;
  --blue-dark: #173769;
  color-scheme: light;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.6;
}
a { color: var(--blue); }
.hero {
  background: var(--paper);
  border-bottom: 1px solid var(--line);
}
.hero-inner, main, .footer-inner { width: min(1180px, calc(100% - 2rem)); margin-inline: auto; }
.hero-inner { padding: clamp(2rem, 5vw, 3.5rem) 0; }
.hero h1 {
  margin: 0;
  font-size: clamp(2rem, 5vw, 3.4rem);
  letter-spacing: -.035em;
  line-height: 1.05;
}
.generated { margin: .65rem 0 0; color: var(--muted); font-size: .88rem; }
main { padding: 2rem 0 4rem; }
.quick-nav {
  display: flex;
  flex-wrap: wrap;
  gap: .55rem;
  margin-bottom: 1.25rem;
}
.quick-nav a {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: .4rem .8rem;
  background: var(--paper);
  color: var(--blue-dark);
  font-size: .88rem;
  font-weight: 700;
  text-decoration: none;
}
.quick-nav a:hover { background: white; border-color: #aebfd8; }
.summary-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(300px, .65fr); gap: 1.25rem; }
.panel, .plot-card {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--paper);
}
.panel { padding: clamp(1.2rem, 3vw, 2rem); }
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.15rem;
}
.section-heading h2, .plots-heading h2 {
  margin: 0;
  font-size: clamp(1.35rem, 2.5vw, 1.8rem);
  line-height: 1.2;
}
.order-toggle {
  flex: none;
  border: 1px solid #aebfd8;
  border-radius: 7px;
  padding: .42rem .72rem;
  background: var(--paper);
  color: var(--blue-dark);
  font: inherit;
  font-size: .8rem;
  font-weight: 750;
  cursor: pointer;
}
.order-toggle:hover { background: #edf3fb; }
.order-toggle:focus-visible { outline: 3px solid #93c5fd; outline-offset: 2px; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 13px; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { padding: .72rem .82rem; border-bottom: 1px solid #e9eef5; text-align: left; white-space: nowrap; }
th { background: #edf3fb; color: #314767; font-size: .75rem; letter-spacing: .055em; text-transform: uppercase; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: #f8fafd; }
.numeric { text-align: right; }
.chapter { color: var(--blue-dark); font-weight: 800; }
.timing {
  display: inline-block;
  min-width: 5.2rem;
  border-radius: 6px;
  padding: .15rem .42rem;
  font-weight: 750;
  text-align: right;
}
.timing-early { background: #dbeafe; color: #1e40af; }
.timing-slightly-early { background: #e0f2fe; color: #075985; }
.timing-under-12 { background: #dcfce7; color: #166534; }
.timing-under-24 { background: #fef3c7; color: #92400e; }
.timing-under-36 { background: #ffedd5; color: #9a3412; }
.timing-over-36 { background: #fee2e2; color: #991b1b; }
.timing-unknown { background: #f1f5f9; color: #64748b; }
.timing-legend { display: flex; flex-wrap: wrap; gap: .45rem 1rem; margin-top: .85rem; color: var(--muted); font-size: .72rem; }
.timing-legend span { display: inline-flex; align-items: center; gap: .35rem; }
.timing-legend i { width: .72rem; height: .72rem; border-radius: 3px; }
.tag {
  display: inline-block;
  border-radius: 999px;
  padding: .16rem .52rem;
  background: #e9f0fb;
  color: #34547e;
  font-size: .77rem;
  font-weight: 750;
}
.stats-list { margin: 0; border-top: 1px solid var(--line); }
.stat { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; padding: .55rem .1rem; border-bottom: 1px solid var(--line); }
.stat dt { color: var(--muted); }
.stat dd { margin: 0; color: var(--blue-dark); font-weight: 750; font-variant-numeric: tabular-nums; }
.plots-heading { margin: 2.75rem 0 1rem; }
.plots { display: grid; gap: 1.4rem; }
.plot-card { display: grid; grid-template-columns: minmax(235px, .42fr) minmax(0, 1.58fr); }
.plot-copy { padding: clamp(1.1rem, 2.5vw, 1.65rem); }
.plot-copy h3 { margin: 0 0 .55rem; font-size: clamp(1.2rem, 2vw, 1.5rem); line-height: 1.2; }
.plot-copy > p { margin: 0; color: #52627a; font-size: .92rem; }
figure { display: grid; place-items: center; align-content: center; margin: 0; padding: 1rem; background: #eaf0f7; border-left: 1px solid var(--line); }
figure a { display: block; line-height: 0; }
figure img { display: block; width: 100%; height: auto; max-height: 740px; object-fit: contain; border-radius: 7px; background: white; }
.missing-plot { display: block; border-style: dashed; }
.missing-note { border-radius: 10px; padding: .7rem .8rem; background: #fff1df; color: #85460e !important; font-weight: 700; }
.source-details { margin-top: 1rem; color: var(--muted); font-size: .85rem; }
.source-text { overflow-x: auto; border-radius: 10px; padding: 1rem; background: #f4f7fb; color: #34445d; font-size: .8rem; }
footer { border-top: 1px solid var(--line); color: var(--muted); background: var(--paper); }
.footer-inner { padding: 1.5rem 0; font-size: .82rem; }
@media (max-width: 850px) {
  .summary-grid, .plot-card { grid-template-columns: 1fr; }
  figure { border-top: 1px solid var(--line); border-left: 0; }
}
@media (max-width: 520px) {
  .hero-inner, main, .footer-inner { width: min(100% - 1rem, 1180px); }
  .section-heading { align-items: flex-start; flex-direction: column; }
  th, td { padding: .62rem .68rem; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""


def build_page(args: argparse.Namespace) -> str:
    recent_path = Path(args.recent_entries)
    stats_path = Path(args.summary_stats)
    images_dir = Path(args.images)
    output_path = Path(args.output)

    missing = [plot.filename for plot in PLOTS if not (images_dir / plot.filename).is_file()]
    if missing and not args.allow_missing_images:
        joined = "\n  - ".join(missing)
        raise SystemExit(
            f"Expected plot files are missing from {images_dir}:\n  - {joined}\n"
            "Run plot_patreon.py first, or pass --allow-missing-images."
        )

    recent_text = read_text(recent_path)
    stats_text = read_text(stats_path)
    generated = datetime.now(timezone.utc)
    generated_machine = generated.isoformat(timespec="seconds")
    generated_human = generated.strftime("%d %B %Y at %H:%M UTC")

    entries_html = render_entries(recent_text)
    stats_html = render_stats(stats_text)
    plots_html = render_plots(images_dir, output_path.parent)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Latest Patreon chapter timing, output, cadence, and story-arc statistics.">
  <title>{e(args.title)}</title>
  <style>{CSS}</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <h1>{e(args.title)}</h1>
      <p class="generated">Updated <time datetime="{e(generated_machine)}">{e(generated_human)}</time></p>
    </div>
  </header>
  <main>
    <nav class="quick-nav" aria-label="Page sections">
      <a href="#recent">Recent entries</a>
      <a href="#statistics">Summary statistics</a>
      <a href="#visual-analysis">Visual analysis</a>
    </nav>
    <div class="summary-grid">
      {entries_html}
      {stats_html}
    </div>
    <section id="visual-analysis">
      <div class="plots-heading">
        <h2>Plots</h2>
      </div>
      <div class="plots">{plots_html}</div>
    </section>
  </main>
  <footer><div class="footer-inner">Generated from the latest chapter data.</div></footer>
  <script>
    const orderToggle = document.querySelector("[data-order-toggle]");
    const entriesBody = document.querySelector("#recent-entries-body");
    if (orderToggle && entriesBody) {{
      let newestFirst = true;
      orderToggle.addEventListener("click", () => {{
        const rows = Array.from(entriesBody.rows);
        rows.reverse().forEach((row) => entriesBody.appendChild(row));
        newestFirst = !newestFirst;
        orderToggle.textContent = newestFirst ? "Show oldest first" : "Show newest first";
      }});
    }}
  </script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    page = build_page(args)
    try:
        output.write_text(page, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Could not write {output}: {exc}") from exc
    print(f"Wrote {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
