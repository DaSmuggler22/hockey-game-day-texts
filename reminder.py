#!/usr/bin/env python3
"""Game-day reminders for the Flyers and the Stars.

Runs hourly (see .github/workflows/game-day.yml). For each day in the coming
week that either team plays (Mountain time), it writes that day's message
into schedule.json, keyed by date: opponent, puck drop in Mountain time,
anything special about the game, the season record, one player to watch, and
the next game coming up.

An iPhone Shortcut reads schedule.json at 9 AM and texts today's entry to the
group chat. Days with no game have no entry, so nothing is sent.

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
OUT_FILE = Path(__file__).resolve().parent / "schedule.json"
WATCH_POOL = 5  # the player to watch rotates through this many top scorers
DAYS_AHEAD = 6  # messages are prepared this many days in advance

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


def player_to_watch(abbrev, turn=0):
    """One of the team's top scorers, e.g. 'Jason Robertson (21 pts)'.
    `turn` picks whose turn it is, so the name changes from game to game."""
    try:
        skaters = fetch_json(f"{NHL_API}/club-stats/{abbrev}/now").get("skaters", [])
    except RuntimeError:
        return None
    skaters = [s for s in skaters if s.get("points")]
    if not skaters:
        return None
    skaters.sort(key=lambda s: (-s.get("points", 0), -s.get("goals", 0), s.get("playerId", 0)))
    top = skaters[:WATCH_POOL]
    pick = top[turn % len(top)]
    name = f"{pick['firstName']['default']} {pick['lastName']['default']}"
    return f"{name} ({pick['points']} pts)"


def game_number(games, game):
    """Where this game falls in the team's season, used to rotate the player."""
    ordered = sorted((g for g in games if is_playable(g)), key=start_local)
    return next((i for i, g in enumerate(ordered) if g["id"] == game["id"]), 0)


# ------------------------------------------------------------ game helpers

def start_local(game):
    utc = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
    return utc.astimezone(LOCAL_TZ)


def is_playable(game):
    """Skip postponed / cancelled games."""
    return game.get("gameScheduleState", "OK") == "OK"


def fmt_time(dt):
    """Mountain time, no zone label: '5pm' or '5:30pm'."""
    hour = dt.hour % 12 or 12
    ampm = "am" if dt.hour < 12 else "pm"
    return f"{hour}{ampm}" if dt.minute == 0 else f"{hour}:{dt.minute:02d}{ampm}"


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
    # Within a week the weekday is enough; further out, give the date.
    if (local.date() - after).days <= 6:
        day = local.strftime("%a")
    else:
        day = f"{local.month}/{local.day}"
    return f"Next: {day} {matchup(game, abbrev)} {fmt_time(local)}"


# ----------------------------------------------------------------- message

def team_block(abbrev, game, games, today, header=None):
    team = TEAMS[abbrev]
    lines = [header or f"{team['badge']} {team['name']} {matchup(game, abbrev)} {fmt_time(start_local(game))}"]
    for note in special_notes(game):
        lines.append(f"Special: {note}")
    record = team_record(abbrev)
    if record:
        lines.append(f"Record: {record}")
    watch = player_to_watch(abbrev, game_number(games, game))
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
    lines = [f"{badges} {away} at {home} {fmt_time(start_local(game))}"]
    for note in special_notes(game):
        if "play each other" not in note:  # the header already says so
            lines.append(f"Special: {note}")
    for abbrev, team in TEAMS.items():
        watch = player_to_watch(abbrev, game_number(schedules[abbrev], game))
        bits = [b for b in (team_record(abbrev), watch) if b]
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
    """Write schedule.json: one entry per game day from today through the
    look-ahead window, keyed by date. Days without a game have no entry."""
    schedule = {}
    for n in range(DAYS_AHEAD + 1):
        day = today + timedelta(days=n)
        message = build_message(day)
        if message:
            schedule[day.isoformat()] = message
    OUT_FILE.write_text(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return schedule


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

    schedule = publish(today)
    print("Game days in the next week: " + (", ".join(schedule) or "none"))
    if today.isoformat() in schedule:
        print("-" * 40)
        print(schedule[today.isoformat()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
