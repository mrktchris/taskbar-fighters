<div align="center">

<img src="https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/assets/icon/minis-256.png" alt="Taskbar Fighters icon" width="96" height="96">

# Taskbar Fighters

**Your AI agents fight in your taskbar.**

Claude Code, Codex, Gemini, Cursor, Ollama, LM Studio and more, auto-detected and battling as pixel-art fighters based on what they're really doing.

[![CI](https://github.com/mrktchris/taskbar-fighters/actions/workflows/ci.yml/badge.svg)](https://github.com/mrktchris/taskbar-fighters/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mrktchris/taskbar-fighters?color=f0a184)](https://github.com/mrktchris/taskbar-fighters/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/taskbar-fighters?color=3776ab)](https://pypi.org/project/taskbar-fighters/)
[![License: MIT](https://img.shields.io/github/license/mrktchris/taskbar-fighters?color=blue)](https://github.com/mrktchris/taskbar-fighters/blob/master/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2011%20%7C%20macOS%20(experimental)-0078d4)](#install-and-run)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/downloads/)

<img src="https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/demo.gif" alt="Claude Code and Codex fighting on the taskbar to a K.O. with the scoreboard beside them, then arena mode: Claude cuts a blade out of a window title bar, swings it and it shatters" width="820">

</div>

- **Auto-detects your AI tools.** Every agent on your computer gets its own armed fighter (13 in all), with no hooks or
  config edits.
- **Fights from real usage.** They clash while an agent works, hand off when a task finishes, and get K.O.'d at the
  context limit. Best-of-3 matches, supers, ultimates and hand-directed cinematic set pieces, always locked on to each other.
- **Arena mode with desktop weapons.** The fight breaks out onto a whole monitor, and fighters cut weapons out of your
  windows. Visual only: nothing real happens to your windows.
- **Private by design.** It reads numbers only, never your prompts or files, and makes no network calls.

<div align="center">

[![Download for Windows](https://img.shields.io/badge/Download-Windows%20.zip-0078d4?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/mrktchris/taskbar-fighters/releases/latest/download/TaskbarFighters-windows.zip)
[![pip install](https://img.shields.io/badge/pip-install%20from%20release-3776ab?style=for-the-badge&logo=pypi&logoColor=white)](#install)
[![macOS experimental](https://img.shields.io/badge/macOS-experimental-555555?style=for-the-badge&logo=apple&logoColor=white)](#macos-experimental)

**⭐ Star it if your agents deserve a fight.**

</div>

## Install

| | |
| --- | --- |
| **Windows, no Python needed** | Download [TaskbarFighters-windows.zip](https://github.com/mrktchris/taskbar-fighters/releases/latest/download/TaskbarFighters-windows.zip), unzip it and double-click `TaskbarFighters.exe`. The zip is not code-signed, so SmartScreen may ask once: **More info > Run anyway**. Quit from the tray icon or with `TaskbarFighters-cli.exe stop`. |
| **pip, Windows (Python 3.12+)** | `pip install "taskbar-fighters @ https://github.com/mrktchris/taskbar-fighters/releases/download/v1.0.0/taskbar_fighters-1.0.0-py3-none-any.whl"` then `taskbar-fighters start` (the PyPI listing, `pip install taskbar-fighters`, is coming) |
| **pip, macOS (experimental)** | `pip install "taskbar-fighters[mac] @ https://github.com/mrktchris/taskbar-fighters/releases/download/v1.0.0/taskbar_fighters-1.0.0-py3-none-any.whl"` then `taskbar-fighters doctor` and `taskbar-fighters start` |
| **From source** | see [Install and run](#install-and-run) (Windows) or [macOS](#macos-experimental) |

> **Or paste this to your AI agent.** Claude Code, Codex, Cursor or any coding agent:
>
> ```
> Install and run Taskbar Fighters from https://github.com/mrktchris/taskbar-fighters - follow AGENTS.md.
> ```
>
> The agent follows [AGENTS.md](https://github.com/mrktchris/taskbar-fighters/blob/master/AGENTS.md) on Windows and on macOS: it checks your computer, installs the Python packages
> (Pillow; on a Mac also PyObjC, into a `.venv`), runs the tests, starts the fighters and asks you before adding a startup
> entry or a shortcut.

Run one copy at a time: a git checkout, a pip install and the Windows zip share one data folder (`%LOCALAPPDATA%\minis`,
on macOS `~/Library/Application Support/minis`), so stop one before starting another. With pip, every `python minis.py ...`
command below is `taskbar-fighters ...`; in the zip it is `TaskbarFighters-cli.exe ...`.

<sub>The command-line tool is `minis.py`; "minis" is the internal short name you will see in commands, folders and the data
directory. The loop above is rendered offline by the app's own planner and renderer with DEMO numbers, on a synthetic
desktop drawn for the picture, never a screen capture (`python packaging/launch_media.py`).</sub>

## What it does

Every AI coding program running on your computer - Claude Code, Codex, Gemini, Cursor, Ollama, LM Studio, Copilot CLI and more -
is detected automatically and gets a pixel fighter. At most two stand in the empty part of your taskbar (on a Mac, on top of
the Dock). They spar while both programs are idle, clash while one is working, hand work over when a task finishes, get knocked
out when a program hits its context limit, and fight best-of-3 matches with HP bars, banners, cinematic set pieces and one
signature ultimate each. Each fighter has a small HUD plate with the program's state and context fill, and a scoreboard keeps
the record.

It is all visual. It reads numbers from local files and the process table; it never touches your agents, your windows or the
network.

![A real bout captured on the live Windows 11 taskbar: HUD plates on the left, two fighters in the middle, the scoreboard on the right](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/live-taskbar.png)

![A live bout on the real taskbar](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/live-bout.gif)

![The taskbar strip annotated: HUD plates on the left, two 128 px fighters in the middle, the scoreboard on the right](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/hero-taskbar.png)

## Features

- **Auto-detect.** Claude Code and Codex from their local session transcripts (numbers and enums only); a dozen other programs
  from the process table. No hooks, no config edits, nothing installed into your agents. `python minis.py detect` shows what is
  seen right now and how.
- **Thirteen armed fighters in HD.** One per program (Claude, Codex, Gemini, Cursor, Ollama, LM Studio, and a generic Agent for
  everything else) plus six selectable extras (Kunoichi, Knight, Barbarian, Monk, Nomad, Oni). Fighters are 128 px tall by
  default (real 128 px art); `size 96` or `size 64` makes them smaller. Every frame is generated by a rig from pose data.
- **A deep move set.** 56 shared moves plus each fighter's signature strike, special, super and ultimate and 8-10 weapon-family
  moves: 3-hit strings, air juggles, throws, chain pulls, dash-through cuts, guard breaks, ripostes, weapon locks and armoured
  heavies, each with its own contact sparks.
- **Cinematic set pieces.** Hand-directed exchanges for both fighters (blade lock, pull and launch, cross-cut freeze, vault
  overhead, parry riposte, guard crush, reversal, aerial finish) play at a match's dramatic moments, mixed with the
  procedural fight. Any pairing plays them.
- **Battles from real usage.** Clash when either program is working, spar or ranged duel when neither is, a handoff when one
  finishes a task, a KO and a consoling visit when one hits its limit, timed best-of-3 matches.
- **Locked on.** Fighters always face and aim at each other, even right after a dash-through swaps their sides; strikes
  land from inside their reach and shots fly at the opponent.
- **Real jumps.** A crouch, the rise, a hang at the apex and a landing (an 8-frame row for every fighter), drawn with
  headroom above the taskbar so nothing is cut off. HUD plates and the scoreboard keep clear of the fighters at 64, 96
  and 128 px.
- **HUD plates.** Program name, state (`working idle done waiting? sleeping limit`), a 10-segment context meter and the context
  %, plus a plan figure with a reset countdown when it can be trusted. Unknown is always `-`.
- **Scoreboard.** Names and W-L per program, HP bars during a match, a result line ("CLAUDE WINS 2-1"), a 7-day context
  sparkline, and Pause / Arena / Bout now buttons.
- **Rounds and winners.** Best-of-3, 100 HP, supers from a meter, one ultimate per match, impact frames and a KO finisher.
  Winners are weighted by a health score (`decided`) or a coin flip (`random`).
- **Platform-fighter frame data.** Every hit freezes both fighters for a hitlag that grows with its damage, adds to a damage
  % shown on the plate during a match, and knocks back further the higher that % climbs; hitstun follows the knockback,
  big late hits tumble along a real arc and end in a tech or a knockdown, blocks have shieldstun and pushback. Fights
  redraw at 60 fps.
- **Rival mode.** A sleeping partner (a program that went quiet, or the sparring bot) is woken now and then for a match, then
  goes back to sleep. The plate keeps saying `sleeping`.
- **Fighter select.** Pick which program fights on each side, and which character any program wears, from an arcade-style select
  screen, the right-click menu or the CLI.
- **Arena mode.** The fight breaks out onto a whole monitor: window edges become walls and ledges, glass cracks and shatters,
  beams clash, the camera punches in. Visual only - nothing real happens to your windows.
- **Desktop weapons.** In the arena, fighters cut pieces out of your windows and forge them into weapons that crack and
  shatter. The screen picture they are made from stays in memory and is never saved; `forge off` turns it off
  ([Desktop weapons](#desktop-weapons)).
- **Windows and macOS.** Windows 11 is the tested home. macOS (fighters on the Dock, a menu-bar icon) is experimental, and its
  test suite runs in CI on every push.
- **Tray icon and Start-menu shortcut.** Left-click the tray icon for fighter select, right-click for the menu (Restart, Quit);
  `python minis.py shortcut` adds Taskbar Fighters to Start so you can pin it.
- **Streamer mode.** `python minis.py stream on` opens a normal window with the live fight on a chroma-key background for
  OBS, built from the fighters' own frames ([Streamer mode](#streamer-mode)).
- **Stats card, careers and achievements.** `python minis.py card` renders a shareable 1200 x 675 picture of your agents'
  record; lifetime careers, head-to-head records and local ranks; 22 achievements with open criteria and a small toast on
  the scoreboard ([Stats card and achievements](#stats-card-and-achievements)).
- **Skin packs.** Install community looks from a zip; strict validation, data only ([Skin packs](#skin-packs)).
- **Controls.** Pause, hide plates, flash effects on/off (no white flashes or impact frames for anyone who dislikes strobing),
  fighter size, hide a fighter, drag, double-click for a victory pose, Shift-drag to throw.
- **Optional sound effects, off by default.** `python minis.py sound on` (or the menus' *Sound effects*): short, quiet,
  original sounds made from math (`art/build_sfx.py`, no recordings) for hits, clashes, swings, rounds and KOs; one process
  plays them, rate-limited, and nothing plays while paused or hidden.

## The roster

![All 13 fighters at 4x: the seven program characters with the programs they play and their weapons, and the six selectable extras](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/roster.png)

| fighter | plays | weapon | strike / special / super / ultimate |
| --- | --- | --- | --- |
| Claude | Claude Code | katana | spin_kick / slash_wave / reverse / radiant_beam |
| Codex | Codex (CLI and desktop app) | twin kunai and chain | ground_pound / deploy / sudo / spiral_orb |
| Gemini | Gemini (app and CLI) | twin short blades | spin_kick / star_shot / twin_flash / crescent_fang |
| Cursor | Cursor | spear | ground_pound / tab_bolt / autocomplete / grapple_strike |
| Ollama | Ollama | staff | ground_pound / pull_shot / serve / gale_rend |
| LM Studio | LM Studio | energy katana | spin_kick / load_wave / hot_swap / awakening |
| Agent | aider, opencode, Windsurf, Copilot CLI, Qwen Code, Perplexity, Grok, ChatGPT, Amazon Q, the sparring bot | bow and dagger | spin_kick / energy_bolt / overclock / star_core |
| Barbarian | selectable extra | axe | axe_spin / axe_toss / berserk / earthsplitter |
| Knight | selectable extra | greatsword | crusher / sword_wave / valor / holy_crescent |
| Kunoichi | selectable extra | twin fans | fan_whirl / petal_shot / vanish / petal_dance |
| Monk | selectable extra | twin tonfa | palm_crash / chi_bolt / meditate / chi_sphere |
| Nomad | selectable extra | twin chakrams | ring_spin / chakram_throw / mirage / ring_storm |
| Oni | selectable extra | kanabo club | club_slam / oni_fire / rampage / oni_roar |

Programs detected since the growth release wear the extras by default: Zed as the Knight, Junie as the Kunoichi, Cline as
the Barbarian, Continue as the Monk, Goose as the Nomad, Crush as the Oni, Jan as LM Studio, the Claude desktop app as
Claude. Any program can wear any look (`python minis.py skin <program> <character>`).

### Detected programs

`python minis.py detect` lists every row and whether it is running now. Process names and command lines are compared and
then discarded; nothing about them is stored or shown beyond the executable's file name.

| program | Windows | macOS | notes |
| --- | --- | --- | --- |
| Claude Code | session transcripts (`claude.exe` / the npm CLI only claimed) | same (`claude`) | numbers from the transcript |
| Codex | session transcripts (`codex.exe`, the npm CLI, the Codex desktop app's `ChatGPT.exe` under `OpenAI.Codex_*`) | same (`codex`, `Codex.app`) | numbers from the transcript |
| Claude desktop | `claude.exe` under `AnthropicClaude\` or the `Claude_*` app package | `Claude.app` | process CPU only; seen on a real PC |
| ChatGPT desktop | `ChatGPT.exe` (anywhere but the Codex package) | `ChatGPT.app` | |
| Cursor, Windsurf, Zed | `cursor.exe`, `windsurf.exe`, `zed.exe` | `Cursor.app`, `Windsurf.app`, `Zed.app` | editors: shown while open |
| Gemini CLI, Qwen Code, Copilot CLI | `node` + `@google/gemini-cli`, `@qwen-code/qwen-code`, `@github/copilot` | same | npm CLIs, by package path |
| Junie | `junie.exe`, `@jetbrains/junie` | `junie` | the CLI; JetBrains AI Assistant inside an IDE is not separable from the IDE and is not detected |
| Cline, Continue | `node` + `cline`, `@continuedev/cli` | same | the CLIs only. The VS Code extensions run inside VS Code's extension host, which cannot be told apart from plain VS Code, so they are not detected (and plain VS Code never shows as Cline or Continue) |
| Roo Code | - | - | a VS Code extension only: not detected, for the same reason |
| Amazon Q Developer CLI | - (Windows runs it in WSL) | `q`, `qchat`, `Amazon Q.app` | |
| aider, opencode, Crush, Goose | `aider.exe` / `python -m aider`, `opencode.exe`, `crush.exe` / `@charmland/crush`, `goose.exe` | `aider`, `opencode`, `crush`, `goose`, `Goose.app` | `goose` is also the name of an unrelated database tool, which would show as Goose while it runs |
| Ollama, LM Studio, Jan | `ollama.exe`, `lm studio.exe`, `jan.exe` | `Ollama.app`, `LM Studio.app`, `Jan.app` | |
| Perplexity, Grok | `perplexity.exe`, `grok bot.exe` | `Perplexity.app`, `Grok.app` | |

The names added in this release come from each vendor's install documentation; apart from the Claude desktop app, none
has been seen on a real machine yet. A program that is missing or misnamed is a one-line fix in `RULES`
(`minis_core/sources.py`).

### Moves

Every character has the full shared move set (locomotion, strikes, defence, reactions, emotes, states), its signature strike,
special, super and ultimate, and its weapon family's moves. [MOVELIST.md](https://github.com/mrktchris/taskbar-fighters/blob/master/MOVELIST.md) lists every move, input notation,
trigger and timing for all 13 fighters.

![Claude's signature and weapon moves frame by frame with hold times, contact frames and smears](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/moves-claude.png)

<details><summary>Codex, Knight and Kunoichi</summary>

![Codex's moves frame by frame](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/moves-codex.png)

![Knight's moves frame by frame](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/moves-knight.png)

![Kunoichi's moves frame by frame](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/moves-kunoichi.png)

</details>

All thirteen sheets are in `docs/img/moves-<character>.png`.

### Impact frames and the KO finisher

![Six consecutive frames around a KO: one normal frame, then flat silhouettes and radial lines for about 130 ms](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/impact-frames.png)

![The KO finisher in eight labelled frames: the deciding blow, the freeze, the slow-motion fall, the winner on the highest window](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/ko-finisher.png)

### Cinematic set pieces

![Arena set pieces frame by frame: a flame-drawn stance and a frozen beat before the cut, a water-trail flurry, a petal-trail finisher](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-setpieces.png)

A match plays one to three set pieces at its dramatic moments (a round's second exchange, the comeback, match point), on the
taskbar and in the arena. They are data, written against weapon-family slots, so any two fighters can play any of them.
Preview one with `python tools/setpiece_preview.py <piece> --a claude --b codex`. The list is in
[MOVELIST.md](https://github.com/mrktchris/taskbar-fighters/blob/master/MOVELIST.md#set-pieces).

### V5 -> V6

![Side by side, each program character in V5 and in V6: idle and the signature strike's contact frame](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/before-after.png)

## HUD plates

![The HUD plate annotated (program name, state word, context meter, numbers) and every state with an explanation](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/plates.png)

Context = tokens of the newest assistant line over the model's context window. A tool call unanswered for 45 s shows `waiting?`
(amber); 10 quiet minutes is `idle`; 30 minutes is `sleeping`. A plan figure appears only when its limit id, value and reset time
all check out. Process-detected programs have no numbers (`ctx -`).

## Scoreboard

![The scoreboard in five states: plain, during a match, after a match, a fighter hidden, paused](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/scoreboard.png)

## Fighter select

![The select screen: WHO row, LOOK grid and the VS card, with how to open it and the CLI equivalents](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/select.png)

- **Open it:** right-click a fighter > *Select fighters...*, or click a name on the scoreboard (opens that side only).
- **Pick** a program for a side and it stays there: live when detected, asleep and dimmed when not. A side on `auto` follows the
  director. **Look**: any program can wear any character; the plate still names the program.
- Arrows + Enter, Backspace to go back, Esc or a click elsewhere cancels; mouse clicks and the wheel work too. It is the only
  window that takes keyboard focus, and only while open.

## Arena mode

![Arena mode on a synthetic desktop: a set piece's ink-wash cut, a beam clash, a crater on the taskbar line, the winner on the highest window](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena.png)

![Arena mode animated, on a synthetic desktop](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena.gif)

**Visual only - nothing real happens to your windows.** The arena is one click-through overlay that reads window rectangles
(never titles or contents) and paints on itself. No real window is moved, resized, focused, closed or typed into; screen shake
moves only the overlay. The images here are headless renders on a desktop drawn for the picture, not a screen capture.

```
python minis.py arena [--monitor N] [--rounds 1|3|5|endless] [--endless] [--intensity calm|normal|wild]
                      [--seconds S] [--no-intro] [--no-outro] [--freeze]
python minis.py arena stop
```

Or the scoreboard's Arena button, or the right-click menu. ESC, the on-screen EXIT button, `arena stop` or the scoreboard end
it. Flags you leave out fall back to `"arena": {...}` in `minis.json`, then to the defaults (best of 3, `normal`).

- **Intro and outro.** The fighters burst out of the taskbar and a VS card slides in; at the end the winner flies to the
  highest window to pose and both dive back into the taskbar.
- **The stage.** Window edges are walls and ledges: wall bounces, tech recoveries, ledge grabs and climbs, knock-throughs that
  leave a cracked silhouette in the glass, skids with sparks, craters on the taskbar line, shard platforms.
- **In the air.** Double jumps, air dashes, juggles, meteor spikes through every window top on the way down, recovery jumps.
- **Camera.** Letterbox for big moments, a seamless zoom punch, speed lines, a slow-motion final KO. `flash off` removes every
  full-screen frame.
- **Beam clashes and set pieces.** Two beams meet and push back and forth; sword scenes with elemental trails play 2-4 times a
  match.
- **Intensity.** `calm` halves the effects and turns hazards off; `wild` adds more of everything.

<details><summary>Stage, air, camera, clash, hazards, intro</summary>

![Stage interaction](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-stage.png)

![Aerial game](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-air.png)

![Camera](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-camera.png)

![Beam clash](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-clash.png)

![Stage hazards](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-hazards.png)

![Intro and outro](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-intro.png)

</details>

### Desktop weapons

![Desktop weapons, animated on a synthetic desktop: a glowing outline cuts a title bar out of a window, the piece shatters into pixels and re-forms as a blade in the fighter's hand, it swings, cracks and shatters](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-forge.gif)

A fighter reaches for a window, a glowing outline cuts a piece out of it, the piece lifts off (a dark hole is painted where
it was), shatters into pixels and re-assembles as that fighter's weapon: a blade from a title bar, a greatsword or axe from a
window chunk, a spear from a taskbar strip, a club, glass shards. The weapon sits in the fighter's hand on every frame and
swings with the arm, cracks with every hit and shatters into pixel debris. Slabs get thrown, and chunks knocked off windows
can be picked up. 2-4 a match (`calm` 1, `wild` 5 or more). Nothing happens to the real windows: the cut, the hole and the
weapon are paint on the arena's own overlay.

**Privacy: arena mode grabs the screen into memory to forge weapons, and never saves it.** When an arena starts it takes ONE
picture of its monitor into RAM, and fighters cut pieces out of that picture. The picture is never written to disk, a log, a
temp file or `arena.json`, `arena capture` refuses while it is held, and it is dropped when the arena closes. **Run
`python minis.py forge off` before you share your screen** or record anything private, or untick **Desktop weapons** in the
tray or fighter menu (a running arena drops its picture within 2 seconds). The taskbar fighters never read the screen. On
macOS the picture needs the Screen Recording permission, which Taskbar Fighters never asks for; without it the weapons are
forged from window shapes instead.

![Desktop weapons on a synthetic desktop: the cut, the hole, the pixel morph, the weapon families, a swing, cracks, the shatter, a thrown slab](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/arena-forge.png)

Every option, effect and number: [docs/ARENA.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/ARENA.md).

## Streamer mode

![The stream window: both fighters, the HUD plates and the scoreboard on a green chroma-key background](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/stream.png)

`python minis.py stream on` opens **Taskbar Fighters — Stream**, a normal window (not topmost, not click-through,
resizable) showing the live fight strip on `#00FF00`, always at a whole-number scale. In OBS add it as a **Window Capture**
and put a **Chroma Key** filter on it. `stream off` closes it; the tray menu has *Streamer mode (OBS window)*.
`--chroma #FF00FF` changes the key colour, `--no-plates` leaves the context numbers out, `--transparent` tries an alpha
background (experimental). The picture is made from the fighters' own window images (the same self-dump `own_capture`
uses), never a screen capture, and desktop weapons are switched off while you stream. Setup and options:
[docs/STREAMING.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/STREAMING.md).

## Stats card and achievements

![A stats card: four program cards with fighter sprites, rank, W-L, win %, streak, favourite move and head-to-head, and 22 achievement badges](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/stats-card.png)

<sub>DEMO numbers (`python tools/card_preview.py`).</sub>

- `python minis.py card` writes a 1200 x 675 PNG of your agents' record into the data folder's `exports\` (or into an
  existing folder / a `.png` path you name with `--out`), then prints each program's career and the head-to-head records
  ("Claude vs Codex 34-29 (last 10: 6-4)"). `--share`, and the menu's *Share my stats card…*, then open that folder with
  the card selected.
- **Careers**: lifetime W-L, win %, current and best streak, KOs, flawless rounds, comebacks, ultimates, favourite move.
  **Ranks** (Bronze, Silver, Gold, Master, Legend) follow lifetime wins, so they only ever climb.
- **Achievements**: `python minis.py achievements` lists all 22 with what each takes and how far you are; none is secret.
  Fight (First KO, Flawless, Comeback, Perfect, Unstoppable ...), Discovery (Cinema, Director's Cut, Blacksmith,
  Squad ...) and Partnership (Job Done, Teamwork, Old Rivals). None rewards token use, hours, context or time of day, and
  nothing is taken away for being away. A new one shows as a small 3-second toast on the scoreboard.
- Everything comes from `record.json` (since this release it also keeps a log of the last 500 matches with the facts above
  and each match's seed and lineup, so a match can be rebuilt for a replay) and `achievements.json`: program ids, move
  names and numbers only.

## Skin packs

Community looks any program can wear: `python minis.py packs install shadow-ronin.zip`, then pick it in fighter select or
`python minis.py skin claude "Shadow Ronin"`. A pack is a `pack.json` (name, author, licence) plus the same sprite sheets
the built-in fighters use, at 64 px and optionally 128 px. Packs are data only and strictly checked (file names, sizes,
sheet geometry, a 64-colour cap, every move the engine plays, zip paths); nothing in a pack is ever run.
`python tools/make_example_pack.py` builds a valid example from a built-in fighter. Format and rules:
[docs/SKIN-PACKS.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/SKIN-PACKS.md).

## Install and run

**Requirements:** Windows 11 (tested; Windows 10 should work but is untested), the taskbar on any edge, Python 3.12 or
newer (tested on 3.12 to 3.14), and Pillow. Nothing else: no services, no network, no startup entries unless you add one. The
Windows zip needs no Python at all. On a Mac, see [macOS](#macos-experimental).

```
git clone https://github.com/mrktchris/taskbar-fighters
cd taskbar-fighters
python -m pip install -r requirements.txt
python minis.py start
python minis.py status
```

Or `pip install "taskbar-fighters @ https://github.com/mrktchris/taskbar-fighters/releases/download/v1.0.0/taskbar_fighters-1.0.0-py3-none-any.whl"` and `taskbar-fighters start` (`pip install taskbar-fighters` once the PyPI listing is live).

`start` launches three windowless processes (a director and fighter slots `a` and `b`) and after about 3 s prints what is on
screen, for example `a: Claude Code, b: Sparring bot asleep`.

**Start at logon (optional).** `python minis.py print-startup` prints - never runs - a `schtasks` command and a shortcut target
you can use; it also prints the command to remove the task again.

**Stop and uninstall.** `python minis.py stop` ends only the processes it started (it checks each one's exact command line).
`python minis.py shortcut remove` deletes the shortcuts it made. Delete the `taskbar-fighters` folder (or run
`pip uninstall taskbar-fighters`, or delete the unzipped folder) and `%LOCALAPPDATA%\minis` to remove everything; remove a
startup task you added with the `schtasks /Delete` line `print-startup` shows.

`python minis.py doctor` prints a report of this machine (versions, screen and taskbar geometry, detected programs, a test
window) that ends with PASS or FAIL; paste it to your AI agent or into an issue when something is off.

**Fighter size.** Fighters are 128 px tall by default (the HD art). `python minis.py size 96` or `size 64` makes them smaller
(also in the right-click menu's *Fighter size*); running fighters restart to apply it. `"fighter_size"` in `minis.json` sets
the default.

## macOS (experimental)

> **Experimental, but CI-verified.** The full test suite and `doctor --headless` run on macOS in GitHub Actions on every push,
> and the fixes from the first runs on a real Mac are in this release. It has not been tried on many Macs yet: if it draws in
> the wrong place, run `python minis.py doctor` and paste the report into an issue. The checklist:
> [docs/MAC-TESTING.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/MAC-TESTING.md). Open Mac test items from the
> PC side, and what was found on real Macs, are tracked in
> [docs/MAC-HANDOFF.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/MAC-HANDOFF.md).

**Requirements:** macOS 13 (Ventura) or newer, Apple silicon or Intel, Python 3.12 or newer (from python.org or
`brew install python@3.12`; the `python3` that ships with macOS is too old), Pillow and PyObjC.

```
pip install "taskbar-fighters[mac] @ https://github.com/mrktchris/taskbar-fighters/releases/download/v1.0.0/taskbar_fighters-1.0.0-py3-none-any.whl"
taskbar-fighters doctor
taskbar-fighters start
```

or from source:

```
git clone https://github.com/mrktchris/taskbar-fighters
cd taskbar-fighters
./scripts/setup_mac.sh
```

The script checks your macOS version and chip, finds Python 3.12+, creates `.venv` in the clone, runs
`pip install --upgrade pip` and `pip install -r requirements-mac.txt`, then `python minis.py doctor` and `python minis.py start`.
By hand: `python3.12 -m venv .venv`, `.venv/bin/python -m pip install --upgrade pip` (an old pip may try to compile PyObjC),
`.venv/bin/python -m pip install -r requirements-mac.txt`, `.venv/bin/python minis.py start`.

- **Where they stand:** on top of the Dock's top edge, with the scoreboard at the right end of the strip. A Dock on the left or
  right, or one that auto-hides, falls back to a strip at the bottom of the screen. Plates and the scoreboard are drawn at the
  screen's Retina scale and fade out of the way while the mouse is over them.
- **Plates in the menu bar (optional):** right-click a fighter > *Plates position* > *In the menu bar*, or
  `python minis.py plates menubar` (`plates dock` puts them back); they sit just left of the notch.
- **Menu-bar icon** instead of the tray icon, with the same menu (left click: fighter select; right click or Control-click: the
  menu). No Dock icon: it runs as a background (accessory) app. On a notched MacBook with a full menu bar, macOS may hide the
  icon behind the notch. Then a small badge with the same icon appears just left of the notch (left click: select, right click:
  the menu), `status` says so, and the fighter's right-click menu has everything. Cmd-drag the icon to a visible spot once and
  macOS remembers it.
- **No permissions needed:** no Accessibility, no Screen Recording, no Input Monitoring. The arena reads window *bounds* only.
  Arena desktop weapons use real screen pixels only if you have granted Screen Recording yourself (it is never requested;
  `python minis.py doctor` says how); otherwise they are forged from window shapes.
- **What differs:** no arena `--freeze` and no `arena capture` (both would need a screen capture); start at login is
  `python minis.py autostart on` (one LaunchAgent plist; `autostart off` removes it; `print-startup` only shows it); no Start
  menu, so `shortcut` only explains; `selftest-gui` shows two fighters (at your fighter size) for 5 s and reports their window
  frames instead of comparing screenshots; data lives in `~/Library/Application Support/minis`.
- **Stop:** `python minis.py stop` (SIGTERM, then SIGKILL only for a process still proven ours).

### Taskbar and tray icon

![The app icon at every size on dark and light taskbars, and an illustration of the tray icon with its tooltip and right-click menu](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/icon-tray.png)

- `python minis.py shortcut` adds **Taskbar Fighters** to the Start menu (`--desktop` also puts one on the Desktop). Then
  right-click Taskbar Fighters in Start > **Pin to taskbar** (Windows only lets you pin a program; it never pins itself).
  `python minis.py shortcut remove` deletes the shortcuts it made, only if they still run this `minis.py`.
- While it runs, its icon sits in the notification area (tray). Hover: who is fighting ("Taskbar Fighters — Claude vs Grok").
  **Left-click**: fighter select. **Right-click**: Select fighters..., Pause animations, Flash effects, Desktop weapons, Sound effects,
  Plates, Rival mode, Start/Exit arena, Bout now, Share my stats card…, Streamer mode (OBS window), Restart Taskbar Fighters,
  Quit Taskbar Fighters.
- `python minis.py restart` stops everything and starts it again.
- No tray icon: set `"tray_icon": false` in `minis.json`.
- Rebuild the icon: `python art/build_icon.py [--preview qa/local/icon-preview.png]`.

## Commands

Every command below was checked against `python minis.py --help` and each subcommand's `--help`. With pip the command is `taskbar-fighters`, in the Windows zip `TaskbarFighters-cli.exe`.

| command | what it does |
| --- | --- |
| `python minis.py start` | start the director and both fighter slots (no console windows) |
| `python minis.py stop` | stop them: only PIDs it recorded itself, after proving each one's command line |
| `python minis.py status` | one plain line (running?, who is on which side, rival mode), then the details |
| `python minis.py restart` | stop everything, then start again (what the tray's *Restart Taskbar Fighters* runs) |
| `python minis.py shortcut [--desktop]` / `shortcut remove` | Start-menu (and Desktop) shortcut "Taskbar Fighters" / delete the ones it made |
| `python minis.py pause` / `resume` | freeze every fighter on one frame (plates keep updating) / animate again |
| `python minis.py plates on\|off` | show or hide both HUD plates |
| `python minis.py demo [spar\|clash\|ranged\|match]` | start one bout now |
| `python minis.py winners decided\|random` | how match winners are drawn (default `decided`) |
| `python minis.py rival on\|off` | rival mode: wake a sleeping partner for a match now and then |
| `python minis.py flash on\|off` | white flashes and impact frames on big hits |
| `python minis.py sound on\|off` | optional sound effects (default off): quiet, original, generated by `art/build_sfx.py` |
| `python minis.py fighters` | programs seen and their state, every character, the current lineup |
| `python minis.py fighters set a\|b <program\|character>` | a program: keep it on that side; a character: that side's look |
| `python minis.py fighters pin a\|b <program>` | keep a program on that side, asleep when not detected |
| `python minis.py fighters auto` / `reset` | both sides back to auto (`reset` also forgets every look) |
| `python minis.py pick a\|b <program>\|auto` | alias of `fighters pin` (or `auto` for one side) |
| `python minis.py skin <program> <character>\|default` | draw a program as another character, e.g. `skin grok knight` |
| `python minis.py show [a\|b]` | bring back a hidden fighter |
| `python minis.py detect` | which known AI programs are seen right now, and how (names and numbers only) |
| `python minis.py monitors` | list monitors for `arena --monitor N` |
| `python minis.py arena [--monitor N] [--rounds 1\|3\|5\|endless] [--endless] [--intensity calm\|normal\|wild] [--seconds S] [--no-intro] [--no-outro] [--freeze] [--seed K]` | arena mode ([docs/ARENA.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/ARENA.md)); `arena stop` ends it |
| `python minis.py arena capture <png>` | PrintWindow of the arena's own window only (refused with `--freeze` or while the arena holds a desktop-weapons screen grab; writes only under `qa/` or the data folder) |
| `python minis.py forge on\|off` | desktop weapons in the arena (default on: one RAM-only screen grab per arena, never saved) |
| `python minis.py print-startup` | print (never run) the commands to start at logon (macOS: the LaunchAgent plist) |
| `python minis.py autostart on\|off\|status` | macOS only: start at login with a LaunchAgent (written only when you run `on`) |
| `python minis.py size 64\|96\|128` | fighter height in px (default 128, HD art); running fighters restart to apply it |
| `python minis.py stream on\|off\|status` / `stream snapshot [png\|folder]` | streamer mode: an OBS-friendly window with the live fight ([docs/STREAMING.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/STREAMING.md)) |
| `python minis.py card [--out path] [--share]` | the 1200 x 675 stats card, then careers and head-to-head records |
| `python minis.py achievements` | every achievement, what it takes and how far you are |
| `python minis.py packs list\|install <zip\|folder>\|remove <name>\|check <folder>` | community skin packs ([docs/SKIN-PACKS.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/SKIN-PACKS.md)) |
| `python minis.py doctor [--headless]` | a report to paste to your AI agent or an issue; `--headless` skips the test window (CI) |
| `python minis.py director` / `run a\|b` | run the director or one slot in the foreground (debugging) |
| `python minis.py selftest-gui [--keep]` | real-desktop check: both windows draw over the taskbar and survive a taskbar raise (macOS: frames, no capture) |
| `python -m unittest discover -s tests` | the test suite (the process-level tests are skipped unless `MINIS_INTEGRATION=1`) |

### Right-click menu

Right-click a fighter or its plate:

- **Fighter (left/right side)**: *Auto*, then every program with its state; never-seen programs are greyed.
- **Look (program)**: *Default* and every character on disk.
- *Select fighters...* opens the select screen.
- Checkmarks: *Pause all animations*, *HUD plates*, *Flash effects*, *Rival mode*; **Who wins**: *Healthier program usually wins*
  / *Coin flip*.
- *Start a bout now*, *Start a match now (best of 3)*, *Arena mode*.
- *Hide this fighter*, *Hide for 1 hour*, *Quit Taskbar Fighters (stops everything)*.

## Configuration

Optional: a `minis.json` next to `minis.py` (in the Windows zip: next to `TaskbarFighters.exe`) overrides any default in
`minis_core/config.py`; a pip install runs on the defaults plus the CLI toggles. Runtime toggles (pause, plates,
flash, rival, winners, lineup) live in `%LOCALAPPDATA%\minis\control.json` and are set by the CLI and the menu.

```json
{
  "dormant_hours": 72,
  "sparring_bot": true,
  "ignore_sources": ["grok"],
  "rival_min": 8,
  "rival_max": 15,
  "proc_working_cpu_pct": 15,
  "arena_monitor": 2,
  "scoreboard_x": null
}
```

| key | default | meaning |
| --- | --- | --- |
| `zone` | detected | x range (logical px: screen px / sprite scale) of the stretch the fighters use. Windows finds the empty part of the taskbar itself; setting `zone` turns that off and always wins. `[40, 900]` is the fallback when detection fails |
| `zone_auto` | `true` | Windows: detect the zone from the taskbar's element rects (`false` = always use `zone`) |
| `monitor` | `null` | Windows: monitor index (`minis.py monitors`) whose taskbar the fighters use; default the primary. Other monitors' taskbars are ignored |
| `dormant_hours` | `24` | a program that went quiet keeps its slot (asleep, dimmed) this long |
| `sparring_bot` | `true` | one fighter alone: a generic sparring bot takes the other side |
| `ignore_sources` | `[]` | program ids (see `detect`) that never get a fighter |
| `rival_min` / `rival_max` | `8` / `15` | minutes between rival matches while the active program is not working |
| `rival_spar_min` / `rival_spar_max` | `3` / `6` | minutes between short rival exchanges while it is working |
| `match_min_s` / `match_max_s` | `180` / `360` | seconds between timed matches when both are awake |
| `proc_working_cpu_pct` | `15` | process sources count as working above this % of one core |
| `claude_window` | `1000000` | context window used for Claude's context % |
| `tray_icon` | `true` | the notification-area icon (left click: select, right click: menu) |
| `scoreboard` / `scoreboard_x` | `true` / `null` | show the widget; its screen x (default: just left of the icons) |
| `fighter_size` | `128` | taskbar fighter height: 64, 96 or 128 px (`minis.py size N` overrides it at runtime) |
| `arena_monitor` | `null` | monitor for the Arena button (default: the one non-primary monitor) |
| `arena` | `{}` | arena options: `rounds`, `endless`, `intensity`, `seconds`, `intro`, `outro` ([docs/ARENA.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/ARENA.md)) |
| `fps_active` / `fps_fight` / `fps_idle` | `10` / `60` / `4` | redraw rates (a fight script redraws at `fps_fight`) |
| `arena_fps` / `arena_cpu_budget_pct` | `60` / `10` | the arena starts at 60 fps and steps down to 30, then 20, while it costs more than the budget (% of one core) |

Where the fighters stand (Windows; `python minis.py doctor` prints the detected edge, DPI, layout and zone):

- **Taskbar at the bottom:** on the taskbar, in its empty stretch. The stretch is found from the RECTANGLES of the taskbar's
  buttons (UI Automation bounding rects of start, search, widgets, each app button, the tray; the shell's own child windows
  `Start` / `MSTaskListWClass` / `TrayNotifyWnd` as a fallback) - never a name or title. Centred icons (Windows 11): left of
  the icon cluster; left-aligned icons (Windows 10, or 11 set to left): between the icons and the tray. It is re-read every
  5 s, so the zone shrinks as the icon cluster grows (in 48 px steps, so not every new icon moves the fighters).
- **Taskbar at the top, left or right:** on a strip along the bottom of the work area next to the taskbar (48 px x the
  monitor's scale high, up to 900 px of roam). The fight engine and art are horizontal, so a vertical lane is not offered.
  The strip lies over the bottom of app windows; everything but the sprites, the names and the buttons is click-through.
- **Auto-hide taskbar at the bottom:** shown only while the taskbar is revealed (followed every 0.25 s), so nothing ever sits
  on the 2 px strip that brings it back. At the top or a side, the bottom strip is used and stays up.
- **DPI:** the process is per-monitor DPI aware (v2, with fallbacks), so every position is a physical pixel. Sprites, plates
  and the scoreboard are drawn at an integer scale that fits the taskbar band (1x at 100-175%, 2x at 200%): always crisp, never
  stretched. The tray icon is reloaded at the new small-icon size when the DPI changes.
- **Live changes:** a display change, a DPI change, the taskbar moving or resizing, and an Explorer restart (TaskbarCreated)
  re-lay everything out at once.

Fighters hide while a fullscreen app is up.

## Privacy and safety

- **Numbers only.** From Claude Code and Codex transcripts it reads token counts, timestamps and states - never prompt or reply
  text, window titles, file names or project names. Nothing it reads is logged, stored or sent; logs carry exception types and
  `file:line` of this program only.
- **No network.** No network access of any kind.
- **Your tools untouched.** No settings, hooks, status lines or config files of your AI tools are edited.
- **Stops only itself.** `stop` ends only processes whose exact command line it can prove are its own; the director restarts a
  dead slot only after the same proof, at most three times in ten minutes.
- **Screen capture only in the arena, only in memory.** An arena grabs its monitor ONCE into RAM to forge desktop weapons (and
  for the optional `--freeze` backdrop). It is never written to disk, logs, temp files, `arena.json` or `arena capture`, and is
  dropped when the arena closes. `python minis.py forge off` (or the menu's *Desktop weapons*) turns it off. The taskbar
  fighters never read the screen.
- **Arena never touches real windows.** It reads window rectangles (`EnumWindows` / `GetWindowRect`), never titles, never sends
  input; cracks and shatters are paint on its own overlay.
- **Files written:** `%LOCALAPPDATA%\minis\` on Windows, `~/Library/Application Support/minis/` on macOS (bus files,
  `assign.json`, `control.json`, `record.json`, `history.json`, `seen.json`, `achievements.json`, `stream.json`, pid and
  lock files, small rotating logs, `packs/` for skin packs you install, and `exports/` for the stats card and stream
  snapshots).
- **Exports stay in the data folder unless you name a place.** `card` and `stream snapshot` write to `exports/` inside the
  data folder. With `--out` (card) or a path (snapshot) you can name an existing folder, or a `.png` file in an existing
  folder; anything else is refused, no folder is created outside the data folder, and nothing is ever written to
  Pictures, the Desktop or your home folder on its own. *Share my stats card…* writes to `exports/` and opens it.

## How it works

![Detection diagram: programs feed transcript and process sources plus a memory of recently seen programs; the director picks two and writes assign.json; slots a and b talk through bus files](https://raw.githubusercontent.com/mrktchris/taskbar-fighters/master/docs/img/detection.png)

- **Sources** (`minis_core/sources.py`) poll every 2 s: Claude Code and Codex from the newest local transcript (only appended bytes,
  numbers and enums), every other program from a table matched against the process list through ctypes, *working* above 15% of one
  core.
- **Director** (`minis_core/director.py`) picks at most two by recency and keeps them stable; a quiet program stays as a dormant
  partner, else the sparring bot fills in; your lineup overrides a side. It writes `assign.json` and hosts the scoreboard.
- **Fighter slots** (`minis.py run a|b`, `minis_core/brain.py`) each draw a per-pixel-alpha layered window over the taskbar and talk
  through one small JSON bus file each. Both compute the same bout timeline from the same seed, so a hit and the other fighter's
  reaction land on the same frame without a round trip.
- **Choreography** (`minis_core/choreo.py`, `rounds.py`) is a pure function of a seed and the two move sets: a no-repeat move picker,
  openers, combos, defence, specials, a super meter and one ultimate per match. The same planner drives the taskbar, the arena and
  the headless simulator used for tests and these images.
- **Art** (`art/`) is generated: a 2-bone rig and pose data build `assets/` (64 px) and `assets_hd/` (128 px) with
  `python art/build_fighters.py --all`.
- **Set pieces** (`minis_core/setpieces.py`, `arena_setpieces.py`) are hand-authored beat lists for both fighters, written
  against weapon-family slots and played by the same round player as the procedural exchanges.

```
minis.py          CLI, director loop, fighter loop        art/      rig, moves, roster, builder -> assets/, assets_hd/
minis_core/       sources, director, telemetry, brain,    tools/    previews, doc images, MOVELIST generator, captures
                  choreo, rounds, fx, arena, scoreboard,  tests/    unittest; synthetic, content-free fixtures
                  select, lineup, render, sim, config     docs/     notes, credits, work orders, docs/img/
minis_win/        layered windows, arena window, process table (all ctypes)
minis_mac/        macOS: NSPanel windows, menu-bar item, Dock geometry, ps process table, LaunchAgent (experimental)
taskbar_fighters_assets/   where the wheel installs assets/ and assets_hd/ (minis_core/paths.py finds the art in every install)
minis_platform/   picks minis_win or minis_mac at run time (nothing imports a desktop library at import time)
```

## Known limits and roadmap

- **Windows tested; macOS experimental** (CI-tested, few real Macs so far: [docs/MAC-TESTING.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/MAC-TESTING.md)).
- Windows layouts seen on a real PC: 100% DPI, bottom taskbar, centred icons, on the primary monitor and (with `monitor`) a
  second monitor's taskbar. 125-200% DPI, top / left / right and auto-hide taskbars, left-aligned icons, Windows 10 and an
  Explorer restart are unit-tested over synthetic rect sets, not yet seen on a real desktop (RESULT.md has the matrix).
- At fractional scales (125%, 150%, 175%) sprites stay at 1x so they are crisp: they look smaller than at 100% (use `size 128`).
- A taskbar too full to hold the plates, a bout and the scoreboard (a 1024 px screen, 1920x1080 at 200% with many icons) gets a
  narrow zone in its gap: nobody walks on an icon, but the plates and the scoreboard overlap; `plates off`, `"scoreboard":
  false` or `size 64` help, or set `zone`. With no free stretch at all the fighters hide, and `status` / `doctor` say "no free
  taskbar space". The default zone `[40, 900]` is used only when the taskbar's buttons cannot be read at all.
- Top, left and right taskbars use a strip at the bottom of the screen, over app windows (no vertical lane).
- At the default 128 px a fighter stands well above the 48 px taskbar, over the bottom of the desktop (its window is
  click-through except the sprite); `size 64` keeps it to about 11 px above the taskbar's top edge. Long weapons tilt to fit
  the cell.
- On macOS, desktop weapons from real pixels (after you grant Screen Recording yourself), the weapon held frame by frame,
  and the taller jump windows, scaled fight zone and lock-on are CI-tested but not yet fully checked on a real Mac
  ([docs/MAC-HANDOFF.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/MAC-HANDOFF.md) MAC-13, 17, 18, 20, 21).
- The arena gets the task-finished super through the bus files (V9). Its frames cost 2.5-3.5 ms headless at 1920x1080 and
  2560x1440 ([docs/ARENA.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/ARENA.md#performance)); the only
  frames still over 33 ms are a few full-screen finisher frames (focus lines over the whole monitor). Platforms are only the
  top edges of windows.
- Process sources have no numbers, and "working" is a CPU heuristic (the 15% threshold is a first guess).
- The art is generated by a rig, not hand-drawn. Every frame gets a pixel clean-up pass, and the most-seen frames a reviewed
  hand-polish pass through the hook (`art/hand/<character>/<move>_<frame>[@2x][_l].png`, `art/hand_polish.py`).
- Ideas not built yet: landing on title bars in the arena; importing Codex pets (their format is not documented offline:
  [docs/SKIN-PACKS.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/SKIN-PACKS.md#codex-pets)); instant replay from the stored match seeds.
- Streamer mode's `--transparent` has not been checked in OBS (the chroma key is the dependable path), and the new
  programs' process names are from vendor docs, not yet seen running (except the Claude desktop app).

Build logs with what was verified and how: [RESULT.md](https://github.com/mrktchris/taskbar-fighters/blob/master/RESULT.md). Version history: [CHANGELOG.md](https://github.com/mrktchris/taskbar-fighters/blob/master/CHANGELOG.md).

## Make the images yourself

`python tools/doc_images.py` renders every image in `docs/img/` offline (no screen capture; the data folder is redirected to a temp
dir). `python tools/ui_previews.py`, `python art/qa_v6.py lineup|sheet <character>` and `python tools/make_previews.py` render the
QA sheets. `python tools/taskbar_capture.py --out <dir> --demo match` captures only the taskbar rows of the fighter zone of a live
bout, and `python tools/doc_images.py --annotate-live <dir>` annotates it.

## Credits

All thirteen fighters, every frame, effect and projectile are original art generated by the rig in `art/`. Free packs by LuizMelo
(Martial Hero), Mattz Art / xzany (Samurai) and GandalfHardcore (Archer) were studied for timing, proportion and silhouette
only; nothing was copied. Links and licence terms:
[docs/CREDITS.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/CREDITS.md). How it compares with other desktop pets and agent monitors:
[docs/COMPARISON.md](https://github.com/mrktchris/taskbar-fighters/blob/master/docs/COMPARISON.md).

## License

[MIT](https://github.com/mrktchris/taskbar-fighters/blob/master/LICENSE), copyright 2026 Christian Sierra.
