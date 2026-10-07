# RL Tracker

A small overlay window for Rocket League that shows ranks for everyone in your lobby. For now, this includes 1s/2s/3s MMR, peak MMR, and wins sourced from [tracker.gg](https://rocketleague.tracker.network/).

## Setup

1. Install [Python 3.9 or newer](https://www.python.org/downloads/windows/), then install the requirements from this folder:

   ```
   py -m pip install -r requirements.txt
   ```

2. Turn on Rocket League's Stats API. Close the game, then open `TAStatsAPI.ini` as administrator. It's in the game's `TAGame\Config` folder, usually one of:

   ```
   C:\Program Files\Epic Games\rocketleague\TAGame\Config\
   C:\Program Files (x86)\Steam\steamapps\common\rocketleague\TAGame\Config\
   ```

   If `TAStatsAPI.ini` doesn't exist, use `DefaultStatsAPI.ini` in the same folder. Make sure it contains:

   ```ini
   [TAGame.MatchStatsExporter_TA]
   Port=49123
   PacketSendRate=10
   ```

3. Launch Rocket League, then run:

   ```
   py rl-tracker.py
   ```

The window fills in when a match starts. You're detected automatically and shown at the top, with your team above the other team.

## Controls

| Action | Mouse | Key |
| --- | --- | --- |
| Switch playlist | Click 1v1 / 2v2 / 3v3 | `1` / `2` / `3` |
| Keep window above the game | Click "On top" | `T` |
| Transparent background | Drag the opacity slider | |

Each new match switches to the playlist that matches its team size. "On top" only works over the game in Borderless Windowed mode.

## Options

```
py rl-tracker.py --test PLATFORM ID   # show one profile without the game, e.g. --test steam 76561198000000000
py rl-tracker.py --port 49123         # use a different Stats API port
```

`PLATFORM` is one of `steam`, `epic`, `psn`, `xbl` or `switch`. Steam uses the 17-digit Steam ID; other platforms use the account name.

## Troubleshooting

- **"Waiting for Rocket League…" never changes:** the Stats API isn't on. Check the `.ini` edit above and restart the game.
- **Players show "blocked (403)":** tracker.gg is limiting requests. The app waits a minute and retries by itself.
- **Players show "not found":** tracker.gg has no profile for that account name, which can happen after a name change.

## Notes

- Profiles are cached for 10 minutes and fetched one at a time.
- Bots and players on unknown platforms are shown as "bot".
- This app uses tracker.gg's website API, which is unofficial and may change or stop working. It isn't affiliated with tracker.gg, Psyonix or Epic Games.