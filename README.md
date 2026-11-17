# Flyers + Stars game-day texts

A personal project. On days the Flyers or the Stars play, a group chat gets
one text around 9 AM Mountain:

```
🟠 Flyers at Oilers 7pm
Record: 4-10-5
Watch: Travis Konecny (15 pts)
Next: Sat at Blue Jackets 5pm
```

A `Special:` line appears for playoffs, preseason, outdoor or neutral-site
games, and unusually early or late starts. On days both teams play, it is one
combined text. No game, no text.

## How it works

1. Every hour GitHub runs `reminder.py`, which writes the coming week's
   messages into `schedule.json`, one entry per game day. Schedule, record and
   stats come from the NHL's public feed, so it keeps working season after
   season.
2. At 9 AM an iPhone Shortcut reads `schedule.json`. If there is an entry for
   today, the phone sends it to the group chat as a normal text.

Nobody's phone number is stored here. To stop the sound but keep the
messages, mute the group chat on your phone (Hide Alerts).

## The iPhone Shortcut

1. **Date**: Current Date
2. **Format Date**: Custom, format `yyyy-MM-dd`
3. **Text**: `https://raw.githubusercontent.com/DaSmuggler22/hockey-game-day-texts/main/schedule.json`
4. **Get Contents of URL**: the Text from step 3
5. **Get Dictionary Value**: Value for the Formatted Date key in Contents of URL
6. **If** Dictionary Value **has any value**
7. **Send Message**: Dictionary Value, to the group. Show Compose Sheet off.
8. **End If**

Then add a Time of Day trigger for 9:00 AM under Edit > Automation.

## Trying it out

Actions tab > **Game day reminder** > **Run workflow**. `preview` shows the
message in the run log; `publish` updates `schedule.json`. Fill in a date like
`2026-11-21` to try another day.
