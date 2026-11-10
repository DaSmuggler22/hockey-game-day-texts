# Flyers + Stars game-day texts

Every morning around 9 AM Mountain, GitHub runs `reminder.py`. If the Flyers or
the Stars play that day, it texts everyone on the list through Twilio:

```
🟠 FLYERS GAME DAY
at Oilers, 7:00 PM MST
Record: 4-10-5
Watch: Travis Konecny (15 pts)
Next: Sat 11/14 at Blue Jackets, 5:00 PM MST

Reply STOP to quit, START to rejoin.
```

A `Special:` line appears for playoffs, preseason, outdoor or neutral-site
games, and unusually early or late starts. On days both teams play, it is one
combined text. No game, no text. Schedule, record and stats come from the
NHL's public feed, so it keeps working season after season.

## Who gets these texts

This is a personal, non-commercial project. The only recipients are the owner
and a few people the owner knows personally, each of whom asked in person to be added. Nobody
can sign up online and no numbers are collected, shared, or sold. Each person
gets at most one text on a day the Flyers or Stars play, and none otherwise.
Message and data rates may apply. Reply `STOP` at any time to opt out, `START`
to opt back in, or `HELP` for help. See [PRIVACY.md](PRIVACY.md).

## Settings (GitHub repo > Settings > Secrets and variables > Actions)

| Secret | What goes in it |
|---|---|
| `TWILIO_ACCOUNT_SID` | Account SID from the Twilio console home page |
| `TWILIO_AUTH_TOKEN` | Auth Token from the same place |
| `TWILIO_FROM` | Your Twilio phone number, e.g. `+15551234567` |
| `RECIPIENTS` | Everyone's mobile numbers, separated by commas |

To add or remove someone, edit the `RECIPIENTS` secret.

## Stopping and restarting

Anyone can reply `STOP` to stop getting texts and `START` to get them again.
Twilio handles both by itself; the script skips anyone who has stopped.

## Trying it out

Actions tab > **Game day reminder** > **Run workflow**, then pick a mode:

- `preview` shows today's message in the run log without texting anyone
  (fill in a date like `2026-11-11` to preview another day)
- `test` sends a short "you're set up" text to everyone
- `send` sends today's reminder right now

If a send fails, the run turns red and GitHub emails the repo owner.
