#!/usr/bin/env python3
"""Game-day reminders for the Flyers and the Stars.

Runs hourly (see .github/workflows/game-day.yml). For each day in the coming
week that either team plays (Mountain time), it writes that day's message to
days/YYYY-MM-DD.txt and keeps it up to date:
opponent, puck drop in Mountain time, anything special about the game, the
season record, one player to watch, and the next game coming up.

An iPhone Shortcut reads that file at 9 AM and texts it to the group chat.
On days with no game there is no file, so nothing is sent.

No third-party packages: standard library only.

Optional environment variables:
  MODE       publish (default) | preview (print only, write nothing)
  FOR_DATE   YYYY-MM-DD, pretend today is this date
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Denver")
OUT_DIR = Path(__file__).resolve().parent / "days"
DAYS_AHEAD = 6  # files are prepared this many days in advance

TEAMS = {
    "PHI": {"name": "Flyers", "badge": "\U0001F7E0"},  # orange circle
    "DAL": {"name": "Stars", "badge": "⭐"},       # star
}

NHL_API = "https://api-web.nhle.com/v1"


# ---------------------------------------------------------------- NHL data

_CACHE = {}


def fetch_json(url, tries=3):
    if url in _CACHE:
        return _CACHE[url]
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "game-day-reminder"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                _CACHE[url] = json.load(resp)
                return _CACHE[url]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last = err
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not load {url}: {last}")


def season_games(abbrev):
    return fetch_json(f"{NHL_API}/club-schedule-season/{abbrev}/now").get("games", [])


def team_record(abbrev):
    """'10-5-2' (wins-losses-overtime losses), or None before the season starts."""
    try:
        rows = fetch_json(f"{NHL_API}/standings/now").get("standings", [])
    except RuntimeError:
        return None
    for row in rows:
        if row.get("teamAbbrev", {}).get("default") == abbrev:
            if not row.get("gamesPlayed"):
                return None
            return f"{row['wins']}-{row['losses']}-{row['otLosses']}"
    return None


def player_to_watch(abbrev):
    """The team's points leader, e.g. 'Jason Robertson (21 pts)'."""
    try:
        skaters = fetch_json(f"{NHL_API}/club-stats/{abbrev}/now").get("skaters", [])
    except RuntimeError:
        return None
    skaters = [s for s in skaters if s.get("points")]
    if not skaters:
        return None
    top = max(skaters, key=lambda s: (s.get("points", 0), s.get("goals", 0)))
    name = f"{top['firstName']['default']} {top['lastName']['default']}"
    return f"{name} ({top['points']} pts)"


# ------------------------------------------------------------ game helpers

def start_local(game):
    utc = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
    return utc.astimezone(LOCAL_TZ)


def is_playable(game):
    """Skip postponed / cancelled games."""
    return game.get("gameScheduleState", "OK") == "OK"


def fmt_time(dt):
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {ampm} {dt.tzname()}"  # MST or MDT


def matchup(game, abbrev):
    """'vs Oilers' at home, 'at Oilers' on the road."""
    if game["homeTeam"]["abbrev"] == abbrev:
        return "vs " + game["awayTeam"]["commonName"]["default"]
    return "at " + game["homeTeam"]["commonName"]["default"]


def special_notes(game):
    notes = []
    event = (game.get("specialEvent") or {}).get("name", {}).get("default")
    if event:
        notes.append(f"{event} at {game['venue']['default']}")
    elif game.get("neutralSite"):
        notes.append(f"Neutral site: {game['venue']['default']}")

    game_type = game.get("gameType")
    if game_type == 1:
        notes.append("Preseason")
    elif game_type == 3:
        series = game.get("seriesStatus") or {}
        label = "Playoffs"
        if series.get("seriesTitle"):
            label += f": {series['seriesTitle']}"
        if series.get("gameNumberOfSeries"):
            label += f", Game {series['gameNumberOfSeries']}"
        notes.append(label)

    teams = {game["homeTeam"]["abbrev"], game["awayTeam"]["abbrev"]}
    if set(TEAMS) <= teams:
        notes.append("Flyers and Stars play each other")

    local = start_local(game)
    if local.hour < 15:
        notes.append("Early start")
    elif local.hour > 20 or (local.hour == 20 and local.minute >= 30):
        notes.append("Late start")
    return notes


def next_game_line(games, abbrev, after):
    upcoming = [g for g in games if is_playable(g) and start_local(g).date() > after]
    if not upcoming:
        return None
    game = min(upcoming, key=start_local)
    local = start_local(game)
    day = f"{local.strftime('%a')} {local.month}/{local.day}"
    return f"Next: {day} {matchup(game, abbrev)}, {fmt_time(local)}"


# ----------------------------------------------------------------- message

def team_block(abbrev, game, games, today, header=None):
    team = TEAMS[abbrev]
    lines = [header or f"{team['badge']} {team['name'].upper()} GAME DAY"]
    lines.append(f"{matchup(game, abbrev)}, {fmt_time(start_local(game))}")
    for note in special_notes(game):
        lines.append(f"Special: {note}")
    record = team_record(abbrev)
    if record:
        lines.append(f"Record: {record}")
    watch = player_to_watch(abbrev)
    if watch:
        lines.append(f"Watch: {watch}")
    upcoming = next_game_line(games, abbrev, today)
    if upcoming:
        lines.append(upcoming)
    return "\n".join(lines)


def head_to_head_block(game, schedules, today):
    """One block for the days the Flyers and Stars play each other."""
    badges = "".join(t["badge"] for t in TEAMS.values())
    away = game["awayTeam"]["commonName"]["default"]
    home = game["homeTeam"]["commonName"]["default"]
    lines = [f"{badges} FLYERS + STARS GAME DAY"]
    lines.append(f"{away} at {home}, {fmt_time(start_local(game))}")
    for note in special_notes(game):
        if "play each other" not in note:  # the header already says so
            lines.append(f"Special: {note}")
    for abbrev, team in TEAMS.items():
        bits = [b for b in (team_record(abbrev), player_to_watch(abbrev)) if b]
        if bits:
            lines.append(f"{team['name']}: " + ", watch ".join(bits))
    for abbrev, team in TEAMS.items():
        upcoming = next_game_line(schedules[abbrev], abbrev, today)
        if upcoming:
            lines.append(upcoming.replace("Next:", f"{team['name']} next:"))
    return "\n".join(lines)


def build_message(today):
    """The text for `today`, or None if neither team plays."""
    schedules = {abbrev: season_games(abbrev) for abbrev in TEAMS}
    todays = {}
    for abbrev, games in schedules.items():
        for game in games:
            if is_playable(game) and start_local(game).date() == today:
                todays[abbrev] = game
                break
    if not todays:
        return None

    ids = {game["id"] for game in todays.values()}
    if len(todays) == len(TEAMS) and len(ids) == 1:
        blocks = [head_to_head_block(next(iter(todays.values())), schedules, today)]
    else:
        blocks = [team_block(a, g, schedules[a], today) for a, g in todays.items()]
    return "\n\n".join(blocks)


# ----------------------------------------------------------------- publish

def publish(today):
    """Write a file for each game day from today through the look-ahead
    window, and remove files that are past or no longer have a game."""
    OUT_DIR.mkdir(exist_ok=True)
    window = [today + timedelta(days=n) for n in range(DAYS_AHEAD + 1)]
    wanted = {}
    for day in window:
        message = build_message(day)
        if message:
            wanted[f"{day.isoformat()}.txt"] = message + "\n"
    last = f"{window[-1].isoformat()}.txt"
    for old in OUT_DIR.glob("*.txt"):
        if old.name <= last and old.name not in wanted:
            old.unlink()
    for name, text in wanted.items():
        (OUT_DIR / name).write_text(text, encoding="utf-8")
    return sorted(wanted)


def main():
    mode = (os.environ.get("MODE") or "publish").strip().lower()
    override = (os.environ.get("FOR_DATE") or "").strip()
    today = date.fromisoformat(override) if override else datetime.now(timezone.utc).astimezone(LOCAL_TZ).date()

    if mode == "preview":
        message = build_message(today)
        print(message if message else f"No Flyers or Stars game on {today}.")
        print("-" * 40)
        print("Preview only, nothing written.")
        return 0

    written = publish(today)
    print("Game days in the next week: " + (", ".join(n[:-4] for n in written) or "none"))
    todays = OUT_DIR / f"{today.isoformat()}.txt"
    if todays.exists():
        print("-" * 40)
        print(todays.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
