# AGENTS.md - install and run Taskbar Fighters for your user

You are an AI coding agent. Your user pasted this repository and wants Taskbar Fighters running on their PC: pixel fighters on
the Windows taskbar, one per AI program they use, fighting from real usage. This file is your runbook. Follow it top to bottom,
report each step's result in plain words, and stop at any step that fails.

The command-line tool is `minis.py` ("minis" is the internal short name: packages `minis_core` / `minis_win`, data folder
`%LOCALAPPDATA%\minis`).

## Rules for you, the agent

- **What this app reads:** only numbers and states from local AI-tool transcripts (token counts, timestamps, tool-call states),
  and the process list. Never prompt or reply text, window titles, file or project names. Do not change that.
- **No network.** The app makes no network calls. The only network step in this runbook is `git clone` and `pip install`.
- **Never edit the user's AI tool settings, hooks, status lines or config files** (Claude Code, Codex, Cursor or any other). This
  app needs none of that, and adding it is out of scope.
- **Ask before** adding a startup entry, a Start-menu shortcut, or anything outside the clone folder and `%LOCALAPPDATA%\minis`.
- **Do not** run `selftest-gui`, `arena`, or any screen capture as part of installing (the arena is visual only - it never
  touches a real window - but it fills a whole monitor, so it is the user's call). Do not kill processes by name; use
  `python minis.py stop`, which only stops what it started.
- Do not print the contents of the user's transcripts or `%LOCALAPPDATA%\minis` files into the chat.

**On a Mac?** Skip to [macOS (experimental)](#macos-experimental) below; sections 1-6 are the Windows runbook.

**No git, or the user just wants it installed?** Two shortcuts, same app: `python -m pip install taskbar-fighters` then
`taskbar-fighters start` (every `python minis.py X` below becomes `taskbar-fighters X`; skip the test step), or the Windows zip
from the latest GitHub release (`TaskbarFighters.exe`, no Python needed; `TaskbarFighters-cli.exe X` for commands). Only one copy
may run at a time: they share `%LOCALAPPDATA%\minis`, so `stop` one before starting another.

## 1. Preflight

Run these and check every answer before going on.

| check | command (PowerShell or cmd) | must be |
| --- | --- | --- |
| Windows 11 (10 untested) | `ver` | `Microsoft Windows [Version 10.0.x]`; build 22000 or higher is Windows 11. On Windows 10, tell the user it is untested |
| Python 3.12+ | `python --version` (or `py -3 --version`) | 3.12 or newer. Tested on 3.12 and 3.14. If missing: ask the user to install it from python.org or `winget install Python.Python.3.12` - with their yes |
| pip | `python -m pip --version` | any |
| git | `git --version` | any (or download the ZIP from GitHub) |
| taskbar at the bottom | ask the user, or Settings > Personalization > Taskbar > Taskbar behaviors | bottom; fighters hide when the taskbar is elsewhere or auto-hides |

Only one third-party package is needed: Pillow (see `requirements.txt`). Everything else is the Python standard library and
ctypes.

## 2. Install

```
git clone https://github.com/mrktchris/taskbar-fighters
cd taskbar-fighters
python -m pip install -r requirements.txt
```

## 3. Test

```
python -m unittest discover -s tests
```

Expect `OK` with about 14 tests skipped (the process-level tests only run with `MINIS_INTEGRATION=1`; do not set it). The tests use
synthetic data in a temp folder and never touch the user's real state. If something fails, stop and show the failing test name.

## 4. Start and confirm

```
python minis.py start
python minis.py status
```

`start` launches three windowless processes and after about 3 s prints what is on screen, e.g. `a: Claude Code, b: Sparring bot
asleep`. `status` should begin with a line saying it is running and who is on which side. Tell the user to look at the empty part
of their taskbar, left of the icons.

Then show them the basics: right-click a fighter for the menu, click a name on the scoreboard to pick fighters,
`python minis.py demo match` for a bout right now, `python minis.py pause` / `resume`, `python minis.py size 64|96|128` for the
fighter height (default 128). If they have a second monitor, they can try `python minis.py arena --rounds 1` themselves (visual
only; ESC ends it). Tell them the arena forges weapons from ONE picture of that monitor, held in RAM and never saved, and that
`python minis.py forge off` (or the menu's *Desktop weapons*) turns that off before they share their screen.

## 5. Optional - only with the user's yes

- **Start at logon:** `python minis.py print-startup` prints (never runs) a `schtasks` command and a shortcut target. Show the user
  what it will add, run it only if they say yes, and tell them the matching `schtasks /Delete` line it prints.
- **Start-menu shortcut:** `python minis.py shortcut` adds "Taskbar Fighters" to the Start menu (`--desktop` also adds one on the
  Desktop). Ask first. Then tell the user to right-click it in Start > **Pin to taskbar** themselves - Windows does not let a
  program pin itself, so do not try. `python minis.py shortcut remove` deletes only the shortcuts it made.
- **Tray icon** (no action needed): while it runs, an icon sits in the notification area. Left-click opens fighter select;
  right-click has Pause, Flash effects, Desktop weapons, Plates, Rival mode, arena, Bout now, Restart and Quit. `"tray_icon": false` in `minis.json`
  turns it off.
- **Streamer mode, stats card, skin packs** (only when the user asks): `python minis.py stream on` opens a window for OBS
  (docs/STREAMING.md); `python minis.py card` writes a PNG of their record; `python minis.py packs install <zip>` installs a
  pack file the user gives you - never download one for them (docs/SKIN-PACKS.md).
- **Restart:** `python minis.py restart` stops everything and starts it again (use it after editing `minis.json`).
- **Settings:** a `minis.json` next to `minis.py` overrides defaults (see README "Configuration"), e.g. `zone` if the fighters
  overlap the user's taskbar icons, `ignore_sources` to keep a program off the stage.

## 6. Stop and uninstall

```
python minis.py stop
```

To remove everything: run `stop`, `python minis.py shortcut remove` (if a shortcut was added), delete the clone folder, delete `%LOCALAPPDATA%\minis`, and if a startup task was added,
`schtasks /Delete /TN "MinisFighters" /F` (the exact line `print-startup` printed).

## macOS (experimental)

The macOS backend is **experimental**: its tests run in CI on macOS and it has run on the owner's Mac, but few Macs have tried
it. Tell the user that before you start, and follow
[docs/MAC-TESTING.md](docs/MAC-TESTING.md), which is the full checklist; this is the short form. The rules at the top apply
unchanged (no network beyond clone and pip, no edits to AI tool settings, ask before a login item).

**Preflight** (Terminal):

| check | command | must be |
| --- | --- | --- |
| macOS 13+ | `sw_vers -productVersion` | 13.0 or newer |
| chip | `uname -m` | `arm64` (Apple silicon) or `x86_64` (Intel); both are supported |
| Python 3.12+ | `python3 --version` (also try `python3.12`, `python3.13`) | 3.12 or newer. The system `python3` is too old: with the user's yes, they install it from python.org or `brew install python@3.12` |
| git | `git --version` | any (macOS may offer to install the command line tools: that needs the user's yes) |

**Install, test, start** (or, without a clone: `python3.12 -m pip install "taskbar-fighters[mac]"`, then `taskbar-fighters doctor`
and `taskbar-fighters start`):

```
git clone https://github.com/mrktchris/taskbar-fighters
cd taskbar-fighters
./scripts/setup_mac.sh --no-start
.venv/bin/python -m unittest discover -s tests
.venv/bin/python minis.py start
.venv/bin/python minis.py status
```

`setup_mac.sh` is idempotent: it checks macOS and Python, creates `.venv` in the clone, upgrades pip and installs
`requirements-mac.txt` (Pillow and PyObjC), and runs `python minis.py doctor`. If the doctor ends with `FAIL`, stop and show the
user its output. Do not use `sudo`, and do not install into the system Python.

**Tell the user what to look for:** two fighters standing on the top edge of the Dock (or at the bottom of the screen when the
Dock is on a side or auto-hides), and a Taskbar Fighters icon in the menu bar. No permission prompt should appear; if one does,
they should decline it and you should report it.

**Mac work in this repo** (not an install for a user): read [docs/MAC-HANDOFF.md](docs/MAC-HANDOFF.md) first. It is the channel
between the PC side and the Mac session: work its OPEN items top-down on real macOS, mark them DONE with the commit hash, and
add anything the PC side must know under "Found on Mac".

**Report back:** run `.venv/bin/python minis.py selftest-gui` (shows two fighters for 5 s and prints their frames, no capture)
and give the user the doctor and selftest output to paste into an issue, together with the questions in docs/MAC-TESTING.md.

**Optional, only with the user's yes:** `.venv/bin/python minis.py autostart on` writes one LaunchAgent plist so it starts at
login (`print-startup` shows it first; `autostart off` removes it). There is no Start-menu shortcut on macOS.

**Stop and uninstall:** `.venv/bin/python minis.py stop`; `autostart off` if it was turned on; delete the clone folder and
`~/Library/Application Support/minis`.

## Troubleshooting

| symptom | what to do |
| --- | --- |
| no fighters on the taskbar | `python minis.py status` (running?), then `python minis.py detect` (which AI programs are seen and how). With nothing detected, nothing is shown. Claude Code and Codex need a session file changed in the last 24 h |
| fighters cover taskbar icons / sit in the wrong place | set `"zone": [left, right]` in `minis.json` (screen x of the empty stretch), then `python minis.py restart` |
| nothing visible at all | the taskbar must be at the bottom and not auto-hiding; fullscreen apps hide the fighters |
| tiny or misplaced on a high-DPI display | only 100% scaling has been observed; integer scaling is untested at 150% / 200%. Tell the user and adjust `zone` |
| a program is shown that the user does not want | `"ignore_sources": ["<id from detect>"]` in `minis.json` |
| flashing bothers the user | `python minis.py flash off` |
| `start` says it is already running | `python minis.py restart` |
| anything else, either OS | `python minis.py doctor` and show the user its report (it ends with PASS or FAIL) |
| fighters too big or too small | `python minis.py size 64`, `96` or `128` (default 128) |

## Adapt it

- **A new AI program:** add one row to `RULES` in `minis_core/sources.py` - `dict(source='myagent', program='My Agent',
  character='generic', exe=('myagent.exe',), cmd=('myagent', '@scope/myagent'))` (exe = image name, cmd = names matched against an
  interpreter's first arguments). Optionally a short name in `LABEL`. Run the tests; `python minis.py detect` shows whether it is
  seen.
- **A new character:** add a `Body(...)` and an `_c(...)` entry to `art/roster.py` (copy an existing one: proportions, weapon,
  palette, signature strike / special / super / ultimate), then `python art/build_fighters.py --all --only <name>` to build `assets/<name>`
  and `assets_hd/<name>`, and run `python -m unittest tests.test_art`. It appears in the select screen's LOOK grid automatically;
  any program can wear it with `python minis.py skin <program> <name>`.
- Read `README.md` ("How it works") before changing the engine; keep the privacy rules above.
