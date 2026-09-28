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
                        programmes.setdefault(cid, []).append(
                            {
                                "start": start.isoformat(),
                                "stop": stop.isoformat(),
                                "day": start.strftime("%Y-%m-%d"),
                                "time": start.strftime("%H:%M"),
                                "time_stop": stop.strftime("%H:%M"),
                                "weekday": WEEKDAYS_CS[start.weekday()],
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
    return (
        "# BCU Media EPG – Sport TV guide\n\n"
        "> Statický přehled TV programu pro kanály kategorie \"Спорт\" (Sport) "
        f"ze zdroje {data['source_url']}, aktualizovaný jednou denně.\n\n"
        "Strojově čitelná data:\n"
        "- /data.json — plný strukturovaný export (kanály, pořady, časy v ISO 8601)\n"
        "- /guide.md — stejná data jako čitelný Markdown\n\n"
        f"Vygenerováno: {data['generated_at']}\n"
        f"{data['timezone_note']}\n"
    )


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
<p class="meta">{e(data['timezone_note'])} &middot; Sportovních kanálů: {len(data['channels'])} &middot; Alternativní formáty: <a href="data.json">data.json</a>, <a href="guide.md">guide.md</a></p>
<div class="controls">
<input id="search" type="search" placeholder="Hledat kanál…" autocomplete="off">
<div class="day-buttons" id="day-buttons"></div>
</div>
</header>
<main>
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
    (OUT_DIR / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")

    print("Build finished OK.", file=sys.stderr)


if __name__ == "__main__":
    main()
