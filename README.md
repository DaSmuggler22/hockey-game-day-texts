# Flyers + Stars game-day texts

A personal project. On days the Flyers or the Stars play, a group chat gets
one text around 9 AM Mountain:

```
🟠 FLYERS GAME DAY
at Oilers, 7:00 PM MST
Record: 4-10-5
Watch: Trevor Zegras (14 pts)
Next: Sat 11/14 at Blue Jackets, 5:00 PM MST
```

A `Special:` line appears for playoffs, preseason, outdoor or neutral-site
games, and unusually early or late starts. On days both teams play, it is one
combined text. No game, no text.

## How it works

1. Early each morning GitHub runs `reminder.py`. If there is a game, it writes
   the message to `days/YYYY-MM-DD.txt`. Schedule, record and stats come from
   the NHL's public feed, so it keeps working season after season.
2. At 9 AM an iPhone Shortcut automation looks for today's file. If it exists,
   the phone sends its contents to the group chat as a normal text.

Nobody's phone number is stored here. To stop the sound but keep the
messages, mute the group chat on your phone (Hide Alerts).

## The iPhone Shortcut

Shortcuts app > Automation > New Automation > Time of Day > 9:00 AM, Daily,
Run Immediately. Then add these actions in order:

1. **Date**: Current Date
2. **Format Date**: Custom, format `yyyy-MM-dd`
3. **Text**: `https://raw.githubusercontent.com/DaSmuggler22/hockey-game-day-texts/main/days/` then the Formatted Date variable, then `.txt`
4. **Get Contents of URL**: the Text from step 3
5. **Get Text from Input**: Contents of URL
6. **If** Text **contains** `GAME DAY`
7. **Send Message**: the Text from step 5, to the group. Turn off Show When Run.
8. **End If**

## Trying it out

Actions tab > **Game day reminder** > **Run workflow**. `preview` shows the
message in the run log; `publish` writes today's file. Fill in a date like
`2026-11-21` to try another day.
