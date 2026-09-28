#!/usr/bin/env python3
"""Fetches the BCU Media EPG feed, filters it down to sport channels and
renders a static TV-guide site (HTML + JSON + Markdown) into dist/.

Runs daily via .github/workflows/deploy.yml. No third-party dependencies:
only the Python standard library, so it needs nothing beyond `python3` in CI.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

EPG_URL = "https://epg.bcumedia.pro/epg.xml"
ROOT = Path(__file__).resolve().parent.parent
WEB_SRC = ROOT / "web"
OUT_DIR = ROOT / "dist"

# How much of the schedule to keep, relative to "now" at build time.
LOOKBACK = timedelta(hours=3)
LOOKAHEAD = timedelta(days=3)

# A channel counts as "Спорт" if its id/name matches any of these.
SPORT_RE = re.compile(r"sport|спорт", re.IGNORECASE)
MATCH_TV_RE = re.compile(r"^матч", re.IGNORECASE)

WEEKDAYS_CS = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]


def is_sport_channel(channel_id: str, name: str) -> bool:
    haystack = f"{channel_id} {name}"
    if SPORT_RE.search(haystack):
        return True
    if MATCH_TV_RE.search(channel_id.strip()):
        return True
    return False


def parse_xmltv_time(value: str) -> datetime:
    # e.g. "20260927093251 +0300"
    value = value.strip()
    dt_part, _, tz_part = value.partition(" ")
    dt = datetime.strptime(dt_part, "%Y%m%d%H%M%S")
    if tz_part:
        sign = 1 if tz_part[0] == "+" else -1
        hours = int(tz_part[1:3])
        minutes = int(tz_part[3:5])
        dt = dt.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_and_parse():
    now = datetime.now(timezone.utc)
    window_start = now - LOOKBACK
    window_end = now + LOOKAHEAD

    channels: dict[str, dict] = {}
    sport_ids: set[str] = set()
    programmes: dict[str, list[dict]] = {}

    req = urllib.request.Request(EPG_URL, headers={"User-Agent": "bcu-epg-sport-guide/1.0"})
    print(f"Downloading {EPG_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(req, timeout=180) as resp:
        context = ET.iterparse(resp, events=("start", "end"))
        _, root = next(context)
        for event, elem in context:
            if event != "end":
                continue
            tag = elem.tag
            if tag == "channel":
                cid = (elem.get("id") or "").strip()
                dn = elem.find("display-name")
                name = (dn.text or cid).strip() if dn is not None and dn.text else cid
                icon_el = elem.find("icon")
                icon = icon_el.get("src") if icon_el is not None else None
                channels[cid] = {"id": cid, "name": name, "icon": icon}
                if cid and is_sport_channel(cid, name):
                    sport_ids.add(cid)
                root.clear()
            elif tag == "programme":
                cid = (elem.get("channel") or "").strip()
                if cid in sport_ids:
                    try:
                        start = parse_xmltv_time(elem.get("start") or "")
                        stop = parse_xmltv_time(elem.get("stop") or "")
                    except ValueError:
                        root.clear()
                        continue
                    if stop >= window_start and start <= window_end:
                        title_el = elem.find("title")
                        desc_el = elem.find("desc")
                        cats = [c.text.strip() for c in elem.findall("category") if c.text]
                        start_min = start.hour * 60 + start.minute
                        duration_min = int((stop - start).total_seconds() // 60)
                        # Clip at local midnight so a block never overflows its day's
                        # timeline track; an overnight programme is simply cut short
                        # (it isn't repeated as a continuation on the next day).
                        duration_min = max(1, min(duration_min, 1440 - start_min))
                        programmes.setdefault(cid, []).append(
                            {
                                "start": start.isoformat(),
                                "stop": stop.isoformat(),
                                "day": start.strftime("%Y-%m-%d"),
                                "time": start.strftime("%H:%M"),
                                "time_stop": stop.strftime("%H:%M"),
                                "weekday": WEEKDAYS_CS[start.weekday()],
                                "start_min": start_min,
                                "duration_min": duration_min,
                                "title": (title_el.text or "").strip() if title_el is not None and title_el.text else "",
                                "desc": (desc_el.text or "").strip() if desc_el is not None and desc_el.text else "",
                                "categories": cats,
                            }
                        )
                root.clear()

    print(f"Total channels in feed: {len(channels)}", file=sys.stderr)
    print(f"Sport channels matched: {len(sport_ids)}", file=sys.stderr)
    print(f"Sport channels with programme data: {len(programmes)}", file=sys.stderr)

    result_channels = []
    for cid in sorted(sport_ids, key=lambda c: channels[c]["name"].lower()):
        progs = sorted(programmes.get(cid, []), key=lambda p: p["start"])
        result_channels.append({**channels[cid], "programmes": progs})

    days = sorted({p["day"] for progs in programmes.values() for p in progs})

    return {
        "generated_at": now.isoformat(),
        "source_url": EPG_URL,
        "timezone_note": "Časy v přehledu jsou v časovém pásmu zdroje EPG (Moskva, UTC+3).",
        "days": days,
        "channels": result_channels,
    }


def render_markdown(data: dict) -> str:
    lines = [
        "# BCU Media EPG – kategorie Спорт (Sport)",
        "",
        f"Vygenerováno: {data['generated_at']}",
        f"Zdroj: {data['source_url']}",
        f"{data['timezone_note']}",
        f"Počet sportovních kanálů: {len(data['channels'])}",
        "",
    ]
    for ch in data["channels"]:
        if not ch["programmes"]:
            continue
        lines.append(f"## {ch['name']}")
        lines.append("")
        current_day = None
        for p in ch["programmes"]:
            if p["day"] != current_day:
                current_day = p["day"]
                lines.append(f"### {current_day} ({p['weekday']})")
            lines.append(f"- {p['time']}–{p['time_stop']} **{p['title']}**" + (f" — {p['desc']}" if p["desc"] else ""))
        lines.append("")
    return "\n".join(lines)


def render_llms_txt(data: dict) -> str:
    now = datetime.fromisoformat(data["generated_at"])
    lines = [
        "# BCU Media EPG – Sport TV guide",
        "",
        "> Statický přehled TV programu pro kanály kategorie \"Спорт\" (Sport) "
        f"ze zdroje {data['source_url']}, aktualizovaný jednou denně.",
        "",
        "## Strojově čitelná data",
        "- /data.json — plný strukturovaný export (kanály, pořady, časy v ISO 8601, "
        "start_min/duration_min = minuty od půlnoci v časovém pásmu zdroje)",
        "- /guide.md — stejná data jako čitelný Markdown, seřazeno podle kanálu a dne",
        "- /sitemap.xml — mapa stránek",
        "",
        f"Vygenerováno: {data['generated_at']}",
        f"{data['timezone_note']}",
        f"Počet sportovních kanálů: {len(data['channels'])}",
        "",
        "## Co se právě vysílá (odhad v okamžiku generování)",
        "",
    ]
    now_playing = []
    for ch in data["channels"]:
        for p in ch["programmes"]:
            start = datetime.fromisoformat(p["start"])
            stop = datetime.fromisoformat(p["stop"])
            if start <= now <= stop:
                now_playing.append((ch["name"], p))
                break
    if now_playing:
        for name, p in now_playing:
            lines.append(f"- {name}: {p['time']}–{p['time_stop']} {p['title']}")
    else:
        lines.append("(žádná data k aktuálnímu času, viz /data.json pro plný rozvrh)")
    lines.append("")
    return "\n".join(lines)


SITE_BASE_URL = "https://navrat-dzedaja.github.io/bcu-epg/"


def render_sitemap(data: dict) -> str:
    paths = ["", "data.json", "guide.md", "llms.txt"]
    items = "".join(f"<url><loc>{SITE_BASE_URL}{p}</loc></url>" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>\n'


def render_html(data: dict) -> str:
    e = html.escape

    day_labels = {}
    for day in data["days"]:
        try:
            d = datetime.strptime(day, "%Y-%m-%d")
            day_labels[day] = f"{WEEKDAYS_CS[d.weekday()]} {d.strftime('%d.%m.')}"
        except ValueError:
            day_labels[day] = day

    channel_blocks = []
    ld_channels = []
    for ch in data["channels"]:
        if not ch["programmes"]:
            continue
        ld_channels.append(
            {
                "@type": "Thing",
                "name": ch["name"],
                "image": ch["icon"] or "",
            }
        )
        icon_html = f'<img src="{e(ch["icon"])}" alt="" loading="lazy">' if ch.get("icon") else ""
        groups_html = []
        current_day = None
        items = []
        for p in ch["programmes"]:
            if p["day"] != current_day:
                if items:
                    groups_html.append(
                        f'<div class="day-group" data-day="{e(current_day)}">'
                        f'<h3>{e(day_labels.get(current_day, current_day))}</h3>'
                        f'<ul>{"".join(items)}</ul></div>'
                    )
                current_day = p["day"]
                items = []
            desc_html = f'<span class="desc">{e(p["desc"])}</span>' if p["desc"] else ""
            items.append(
                f'<li data-start="{e(p["start"])}" data-stop="{e(p["stop"])}">'
                f'<time>{e(p["time"])}–{e(p["time_stop"])}</time>'
                f'<strong>{e(p["title"])}</strong>{desc_html}</li>'
            )
        if items:
            groups_html.append(
                f'<div class="day-group" data-day="{e(current_day)}">'
                f'<h3>{e(day_labels.get(current_day, current_day))}</h3>'
                f'<ul>{"".join(items)}</ul></div>'
            )

        channel_blocks.append(
            f'<section class="channel" data-name="{e(ch["name"])}">'
            f'<h2>{icon_html}{e(ch["name"])}</h2>'
            f'<div class="programmes">{"".join(groups_html)}</div>'
            f'</section>'
        )

    if not channel_blocks:
        channels_html = '<p class="empty-state">Ve zdroji se momentálně nenašly žádné pořady pro sportovní kanály.</p>'
    else:
        channels_html = "\n".join(channel_blocks)

    ld_json = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "BCU Media EPG – Sport",
            "itemListElement": ld_channels,
        },
        ensure_ascii=False,
    )

    # Compact payload for the client-side grid renderer (only what it needs).
    grid_data = {
        "generated_at": data["generated_at"],
        "days": data["days"],
        "channels": [
            {
                "name": ch["name"],
                "icon": ch["icon"],
                "programmes": [
                    {
                        "day": p["day"],
                        "time": p["time"],
                        "time_stop": p["time_stop"],
                        "start_min": p["start_min"],
                        "duration_min": p["duration_min"],
                        "title": p["title"],
                        "desc": p["desc"],
                        "start": p["start"],
                        "stop": p["stop"],
                    }
                    for p in ch["programmes"]
                ],
            }
            for ch in data["channels"]
            if ch["programmes"]
        ],
    }
    # Escape "</" so a title/desc containing "</script>" can't break out of the
    # inline <script> tags below.
    ld_json = ld_json.replace("</", "<\\/")
    grid_json = json.dumps(grid_data, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BCU Media EPG – Sport TV program</title>
<meta name="description" content="Denně aktualizovaný TV program pro sportovní kanály (kategorie Спорт) ze zdroje epg.bcumedia.pro.">
<meta name="robots" content="index, follow">
<link rel="alternate" type="application/json" href="data.json" title="Strukturovaná data (JSON)">
<link rel="alternate" type="text/markdown" href="guide.md" title="Textová verze (Markdown)">
<link rel="stylesheet" href="assets/style.css">
<script type="application/ld+json">{ld_json}</script>
</head>
<body>
<header class="site-header">
<h1>BCU Media EPG &ndash; Sport</h1>
<p class="meta">Vygenerováno: {e(data['generated_at'])} &middot; Zdroj: <a href="{e(data['source_url'])}">{e(data['source_url'])}</a></p>
<p class="meta">{e(data['timezone_note'])} &middot; Sportovních kanálů: {len(data['channels'])} &middot; Pro AI/čtečky: <a href="llms.txt">llms.txt</a>, <a href="data.json">data.json</a>, <a href="guide.md">guide.md</a> &middot; <a href="#seznam">textový seznam ↓</a></p>
<div class="controls">
<input id="search" type="search" placeholder="Hledat kanál nebo pořad…" autocomplete="off">
<div class="day-buttons" id="day-buttons"></div>
<button id="jump-now" type="button">Teď</button>
</div>
</header>

<section class="epg-grid-wrap" aria-label="Programová mřížka">
  <div class="epg" id="epg">
    <div class="epg-head">
      <div class="epg-head-corner"></div>
      <div class="epg-head-scroll" id="head-scroll"><div class="epg-ruler" id="ruler"></div></div>
    </div>
    <div class="epg-body">
      <div class="epg-side-scroll" id="side-scroll"><div class="epg-side" id="side"></div></div>
      <div class="epg-main-scroll" id="main-scroll"><div class="epg-main" id="main"></div></div>
    </div>
  </div>
  <p class="epg-noscript-note"><noscript>Mřížka vyžaduje JavaScript. Úplný textový přehled najdeš níže nebo v <a href="guide.md">guide.md</a>.</noscript></p>
</section>

<script type="application/json" id="epg-data">{grid_json}</script>

<main id="seznam">
<h2 class="list-heading">Textový přehled podle kanálů</h2>
{channels_html}
</main>
<footer>
<p>Generováno automaticky jednou denně přes GitHub Actions z {e(data['source_url'])}. Neoficiální přehled, bez záruky přesnosti.</p>
</footer>
<script src="assets/app.js"></script>
</body>
</html>
"""


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    shutil.copytree(WEB_SRC / "assets", OUT_DIR / "assets")

    data = fetch_and_parse()

    (OUT_DIR / "index.html").write_text(render_html(data), encoding="utf-8")
    (OUT_DIR / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "guide.md").write_text(render_markdown(data), encoding="utf-8")
    (OUT_DIR / "llms.txt").write_text(render_llms_txt(data), encoding="utf-8")
    (OUT_DIR / "sitemap.xml").write_text(render_sitemap(data), encoding="utf-8")
    (OUT_DIR / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_BASE_URL}sitemap.xml\n", encoding="utf-8"
    )

    print("Build finished OK.", file=sys.stderr)


if __name__ == "__main__":
    main()
