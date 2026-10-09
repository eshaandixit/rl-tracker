<div align="center">

# RL Tracker

A small overlay window for Rocket League that shows ranks for everyone in your lobby. For now, this includes 1s/2s/3s MMR, peak MMR, and wins sourced from [tracker.gg](https://rocketleague.tracker.network/).

![Windows](https://img.shields.io/badge/platform-Windows-0078D6)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

</div>

## Setup

### 1. Install Python and the requirements

Install [Python 3.9 or newer](https://www.python.org/downloads/windows/), then run this from the project folder:

```
py -m pip install -r requirements.txt
```

### 2. Turn on Rocket League's Stats API

Close the game, then open `TAStatsAPI.ini` as administrator. It's in the game's `TAGame\Config` folder, usually either:

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

### 3. Run it

Launch Rocket League, then run from your terminal or IDE:

```
py rl-tracker.py
```


## Controls

| Action | Mouse | Key |
| --- | --- | --- |
| Switch playlist | Click 1v1 / 2v2 / 3v3 | `1` / `2` / `3` |
| Keep window above the game | Click "On top" | `T` |
| Transparent background | Drag the opacity slider | |
| Open a player's tracker.gg profile | Click their name | |

> [!NOTE]
> "On top" only works in **Borderless Windowed** mode. Keyboard shortcuts only apply while the overlay window is focused, so they don't interfere in-game controls.

## Options

```
py rl-tracker.py --test PLATFORM ID   # show one profile without the game
py rl-tracker.py --port 49123         # use a different Stats API port
```

`PLATFORM` is one of `steam`, `epic`, `psn`, `xbl` or `switch`. Steam uses the 17-digit Steam ID; other platforms use the account name. For example:

```
py rl-tracker.py --test steam 76561198000000000
```

## Troubleshooting

<details>
<summary>"Waiting for Rocket League…" never changes</summary>
<br>
The Stats API isn't on. Check the <code>.ini</code> edit in step 2 and restart the game.
</details>

<details>
<summary>Players show "blocked (403)"</summary>
<br>
tracker.gg is limiting requests. The app waits a minute and retries by itself.
</details>

<details>
<summary>Players show "not found"</summary>
<br>
tracker.gg has no profile for that account name, which can happen after a name change.
</details>

## Notes

- Profiles are cached for 10 minutes and fetched one at a time.
- Bots and players on unknown platforms are shown as "bot".
- This app uses tracker.gg's website API, which is unofficial and may change or stop working.
