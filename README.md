# weatherstation-data

Small JSON files with public sports data (F1, NHL, FIS alpine skiing) for a home-made ESP32 e-ink
display. A GitHub Actions workflow runs `scripts/aggregate.py` twice a day and commits `data/*.json`.

| File | Source | Content |
|---|---|---|
| `data/f1.json` | [Jolpica F1 API](https://api.jolpi.ca/ergast/f1/) | next GP sessions, last result, driver/constructor standings, season calendar |
| `data/nhl.json` | NHL web API (`api-web.nhle.com`) | standings, followed team's last/next games, recent scores |
| `data/news.json` | RSS: Variety, Deadline, The Guardian, Book Riot, NME | film/TV, book and music headlines for the in4md app (every 3 h; optional Serbian titles via DeepL, secret `DEEPL_KEY`) |
| `data/ski.json` | [FIS](https://www.fis-ski.com) (iCal feed + public pages) | World Cup race calendar, start times, last results, cup standings |

All times are UTC (`YYYY-MM-DDTHH:MMZ`). Personal, non-commercial use; data belongs to the respective sources.
