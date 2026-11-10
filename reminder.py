#!/usr/bin/env python3
"""Game-day text reminders for the Flyers and the Stars.

Runs once a morning (see .github/workflows/game-day.yml). If either team plays
today (Mountain time), it texts everyone in RECIPIENTS through Twilio:
opponent, puck drop in Mountain time, anything special about the game, the
season record, one player to watch, and the next game coming up.

No third-party packages: standard library only.

Settings come from environment variables (GitHub secrets):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN   Twilio credentials
  TWILIO_FROM                             the Twilio number that sends
  RECIPIENTS                              phone numbers, comma separated
Optional:
  MODE            send (default) | preview (print only) | test (send a short test text)
  FOR_DATE        YYYY-MM-DD, pretend today is this date (for previews)
  SCHEDULE_CRON   the cron line that started this run (set by the workflow)
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Denver")
SEND_HOUR_LOCAL = 9  # 9 AM Mountain

TEAMS = {
    "PHI": {"name": "Flyers", "badge": "\U0001F7E0"},  # orange circle
    "DAL": {"name": "Stars", "badge": "⭐"},       # star
}

NHL_API = "https://api-web.nhle.com/v1"
FOOTER = "Reply STOP to quit, START to rejoin."

# Twilio error codes that mean "this person opted out", not "something broke".
OPTED_OUT_CODES = {21610}


# ---------------------------------------------------------------- NHL data

def fetch_json(url, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "game-day-reminder"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
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
    return "\n\n".join(blocks + [FOOTER])


# ------------------------------------------------------------------ Twilio

def parse_recipients(raw):
    numbers = []
    for part in re.split(r"[,;\n]+", raw or ""):
        digits = re.sub(r"\D", "", part)
        if not digits:
            continue
        if len(digits) == 10:
            digits = "1" + digits
        number = "+" + digits
        if number not in numbers:
            numbers.append(number)
    return numbers


def send_sms(sid, token, sender, to, body):
    """Returns (ok, detail). Never raises for a Twilio-side rejection."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode({"To": to, "From": sender, "Body": body}).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, json.load(resp).get("status", "queued")
    except urllib.error.HTTPError as err:
        try:
            info = json.load(err)
        except (json.JSONDecodeError, ValueError):
            info = {}
        if info.get("code") in OPTED_OUT_CODES:
            return True, "skipped (they replied STOP)"
        return False, f"Twilio error {info.get('code', err.code)}: {info.get('message', err.reason)}"
    except (urllib.error.URLError, TimeoutError) as err:
        return False, f"network error: {err}"


def deliver(body):
    missing = [k for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "RECIPIENTS")
               if not os.environ.get(k, "").strip()]
    if missing:
        print("Missing settings: " + ", ".join(missing))
        return 1
    recipients = parse_recipients(os.environ["RECIPIENTS"])
    sender = parse_recipients(os.environ["TWILIO_FROM"])[0]
    failures = 0
    for index, to in enumerate(recipients, start=1):
        ok, detail = send_sms(os.environ["TWILIO_ACCOUNT_SID"].strip(),
                              os.environ["TWILIO_AUTH_TOKEN"].strip(), sender, to, body)
        print(f"Recipient {index}: {detail}")
        failures += 0 if ok else 1
    return 1 if failures else 0


# -------------------------------------------------------------------- main

def is_right_slot(now_utc, cron):
    """The workflow fires at two UTC hours so one of them is always 9 AM
    Mountain, summer or winter. Only the matching one should send."""
    if not cron:
        return True  # started by hand
    fields = cron.split()
    if len(fields) < 2 or not fields[1].isdigit():
        return True
    offset_hours = now_utc.astimezone(LOCAL_TZ).utcoffset() // timedelta(hours=1)  # -7 or -6
    return int(fields[1]) == SEND_HOUR_LOCAL - offset_hours


def main():
    mode = (os.environ.get("MODE") or "send").strip().lower()
    now_utc = datetime.now(timezone.utc)

    if mode == "test":
        return deliver("Hockey reminders are set up. You'll get a text on Flyers and "
                       "Stars game days around 9 AM Mountain.\n\n" + FOOTER)

    if mode == "send" and not is_right_slot(now_utc, os.environ.get("SCHEDULE_CRON", "").strip()):
        print("Not the 9 AM Mountain slot. Nothing to do.")
        return 0

    override = (os.environ.get("FOR_DATE") or "").strip()
    today = date.fromisoformat(override) if override else now_utc.astimezone(LOCAL_TZ).date()

    message = build_message(today)
    if message is None:
        print(f"No Flyers or Stars game on {today}.")
        return 0

    print(message)
    print("-" * 40)
    if mode == "preview":
        print("Preview only, nothing sent.")
        return 0
    return deliver(message)


if __name__ == "__main__":
    sys.exit(main())
