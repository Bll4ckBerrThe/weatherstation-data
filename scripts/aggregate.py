"""
aggregate.py — condenses public sports data into small JSON files for an ESP32 e-ink display.

Sources (all free, no API key):
  F1   Jolpica F1 API (Ergast successor)       https://api.jolpi.ca/ergast/f1/
  NHL  NHL web API (used by nhl.com)           https://api-web.nhle.com/v1/
  SKI  FIS website (no API exists)             https://www.fis-ski.com/DB/alpine-skiing/

Output: data/f1.json, data/nhl.json, data/ski.json — a few KB each. All times are UTC ISO-8601
("2026-10-11T12:00Z"); the display converts to local time. Short keys keep the files small,
the device parses them with a fixed schema (see the README).

Standard library only, so it runs unchanged on GitHub Actions.  Usage:  python scripts/aggregate.py [f1|nhl|ski]...
"""
import json, os, sys, time, urllib.request, urllib.error, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data")
UA = {"User-Agent": "weatherstation-data/1.0 (personal e-ink display; daily)"}
NHL_TEAM = "MTL"   # followed team


def get_json(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404 or i == tries - 1:      # 404 = "doesn't exist", retrying won't help
                raise
            print(f"  retry {url}: {e}")
            time.sleep(3 * (i + 1))
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  retry {url}: {e}")
            time.sleep(3 * (i + 1))


def utc(date, tm=None):
    """'2026-10-11', '12:00:00Z' -> '2026-10-11T12:00Z' (date only if no time)."""
    if not date:
        return None
    if not tm:
        return date
    return f"{date}T{tm[:5]}Z"


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def write(name, obj):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  wrote {name}: {os.path.getsize(path)} bytes")


# ── F1 ──────────────────────────────────────────────────────────────────────────
F1 = "https://api.jolpi.ca/ergast/f1"
SESSION_KEYS = [("FirstPractice", "FP1"), ("SecondPractice", "FP2"), ("ThirdPractice", "FP3"),
                ("SprintQualifying", "SQ"), ("Sprint", "SPR"), ("Qualifying", "Q")]


def short_gp(name):
    return name.replace(" Grand Prix", "").replace("Grand Prix", "GP").strip()


def f1():
    races = get_json(f"{F1}/current/races/?format=json&limit=100")["MRData"]["RaceTable"]
    season = int(races["season"])
    races = races["Races"]
    winners = {}
    try:
        res = get_json(f"{F1}/current/results/1/?format=json&limit=100")["MRData"]["RaceTable"]["Races"]
        winners = {int(r["round"]): r["Results"][0]["Driver"].get("code") or r["Results"][0]["Driver"]["familyName"][:3].upper()
                   for r in res if r.get("Results")}
    except Exception as e:
        print("  F1 winners failed:", e)

    # "Next" race = the first one whose start is less than 3 h ago (a race is over by then), so
    # on race evening the display already shows the result, not this race's schedule.
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%MZ")
    cal = []
    nxt = None
    for r in races:
        rnd = int(r["round"])
        sprint = "Sprint" in r
        start = utc(r["date"], r.get("time") or "23:59:00Z")
        cal.append({"r": rnd, "n": short_gp(r["raceName"]), "c": r["Circuit"]["Location"]["country"],
                    "d": utc(r["date"], r.get("time")), "s": 1 if sprint else 0, "w": winners.get(rnd)})
        if nxt is None and start > cutoff:
            sess = [[lab, utc(r[k]["date"], r[k].get("time"))] for k, lab in SESSION_KEYS if k in r]
            sess.append(["R", utc(r["date"], r.get("time"))])
            sess.sort(key=lambda s: s[1] or "")
            nxt = {"r": rnd, "n": short_gp(r["raceName"]), "cir": r["Circuit"]["circuitName"],
                   "loc": r["Circuit"]["Location"]["locality"], "c": r["Circuit"]["Location"]["country"],
                   "sess": sess}
    # Qualifying grid of the next race, once it exists
    if nxt:
        try:
            q = get_json(f"{F1}/current/{nxt['r']}/qualifying/?format=json")["MRData"]["RaceTable"]["Races"]
            if q:
                nxt["grid"] = [[int(x["position"]), x["Driver"]["code"], x["Constructor"]["constructorId"],
                                x.get("Q3") or x.get("Q2") or x.get("Q1") or ""] for x in q[0]["QualifyingResults"][:10]]
        except Exception as e:
            print("  F1 qualifying failed:", e)
        # Sprint result of the next race's weekend (sprint weekends only), once it exists
        if any(k == "SPR" for k, _ in nxt["sess"]):
            try:
                sp = get_json(f"{F1}/current/{nxt['r']}/sprint/?format=json")["MRData"]["RaceTable"]["Races"]
                if sp:
                    nxt["sprint"] = [[int(x["position"]), x["Driver"]["code"], x["Constructor"]["constructorId"],
                                      (x.get("Time") or {}).get("time") or x["status"], float(x["points"])]
                                     for x in sp[0]["SprintResults"][:8]]
            except Exception as e:
                print("  F1 sprint failed:", e)

    last = None
    try:
        lr = get_json(f"{F1}/current/last/results/?format=json")["MRData"]["RaceTable"]["Races"]
        if lr:
            lr = lr[0]
            last = {"r": int(lr["round"]), "n": short_gp(lr["raceName"]), "d": utc(lr["date"], lr.get("time")),
                    "top": [[int(x["position"]), x["Driver"]["code"], x["Driver"]["familyName"],
                             x["Constructor"]["constructorId"],
                             (x.get("Time") or {}).get("time") or x["status"], float(x["points"])]
                            for x in lr["Results"][:10]]}
    except Exception as e:
        print("  F1 last result failed:", e)

    drivers, teams, done = [], [], 0
    ds = get_json(f"{F1}/current/driverstandings/?format=json&limit=40")["MRData"]["StandingsTable"]["StandingsLists"]
    if ds:
        done = int(ds[0]["round"])
        drivers = [[int(x.get("position") or 0), x["Driver"].get("code") or x["Driver"]["familyName"][:3].upper(),
                    x["Driver"]["familyName"], x["Constructors"][0]["constructorId"] if x["Constructors"] else "",
                    float(x["points"]), int(x["wins"])] for x in ds[0]["DriverStandings"]]
    cs = get_json(f"{F1}/current/constructorstandings/?format=json")["MRData"]["StandingsTable"]["StandingsLists"]
    if cs:
        teams = [[int(x.get("position") or 0), x["Constructor"]["constructorId"], x["Constructor"]["name"],
                  float(x["points"]), int(x["wins"])] for x in cs[0]["ConstructorStandings"]]

    write("f1.json", {"upd": now_utc(), "season": season, "done": done, "rounds": len(races),
                      "next": nxt, "last": last, "drivers": drivers, "teams": teams, "cal": cal})


# ── NHL ─────────────────────────────────────────────────────────────────────────
NHL = "https://api-web.nhle.com/v1"


def nhl_game(g, team=None):
    """Compact game: [id, startUTC, away, home, awayScore, homeScore, state, lastPeriodType]."""
    a, h = g["awayTeam"], g["homeTeam"]
    return [g["id"], g["startTimeUTC"][:16] + "Z", a["abbrev"], h["abbrev"], a.get("score"), h.get("score"),
            g.get("gameState"), (g.get("gameOutcome") or {}).get("lastPeriodType")]


def nhl():
    st = get_json(f"{NHL}/standings/now")["standings"]
    standings = [[t["teamAbbrev"]["default"], t["conferenceAbbrev"], t["divisionAbbrev"],
                  t["gamesPlayed"], t["wins"], t["losses"], t["otLosses"], t["points"],
                  t["leagueSequence"], t["conferenceSequence"], t["divisionSequence"],
                  t.get("wildcardSequence", 0), t.get("goalFor", 0), t.get("goalAgainst", 0),
                  (t.get("streakCode") or "") + str(t.get("streakCount") or "")] for t in st]
    standings.sort(key=lambda r: r[8])

    sched = get_json(f"{NHL}/club-schedule-season/{NHL_TEAM}/now")
    games = [g for g in sched.get("games", []) if g.get("gameType") in (2, 3)]   # regular season + playoffs
    played = [g for g in games if g.get("gameState") in ("OFF", "FINAL")]
    future = [g for g in games if g.get("gameState") in ("FUT", "PRE", "LIVE", "CRIT")]
    team = {"abbr": NHL_TEAM, "last": [nhl_game(g) for g in played[-5:]], "next": [nhl_game(g) for g in future[:8]]}

    # Scores seen from Europe: "last" = games of North American date D-1 (finished overnight here),
    # "tonight" = games of NA date D (they start ~01:00-04:00 our time). D = today's UTC date; the
    # workflow runs 04:30 and 18:00 UTC, both well after the previous NA night has ended.
    scores = {}
    today = datetime.datetime.now(datetime.timezone.utc).date()
    for key, day in (("last", today - datetime.timedelta(days=1)), ("tonight", today)):
        try:
            sc = get_json(f"{NHL}/score/{day.isoformat()}")
            scores[key] = {"date": day.isoformat(), "games": [nhl_game(g) for g in sc.get("games", [])]}
        except Exception as e:
            print(f"  NHL scores {key} failed:", e)

    # Followed team's leaders: top 5 skaters by points, plus goalies with games played
    leaders = {}
    try:
        cs = get_json(f"{NHL}/club-stats/{NHL_TEAM}/now")
        sk = sorted(cs.get("skaters", []), key=lambda s: (-s.get("points", 0), -s.get("goals", 0)))[:5]
        leaders["skaters"] = [[s["firstName"]["default"][:1] + ". " + s["lastName"]["default"], s.get("positionCode", ""),
                               s.get("gamesPlayed", 0), s.get("goals", 0), s.get("assists", 0), s.get("points", 0)] for s in sk]
        gl = sorted(cs.get("goalies", []), key=lambda s: -s.get("gamesPlayed", 0))[:2]
        leaders["goalies"] = [[s["firstName"]["default"][:1] + ". " + s["lastName"]["default"], s.get("gamesPlayed", 0),
                               round(s.get("savePercentage") or 0, 3), round(s.get("goalsAgainstAverage") or 0, 2)] for s in gl]
    except Exception as e:
        print("  NHL club stats failed:", e)
    team["leaders"] = leaders

    # Phase: "regular" (division table) / "playoffs" (bracket, live) / "final" (off-season: last
    # season's finished bracket until the new regular season has games). The carousel endpoint
    # lists every round with series letter, seeds and wins.
    season = sched.get("currentSeason")
    phase, bracket = "regular", None
    games_played = sum(r[3] for r in standings)
    cand = [(season, "playoffs")]
    if not games_played:
        cand.append((season - 10001, "final"))              # 20262027 -> 20252026
    for sid, ph in cand:
        try:
            car = get_json(f"{NHL}/playoff-series/carousel/{sid}/")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue                                    # no playoffs for that season (yet)
            print("  NHL playoffs check failed (treated as regular season):", e)
            break
        except Exception as e:
            print("  NHL playoffs check failed (treated as regular season):", e)
            break
        rounds = car.get("rounds") or []
        if rounds:
            phase = ph
            bracket = {"season": sid, "round": car.get("currentRound"),
                       "series": [[s.get("seriesLetter"), r.get("roundNumber"),
                                   s["topSeed"]["abbrev"], s["topSeed"].get("wins", 0),
                                   s["bottomSeed"]["abbrev"], s["bottomSeed"].get("wins", 0)]
                                  for r in rounds for s in r.get("series", [])]}
            break

    write("nhl.json", {"upd": now_utc(), "season": season, "phase": phase,
                       "standings": standings, "team": team, "scores": scores, "bracket": bracket})


# ── NHL team pages: one small file per team (data/nhl/<ABBR>.json) ──────────────
# The display has a team selector, so every team gets: season record + standings place, last
# 10 / next 8 games, every goal of the last game, top scorers + goalies, and franchise history
# (first season, all-time records, Stanley Cups, last seasons with playoff result).
RECORDS = "https://records.nhl.com/site/api"


def nhl_team_file(abbr, row, franchise):
    sched = get_json(f"{NHL}/club-schedule-season/{abbr}/now")
    games = [g for g in sched.get("games", []) if g.get("gameType") in (2, 3)]
    played = [g for g in games if g.get("gameState") in ("OFF", "FINAL")]
    future = [g for g in games if g.get("gameState") in ("FUT", "PRE", "LIVE", "CRIT")]
    out = {"upd": now_utc(), "abbr": abbr, "row": row,
           "last": [nhl_game(g) for g in played[-10:]], "next": [nhl_game(g) for g in future[:8]]}

    # Every goal of the most recent finished game
    if played:
        try:
            L = get_json(f"{NHL}/gamecenter/{played[-1]['id']}/landing")
            goals = []
            for p in L.get("summary", {}).get("scoring", []):
                pd = p["periodDescriptor"]
                per = "OT" if pd.get("periodType") == "OT" else ("SO" if pd.get("periodType") == "SO" else str(pd["number"]))
                for g in p.get("goals", []):
                    goals.append([per, g.get("timeInPeriod", ""), (g.get("teamAbbrev") or {}).get("default", ""),
                                  ((g.get("firstName") or {}).get("default", "")[:1] + ". " + (g.get("lastName") or {}).get("default", "")).strip(". "),
                                  [(a.get("lastName") or {}).get("default", "") for a in g.get("assists", [])],
                                  g.get("strength", ""), g.get("awayScore"), g.get("homeScore")])
            out["lastGame"] = {"id": L["id"], "away": L["awayTeam"]["abbrev"], "home": L["homeTeam"]["abbrev"],
                               "as": L["awayTeam"].get("score"), "hs": L["homeTeam"].get("score"),
                               "asog": L["awayTeam"].get("sog"), "hsog": L["homeTeam"].get("sog"),
                               "start": L["startTimeUTC"][:16] + "Z", "goals": goals}
        except Exception as e:
            print(f"  {abbr} last game failed:", e)

    try:
        cs = get_json(f"{NHL}/club-stats/{abbr}/now")
        sk = sorted(cs.get("skaters", []), key=lambda s: (-s.get("points", 0), -s.get("goals", 0)))[:5]
        out["skaters"] = [[s["firstName"]["default"][:1] + ". " + s["lastName"]["default"], s.get("positionCode", ""),
                           s.get("gamesPlayed", 0), s.get("goals", 0), s.get("assists", 0), s.get("points", 0)] for s in sk]
        gl = sorted(cs.get("goalies", []), key=lambda s: -s.get("gamesPlayed", 0))[:2]
        out["goalies"] = [[s["firstName"]["default"][:1] + ". " + s["lastName"]["default"], s.get("gamesPlayed", 0),
                           round(s.get("savePercentage") or 0, 3), round(s.get("goalsAgainstAverage") or 0, 2)] for s in gl]
    except Exception as e:
        print(f"  {abbr} club stats failed:", e)

    if franchise:
        try:
            hist = {"name": franchise["fullName"], "first": franchise["firstSeasonId"]}
            tot = get_json(f"{RECORDS}/franchise-team-totals?cayenneExp=teamId={franchise['mostRecentTeamId']}")["data"]
            for t in tot:
                key = "reg" if t["gameTypeId"] == 2 else "po"
                hist[key] = [t["gamesPlayed"], t["wins"], t["losses"], (t.get("ties") or 0) + (t.get("otLosses") or 0)]
            res = get_json(f"{RECORDS}/franchise-season-results?cayenneExp=franchiseId={franchise['id']}")["data"]
            cups = sorted(r["seasonId"] for r in res if r.get("gameTypeId") == 3 and r.get("decision") == "W")
            hist["cups"], hist["lastCup"] = len(cups), (cups[-1] if cups else None)
            po = {r["seasonId"]: r for r in res if r.get("gameTypeId") == 3}
            seasons = []
            for r in sorted((r for r in res if r.get("gameTypeId") == 2), key=lambda r: r["seasonId"])[-6:]:
                p = po.get(r["seasonId"])
                # playoff result: None = missed, else [round reached, won-that-round?, series title]
                seasons.append([r["seasonId"], r.get("wins"), r.get("losses"),
                                (r.get("overtimeLosses") or 0) + (r.get("ties") or 0), r.get("points"),
                                r.get("divisionSequence"),
                                [p.get("playoffRound"), p.get("decision"), p.get("seriesTitle")] if p else None])
            hist["seasons"] = seasons
            out["hist"] = hist
        except Exception as e:
            print(f"  {abbr} history failed:", e)

    os.makedirs(os.path.join(OUT, "nhl"), exist_ok=True)
    write(os.path.join("nhl", f"{abbr}.json"), out)


def nhl_teams():
    st = get_json(f"{NHL}/standings/now")["standings"]
    rows = {t["teamAbbrev"]["default"]: [t["teamName"]["default"], t["conferenceAbbrev"], t["divisionAbbrev"],
                                         t["gamesPlayed"], t["wins"], t["losses"], t["otLosses"], t["points"],
                                         t["leagueSequence"], t["conferenceSequence"], t["divisionSequence"],
                                         t.get("goalFor", 0), t.get("goalAgainst", 0),
                                         (t.get("streakCode") or "") + str(t.get("streakCount") or "")] for t in st}
    fr = {f["teamAbbrev"]: f for f in get_json(f"{RECORDS}/franchise")["data"] if f.get("lastSeasonId") is None}
    failed = []
    for abbr in sorted(rows):
        try:
            nhl_team_file(abbr, rows[abbr], fr.get(abbr))
        except Exception as e:
            failed.append(abbr)
            print(f"  team {abbr} FAILED:", e)
        time.sleep(0.3)                      # be gentle: ~5 requests per team
    if len(failed) == len(rows):
        raise RuntimeError("all team files failed")


# ── Alpine skiing (FIS World Cup) ───────────────────────────────────────────────
# FIS has no public API. Sources: the season iCal feed (all races, current season only), the
# per-race results/start-list page (results; "1st Run: 10:00 CET" start times) and the cup
# standings page (overall + every discipline in one table). HTML is parsed with regexes —
# if FIS changes its markup the ski part fails on its own and the old ski.json is kept.
import re, html as _html

FIS = "https://www.fis-ski.com/DB"
DISC = {"Downhill": "DH", "Super G": "SG", "Giant Slalom": "GS", "Slalom": "SL",
        "Alpine combined": "AC", "Alpine Combined": "AC", "Team Combined": "TC", "Parallel": "PAR",
        "Parallel Giant Slalom": "PGS", "Parallel Slalom": "PSL", "Team Parallel": "TP"}


# FIS writes venue names in ASCII ("Soelden", "Kitzbuehel") and sometimes long ("Val Gardena-
# Groeden Südtirol"). Proper spelling for the display; unknown names pass through unchanged.
# Only Latin-1 + Serbian letters render on the device (č ć š ž đ, ä ö ü é è å ...).
PLACES = {
    "Soelden": "Sölden", "Kitzbuehel": "Kitzbühel", "Are": "Åre", "Val d'Isere": "Val d'Isère",
    "Jasna": "Jasná", "Copper Mountain, CO": "Copper Mountain", "Narvik (TBC)": "Narvik",
    "Val Gardena-Groeden Südtirol": "Val Gardena", "Dachstein West / Gosau": "Gosau",
    "Garmisch-Partenkirchen": "Garmisch", "Cortina d'Ampezzo": "Cortina", "Madonna di Campiglio": "Campiglio",
    "Spindleruv Mlyn": "Špindlerův Mlýn", "Zauchensee": "Zauchensee", "Meribel": "Méribel",
    "Crans Montana": "Crans-Montana", "Lake Louise": "Lake Louise", "Semmering": "Semmering",
}


def get_text(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, "User-Agent": "Mozilla/5.0 (" + UA["User-Agent"] + ")"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  retry {url}: {e}")
            time.sleep(5 * (i + 1))


def _txt(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _name(raw):
    """'ODERMATT Marco' -> 'Odermatt M.' ; 'PINHEIRO BRAATHEN Lucas' -> 'Pinheiro Braathen L.'"""
    parts = raw.split()
    sur = [p for p in parts if p.isupper() and len(p) > 1]
    first = [p for p in parts if not (p.isupper() and len(p) > 1)]
    def cap(w):
        w = w.capitalize() if w.isupper() else w
        if w.startswith("Mc") and len(w) > 2:
            w = "Mc" + w[2].upper() + w[3:]                       # McGrath
        return "'".join(x[:1].upper() + x[1:] for x in w.split("'"))   # O'Brien
    s = " ".join(cap(w) for w in (sur or parts[:1]))
    s = "-".join(x[:1].upper() + x[1:] for x in s.split("-"))
    return f"{s} {first[0][0]}." if first else s


def fis_season(today):
    return today.year + 1 if today.month >= 7 else today.year   # 2026/27 season = code 2027


def ski_races(season):
    ics = get_text(f"{FIS}/services/public/icalendar-feed-fis-events.html?seasoncode={season}&sectorcode=AL&categorycode=WC")
    ics = ics.replace("\r\n ", "").replace("\n ", "")
    races = []
    for ev in ics.split("BEGIN:VEVENT")[1:]:
        g = lambda k: (re.search(rf"^{k}[^:\n]*:(.*)$", ev, re.M) or [None, ""])[1].strip()
        date, summ, desc = g("DTSTART")[:8], g("SUMMARY"), g("DESCRIPTION")
        m = re.match(r"(.+?) \(([A-Z]{3})\) - .*?World Cup (.+)$", summ)
        rid = re.search(r"raceid=(\d+)", desc)
        if not (m and rid and len(date) == 8):
            continue
        gender = "W" if "Gender: Women" in desc else ("M" if "Gender: Men" in desc else "X")
        disc = m.group(3).strip()
        place = m.group(1).strip()
        races.append({"d": f"{date[:4]}-{date[4:6]}-{date[6:]}", "p": PLACES.get(place, place), "c": m.group(2),
                      "disc": DISC.get(disc, disc[:3].upper()), "g": gender, "id": int(rid.group(1))})
    races.sort(key=lambda r: (r["d"], r["g"]))
    return races


def ski_race_page(rid):
    """Start times and (if available) the top 10 of one race."""
    h = get_text(f"{FIS}/general/results.html?sectorcode=AL&raceid={rid}")
    # Start times: the visible "1st Run: 11:00" is the VENUE's local time (the "CET" next to it
    # is a stale label — Copper Mountain 11:00 was 19:00 CET). Each run carries the exact
    # moment with offset in data-iso-date ("2025-11-27T11:00:00-07:00"); store it as UTC
    # like F1/NHL, the display converts to local time.
    runs = []
    for num, iso in re.findall(r'schedule-list__event">\s*(\d)(?:st|nd|rd|th) Run:.*?data-iso-date="([^"]+)"', h, re.S):
        try:
            t = datetime.datetime.fromisoformat(iso).astimezone(datetime.timezone.utc)
            runs.append((num, t.strftime("%Y-%m-%dT%H:%MZ")))
        except ValueError:
            pass
    top = []
    for row in re.findall(r'<a class="table-row"[^>]*>(.*?)</a>', h, re.S):
        t = _txt(row)
        # "rank bib fiscode NAME First --> --> year NAT  <times...>"
        #   one run:  "1:07.78 +0.08 1.41 1.41 80"      winner: "1:07.70 1:07.70 0.00 0.00 100"
        #   two runs: "1:14.07 1:17.86 2:31.93 +0.95 …" winner: "1:13.27 1:17.71 2:30.98 2:30.98 …"
        m = re.match(r"(\d+) \d+ \d+ (.+?) (?:--> )*(\d{4}) ([A-Z]{3}) (.*)$", t)
        if not m or len(top) >= 10:
            continue
        rank, name, nat = int(m.group(1)), m.group(2).replace("-->", "").strip(), m.group(4)
        toks = m.group(5).split()
        total, gap = "", ""
        for i, tk in enumerate(toks):
            if tk.startswith("+") and i > 0:          # total is the value right before the gap
                total, gap = toks[i - 1], tk
                break
            if i > 0 and tk == toks[i - 1]:           # winner: total printed twice
                total = tk
                break
        top.append([rank, _name(name), nat, total or (toks[0] if toks else ""), gap])
    return {"runs": [r[1] for r in sorted(runs)], "top": top}


def ski_standings(season, gender):
    h = get_text(f"{FIS}/alpine-skiing/cup-standings.html?sectorcode=AL&seasoncode={season}&cupcode=WC&disciplinecode=ALL&gendercode={gender}")
    rows = []
    for row in re.findall(r'<a class="table-row[^"]*"[^>]*>(.*?)</a>', h, re.S):
        t = _txt(row)
        m = re.match(r"(.+?) ([A-Z]{3}) Overall ALL (\d+|---) ?([\d']*)", t)
        if not m or m.group(3) == "---":
            continue
        rec = {"n": _name(m.group(1)), "c": m.group(2), "r": int(m.group(3)), "pts": int(m.group(4).replace("'", "") or 0)}
        for code in ("DH", "SG", "GS", "SL", "AC"):
            dm = re.search(rf"\b{code} (\d+) ([\d']+)", t)
            if dm:
                rec[code] = [int(dm.group(1)), int(dm.group(2).replace("'", ""))]
        rows.append(rec)
    rows.sort(key=lambda r: r["r"])
    overall = [[r["r"], r["n"], r["c"], r["pts"]] for r in rows[:10]]
    disc = {}
    for code in ("DH", "SG", "GS", "SL"):
        ranked = sorted((r for r in rows if code in r), key=lambda r: r[code][0])[:3]
        if ranked:
            disc[code] = [[r[code][0], r["n"], r["c"], r[code][1]] for r in ranked]
    return {"overall": overall, "disc": disc}


def ski():
    today = datetime.date.today()
    season = fis_season(today)
    races = ski_races(season)
    iso = today.isoformat()
    done = [r for r in races if r["d"] < iso]
    upcoming = [r for r in races if r["d"] >= iso]

    # Start times for the next races (published about a week ahead)
    for r in upcoming[:4]:
        try:
            r["runs"] = ski_race_page(r["id"])["runs"]
        except Exception as e:
            print(f"  start time {r['id']} failed: {e}")

    # Latest completed race per gender: top 10
    last = {}
    for g in ("M", "W"):
        mine = [r for r in done if r["g"] == g]
        if mine:
            r = mine[-1]
            try:
                page = ski_race_page(r["id"])
                if page["top"]:
                    last[g] = {"d": r["d"], "p": r["p"], "disc": r["disc"], "top": page["top"]}
            except Exception as e:
                print(f"  result {r['id']} failed: {e}")

    # Standings: current season once it has started, otherwise last season's final table
    st_season = season if done else season - 1
    stand = {"season": st_season, "final": not done}
    for g in ("M", "W"):
        try:
            stand[g] = ski_standings(st_season, g)
        except Exception as e:
            print(f"  standings {g} failed: {e}")

    cal = [[r["d"], r["p"], r["c"], r["disc"], r["g"], r["id"]] + ([r["runs"]] if r.get("runs") else []) for r in races]
    write("ski.json", {"upd": now_utc(), "season": f"{season - 1}/{str(season)[2:]}",
                       "races": cal, "last": last, "stand": stand})


if __name__ == "__main__":
    which = sys.argv[1:] or ["f1", "nhl", "nhl_teams", "ski"]
    failed = []
    for name in which:
        print(f"[{name}]")
        try:
            globals()[name]()
        except Exception as e:
            failed.append(name)
            print(f"  {name} FAILED: {e}")   # keep the previous file; other sports still update
    sys.exit(1 if failed and len(failed) == len(which) else 0)
