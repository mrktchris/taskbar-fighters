# Changelog

Taskbar Fighters (internal short name: minis). Summarised from the git history and the build logs in [RESULT.md](RESULT.md).

## Unreleased (V9 - fight quality)

- **Platform-fighter frame data** (`minis_core/framedata.py`): hitlag that freezes both fighters by damage, a damage % per
  round (on the plate during a match, under the HP bars in the arena), knockback from damage, % and weight, hitstun from
  knockback, tumbles along a real arc with one bounce and a tech or a missed tech, shieldstun and pushback, DI. Taskbar
  fights redraw at 60 fps; the arena tries 60 and steps down under its CPU budget.
- **No pops**: heavy blades planted (not flipped up and back) on the spike landing; one-shots end on the idle stance; recovery
  keys in-betweened along the shortest arc; continuity-aware weapon fitting; still weapons while sleeping; real `air` lift
  for the high-five, the grapple ultimate, the jumping victories, the launcher and the idle flourish. Weapon flips over the
  roster 300 -> 45, cell hops 19 -> 0 (`art/qa_fight.py audit`).
- **Clean pixels**: every built frame drops stray single pixels and doubled outline corners; a reviewed hand-polish pass
  (`art/hand_polish.py`) on the idle loops, signature strike contacts and KO poses at 64 and 128 px in both facings
  (`art/hand/`, now tracked; the builder reads `@2x` and `_l` files). Real outlines are told from a dark boot by the rig's
  part buffer, and the neighbour counts are exact sums (a convolution kernel rounded differently on macOS CI's Pillow 13).
- **Arena fix**: in freeze mode the shattered window's hole was repainted one row and one column short (the jagged edge
  lands on the window's last row); found by the new lockstep compositor test.
- **Arena 30 fps work**: sprites trimmed to their opaque pixels, a near-linear dirty-rect merge (a 33 ms worst case -> under
  1 ms), flash frames as a window fill plus the drawables, the forge's unarmed sheets decoded before the first frame (a 130 ms
  stall), letterbox bars marked on the image instead of by id; pixel-identical to v1.0.0 or closer to the full recomposition
  (`tests/test_arena_perf.py`).
- **Arena task-finished boost**: a slot whose agent finishes a task publishes a short-lived marker on its bus file; a running
  arena opens the next exchange with that fighter's signature super.
- **Optional sound effects, off by default**: `python minis.py sound on|off`, a menu checkmark, eight original sounds generated
  by `art/build_sfx.py`; winsound on Windows, NSSound on macOS; one process plays, rate-limited, quiet when paused or hidden.

## v1.0.0 - 2026-10-16 (V6 -> V8)

The first tagged release: a one-click Windows zip, a wheel on PyPI (`pip install taskbar-fighters`) and an experimental,
CI-verified macOS port (`pip install "taskbar-fighters[mac]"` or `scripts/setup_mac.sh`). Everything since V6 below; V8 and
V7.1 first.

### V8 - desktop weapons (arena)

- **Weapons forged from real screen pixels** (`minis_core/forge.py`). The arena grabs its monitor ONCE into RAM at start;
  a fighter reaches for a window, a glowing outline cuts a piece out, a jagged dark hole is painted where it was, the piece
  lifts, pixel-shatters in an 8-frame morph and re-forms as that fighter's weapon family (blade, greatsword, axe, spear,
  club, twin blades, shards). It swings with a smear, cracks with every hit and shatters into pixel debris; slabs get thrown
  and pieces knocked off windows can be picked up. 2-4 a match at `normal`, 1 at `calm`, 5-7 at `wild`, plus one inside the
  `stance_finisher` set piece.
- **Held in the hand.** The weapon sits at every drawn frame's grip point (anim.json `grip` / `grip2`, unarmed sheets for
  the forging fighter), so it swings with the arm frame by frame.
- **Privacy.** The grab is never written to disk, a log, a temp file or `arena.json`; `ScreenImage` refuses pickling;
  `arena capture` refuses while pixels are held; `python minis.py forge on|off` and a **Desktop weapons** item in the tray
  and fighter menus (a running arena drops the grab within 2 s). Without pixels, weapons are forged from window shapes.
  `tests/test_forge.py` includes a no-sink privacy test over a real `run_arena`.
- **macOS.** Real pixels only when Screen Recording is already granted (`CGPreflightScreenCaptureAccess`, never requested;
  `doctor` explains how), shape fallback otherwise; arena window CPU work (128-pt tiles, transparent tiles skipped, a GPU
  tint layer for flashes); a badge left of the notch when macOS hides the menu-bar icon.

### V7.1 - lock-on, real jumps, HUD clearance

- **Lock-on.** Fighters always face and aim at each other: facing follows the shared timeline instead of the partner's
  0.2 s-old bus copy, so a dash-through no longer leaves one facing away; strikes land from inside their reach (the strike
  step-in was a 60 s slide) and both processes stay on the shared plan. Seeded audit: facing away 237 -> 0 frames,
  out-of-reach contacts 201 -> 0.
- **Jumps rebuilt** for all 13 fighters: crouch, rise, apex hang, landing, an 8-frame row (neutral jump 600 -> 930 ms),
  drawn by the engine at 30 fps with jump headroom above the window's cell.
- **HUD clearance at 128 px.** Plate and scoreboard clearances scale with `fighter_size`; frames reaching over a plate or
  the scoreboard 91 / 100 / 361 -> 0 at 64 / 96 / 128 px. The doc render's clip band follows the zone.
- **Fixes.** Confirming a fighter pick no longer silently stops the director; a never-drawn window answers a dump request
  as hidden.
- **Own-window capture** (`tools/own_capture.py`): the running processes dump their own frames on request, so the README's
  live images show whole 128 px fighters, plates and the scoreboard without any screen capture.
- **Launch media** rebuilt (`packaging/launch_media.py`): the social card from the 128 px art, and an 8 s loop of a taskbar
  K.O. followed by an arena forge, both on a synthetic desktop.

### V7 - weapon families, set pieces, arena V7, macOS, packaging

- **Every fighter fights like its weapon (V7 art).** Weapon move families (blade, dual, polearm, staff, chain, bow,
  fans / chakram, heavy): 8-10 new attack moves per character, plus shared air slash, spike, throw, dash-through, guard
  break and a taunt variant, and new reactions (`launched`, `air_hit`, `spiked`, `thrown`, `pulled`, `guard_crush`,
  `hit_high`, `hit_low`, `hit_back`, `clash`). Contact sparks per hit kind (slash, blunt, pierce, deflect), directional
  light-hit reactions, weapon locks. 128 px detail pass: faces with eyes, brows and expressions, knuckles, elbow and knee
  creases. The 64 px rows of V3-V6 are byte-identical. MOVELIST.md and `docs/img/moves-<character>.png` cover all 13.
- **Choreography by move type.** Throws on a shared clock, launch-juggle-spike chains, chain pulls, dash-throughs that swap
  sides, boomerang projectiles, 3-hit strings that cancel on the contact frame, armoured heavies.
- **Cinematic set pieces.** Eight hand-authored joint exchanges (`minis_core/setpieces.py`: blade lock, pull and launch,
  cross-cut freeze, vault overhead, parry riposte, guard crush, reversal, aerial finish), written against weapon-family
  slots so any pairing plays them, one to three per match at its dramatic moments; `tools/setpiece_preview.py`.
- **Arena V7** (`docs/ARENA.md`). Options `rounds` 1/3/5 or endless, `intensity` calm/normal/wild, `seconds`, `intro`,
  `outro`, from `minis.json` `"arena"`, `control.json` `"arena_opts"` or the new CLI flags
  `arena --rounds 1|3|5|endless --endless --intensity calm|normal|wild --seconds S --no-intro --no-outro`. A VS card intro
  and a winner's perch on the highest window; wall bounces, techs, ledge grabs, knock-throughs, skids, craters, shard
  platforms; double jumps, air dashes, juggles, meteor spikes; letterbox, a seamless zoom punch, speed lines, a slow-motion
  final KO; beam clashes; sword set pieces with elemental trails (`minis_core/arena_setpieces.py`). Cheaper per frame than
  V6 (dirty-drawable compositor). Still visual only, proven by `VisualOnly7`.

- **macOS backend (experimental, CI-tested).** `minis_platform` picks `minis_win` (unchanged) or the new
  `minis_mac` (PyObjC AppKit + Quartz): borderless non-activating panels above the Dock, click-through except opaque pixels,
  a menu-bar status item with the tray menu, Dock-strip geometry (bottom Dock; side or auto-hiding Dock falls back to the
  bottom of the visible frame), Retina-aware monitors, window bounds from the Quartz window list (never names, no Screen
  Recording), a `/bin/ps` process table, lock-file single instance, SIGTERM-then-SIGKILL `stop` for proven-own pids only,
  `~/Library/Application Support/minis`. `autostart on|off|status` (LaunchAgent, only on request), `scripts/setup_mac.sh`,
  `requirements-mac.txt`, `docs/MAC-TESTING.md`. No arena `--freeze` / `arena capture` on macOS.
- **Fighter size.** `fighter_size` 64 / 96 / 128 (default 128): 128 draws the real HD art, 96 is the HD render reduced with a
  box filter; the brain keeps working in RES 1 px inside the scaled zone, so spacing and reach keep their proportions.
  `python minis.py size N` and a *Fighter size* submenu (both restart the fighters).
- **`python minis.py doctor [--headless]`**: versions, backend, screen and taskbar / Dock geometry, data folder, detected
  programs and a test window, ending in PASS / FAIL; the home folder is shown as `~`.

- **Packaging.** `minis_core/paths.py` finds the art and `minis.json` in a checkout, a PyInstaller bundle, a py2app bundle
  or a wheel install. The wheel ships the art inside the package `taskbar_fighters_assets` (never as top-level
  `site-packages/assets`), `taskbar-fighters` console script, `mac` extra with the PyObjC pins (`sys_platform == "darwin"`).
  Frozen builds re-launch themselves (`self_argv`) and their ownership checks accept that form; `--help` names the program
  the way it was started. CI installs the built wheel and reads the 13 characters from the installed copy; the release job
  smoke-tests the exe with `doctor --headless` and `fighters`.
- **macOS from the first real-Mac runs.** Panels above the Dock, PT Sans plate text, Retina-sharp opaque plates and
  scoreboard that fade under the mouse, the scoreboard at the right end of the strip, `status` reports a menu-bar icon
  hidden behind the notch, `selftest-gui` uses the configured fighter size, a faulthandler log per process
  (`<data>/<role>.fault`) for silent native crashes.
- **Docs.** README top block (demo loop, download buttons, install box for the zip, pip and your AI agent), arena, macOS,
  moves and set-piece sections; every image regenerated from the V7 art (`tools/doc_images.py`, the offline taskbar strip now
  at 128 px); `docs/MAC-HANDOFF.md` for the Mac session; no franchise names anywhere.

## V6 - 2026-10-15 (`744d818`)

- **Armed roster.** The seven program fighters redrawn as taller (~4.5 heads), armed characters: ronin (Claude), ninja (Codex),
  twin-blade dancer (Gemini), lancer (Cursor), monk-brute (Ollama), white cyber samurai (LM Studio), archer-ranger (Agent). Six
  selectable extras: Kunoichi, Knight, Barbarian, Monk, Nomad, Oni. Real HD (1 px outline, 5 tones), weapon crescents and streak
  smears, longer wind-ups and holds, impact frames transparent outside the figure.
- **Fighter select.** `control.json` lineup (program per side, look per program), `minis.py fighters set|pin|auto|reset`, `pick`,
  `skin`, right-click submenus and an arcade-style select screen (WHO row, LOOK grid, VS card).
- **Fight feel.** 30 fps during fights, knockdown get-up fix, a 3.4 s KO finisher beat (was 6 s), ultimates 1.7 -> 0.3 per match,
  spacing from sprite reach, brace on charge-ups, TIME banner, comebacks, task-finished super. Arena: same rules, pacing fixed (KO
  rounds 52% -> 85%).
- **UX and safety.** Readable scoreboard with a result line and per-program records, undoable hide, *Quit minis*, `flash on|off`,
  `start` reports what is on screen; `arena capture` refuses `--freeze` and writes only under `qa/` or the data folder;
  non-blocking `arena stop`, absolute-argv ownership check, director watchdog, config errors logged, fps clamped.
- **Tray, shortcut and icon (2026-10-15).** App icon (`assets/icon/`, `art/build_icon.py`), a notification-area icon (left click:
  select; right click: menu with Restart / Quit), `minis.py shortcut [--desktop] | shortcut remove`, `minis.py restart`,
  `tray_icon` setting; user-visible name Taskbar Fighters in menus and tooltips.
- **Docs (2026-10-15).** Renamed to Taskbar Fighters; README rewritten with fresh annotated images from `tools/doc_images.py`;
  AGENTS.md install runbook, CLAUDE.md, llms.txt, requirements.txt, this changelog.

## V5.1 - 2026-10-14 (`ef6dec7` .. `66d08d7`)

- Character redesign (silhouette feature, accent colour, HD rim light per character) and a beam FX overhaul (`grow`, `flash`).
- **Dormant partner:** a program that went quiet keeps its slot asleep for 24 h; **sparring bot** fills an empty side;
  **rival mode** wakes a sleeping partner for a match every 8-15 min.
- `minis.py detect`; four more programs (Copilot CLI, Qwen Code, Perplexity, Grok); `ignore_sources`.
- Animation notes from two fight-animation studies (impact frames, holds, travel, streak smears); tests can no longer launch a real
  arena.

## V5 - 2026-10-14 (`bf5d090`)

- **Choreography:** a seeded no-repeat move picker (`minis_core/choreo.py`), openers, combos, defence, spacing, specials, a super
  meter and one ultimate per match; the same planner drives the taskbar, the arena and the simulator.
- **Beam playback:** beams extend from the hands, hitstop freezes both fighters on contact, an ultimate landing flashes the frame.

## V4 - 2026-10-13 (`886f116`)

- Best-of-3 **matches** with HP, banners, effects and one ultimate per character; `winners decided|random`; `record.json`.
- **HD** sheets (128 px), effects library with procedural stand-ins.
- **Scoreboard widget** with W-L, HP bars, a 7-day context sparkline and three buttons.
- **Arena mode:** a full-monitor click-through overlay with window-ledge platforms, cracks, shatter, letters and explosions; the
  optional `--freeze` backdrop stays in RAM.
- Reset countdown on the plate, loud `waiting?`, pupils that follow the cursor, dizzy after a fast drag, Shift-drag throw.
- First public commit, with build logs, move list, comparison, credits and an MIT licence (`ce9ac6e`, `d416fc9`).

## V3 / V3.1 - 2026-10-13

- **Any AI program, two slots:** a director plus fighter slots `a` and `b`; Claude Code and Codex from transcripts, other programs
  from the process table; bouts start from usage (clash, spar, ranged duel, handoff, KO + console); `pause` / `resume`.
- V3.1: fighters walk back to their own half, plates fixed at the left end of the zone, any awake pair interacts, `demo`, `plates
  on|off`.

## V1 / V2 - 2026-10-12

- Two rig-generated pixel fighters, Claude and Codex, on the Windows taskbar: 48 moves each, per-pixel-alpha windows, HUD plate with
  real context %, spar / ranged duel / handoff / console from telemetry, pid-checked `stop`, a headless simulator for tests and
  previews.
