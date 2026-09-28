# bcu-epg

Statický TV program pro sportovní kanály (kategorie „Спорт“) ze zdroje
[epg.bcumedia.pro/epg.xml](https://epg.bcumedia.pro/epg.xml), automaticky
aktualizovaný jednou denně přes GitHub Actions a publikovaný na GitHub Pages.

Kanál je vyhodnocen jako sportovní, pokud jeho ID/název obsahuje „sport“
(anglicky) nebo „спорт“ (rusky), nebo začíná na „Матч“ (ruská značka
sportovních kanálů) — viz `is_sport_channel()` ve `scripts/build.py`.

## Jak to funguje

- `scripts/build.py` stáhne `epg.xml`, vyfiltruje sportovní kanály a jejich
  pořady v okně přibližně -3 h až +3 dny od okamžiku buildu a vygeneruje do
  `dist/`:
  - `index.html` — plně vyrenderovaná statická stránka (funguje i bez JS)
  - `data.json` — strojově čitelná data
  - `guide.md` — stejný obsah jako čitelný Markdown
  - `llms.txt` — krátký popis pro AI/LLM crawlery s odkazy na strojová data
- `.github/workflows/deploy.yml` spouští build denně (cron) i ručně
  (`workflow_dispatch`) a nasazuje `dist/` na GitHub Pages přes
  `actions/deploy-pages`.

## Jednorázové nastavení

V nastavení repozitáře **Settings → Pages** nastav **Source: GitHub
Actions**. Po prvním doběhnutí workflow poběží stránka na
`https://navrat-dzedaja.github.io/bcu-epg/`.

## Lokální spuštění

```bash
python3 scripts/build.py
# výstup je v ./dist
```

Nejsou potřeba žádné závislosti mimo standardní knihovnu Pythonu 3.
