# Changelog

Taskbar Fighters (internal short name: minis). Summarised from the git history and the build logs in [RESULT.md](RESULT.md).

## Unreleased (V9 - fight quality)

- **Fighters learn** (`minis_core/learning.py`, `art/evolve.py`, [docs/LEARNING.md](docs/LEARNING.md)): each program's fighter
  teaches itself new moves - mastery (an evolved variant of a move it throws often), counters (against the hit kind that
  keeps landing on it), mimicry (a crude borrowed copy of an opponent's move in its own weapon family) and inventions
  (variations tried out while it shadowboxes). New moves are generated from the pose keyframes by deterministic operators
  (retime, twin, feint, amplify, spin, mimic), gated by the art QA (anchors, the weapon in hand, silhouette, novelty,
  reach, colour caps, both facings, 64 + 128 px), shown once under a `LEARNED: <MOVE>` banner and then used in fights.
  Kits cap at six, grow one move per 15 bouts at most, decay and forget unused moves; both slot processes agree through
  the shared plan. `learning.json` holds ids, counters and seeds only; `python minis.py learned [program]` lists it all.
  Checkout installs only for now.
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

## Unreleased - growth

- **Streamer mode** (`python minis.py stream on|off|status|snapshot`, tray *Streamer mode (OBS window)*): a normal,
  resizable, non-topmost window "Taskbar Fighters — Stream" with the live fight strip (fighters, plates, scoreboard) on a
  chroma-key background (default `#00FF00`, `--chroma`), whole-number scaling, `--no-plates`, experimental `--transparent`.
  Built from the processes' own window images through the existing self-dump (`minis_core/dump.py`), never a screen
  capture; desktop weapons are switched off while streaming. `minis_core/stream.py`, `minis_win/stream_window.py`,
  `minis_mac/stream_window.py` (experimental), [docs/STREAMING.md](docs/STREAMING.md), `tools/stream_preview.py`.
- **Stats card** (`python minis.py card [--out] [--share]`, menus *Share my stats card…*; written to
  `<data folder>/exports/` unless you name an existing folder or a `.png` in one): a 1200 x 675 PNG with each
  program's sprite, rank, W-L, win %, streak, favourite move and head-to-head, an identity line ("Your main: CLAUDE ·
  34-29 vs Codex"), and every achievement badge. `minis_core/stats_card.py`, `tools/card_preview.py`.
- **Careers, head-to-head and ranks**: lifetime per-program totals and per-pair records in `record.json`
  (`totals`, `h2h`), ranks by lifetime wins that never demote; `minis.py card` prints them.
- **Achievements** (`python minis.py achievements`): 22 Fight / Discovery / Partnership badges with open criteria and
  progress, none for token use, hours or time of day; persisted in `achievements.json`, a 3 s toast on the scoreboard.
  `minis_core/achievements.py` (a documented public API for the UX layer).
- **Match log with replay plans**: `record.json` keeps the last 500 matches (`log`) with KO / flawless / comeback /
  ultimate / set-piece facts and the match's seed and lineup (`replay`), enough for `rounds.make_match` to rebuild the
  same fight (tested).
- **More AI programs detected**: Claude desktop (its own program now; `Claude.app` is no longer claimed for Claude Code),
  ChatGPT desktop, Zed, Junie, Continue CLI, Cline CLI, Amazon Q Developer CLI (macOS), Crush, Goose, Jan; VS Code's
  extension host is never mistaken for Cline / Continue / Roo. `detect` says when a program has no process name on this OS.
- **Community skin packs** (`python minis.py packs list|install|remove|check`): a documented, data-only format
  (`pack.json` + 64 / 128 px sheets), strict validation and safe zip install, shown in fighter select as `pack-<name>`;
  `tools/make_example_pack.py`. [docs/SKIN-PACKS.md](docs/SKIN-PACKS.md). Codex pet import is documented as future work
  (its format is not knowable offline).

- **Review fixes (Codex review of `growth`).** Exports (card, stream snapshot) default to `<data folder>/exports/` and
  only go elsewhere to an existing folder or `.png` path you name; `stream on` takes an O_EXCL `stream.lock` before it
  spawns, so two quick starts open one stream, and a stream only ever closes out its own state; pack PNGs are capped by
  their header size before decoding (per sheet and 256 MiB per pack); malformed pack metadata is always a plain refusal;
  `tools/make_example_pack.py` validates `--name` before touching any folder; the Win32 stream window passes an owned
  pixel buffer and is tested by reading back its own pixels. Second review: a stale `stream.lock` is reclaimed under a
  guard so two starters never both take it; `stream off` reaches a stream still opening its window; `--scale`,
  `--width`, `--height` are capped (8 / 4096) and a frame never exceeds 4096 x 2304; `packs.FIGHTER_ID_RE` is the
  fighter-id contract for fight codes (pack names may contain hyphens).

## Unreleased - Windows on strangers' PCs (branch `win-robust`)

## Unreleased - UX layer (branch `ux`)

### UX layer - getting around (branch `ux`)

Built from a survey of desktop companions and fighting games ([docs/RESEARCH-UX.md](docs/RESEARCH-UX.md)), keeping to its
"do not do" list: no popups that take focus, no network, no new capture, no guilt or streak pressure.

- **Settings window** (tray > *Settings...*, `minis.py settings`): a pixel-art window of its own with fighter size, plates,
  flash effects, desktop weapons (default unchanged: real pixels; its help line is amber while on), rival mode, who wins,
  the results strip, hover cards, event signals, **Start with Windows** (one `Taskbar Fighters.lnk` in shell:startup,
  an existing one for this copy reused, one for another copy left alone) / **Open at login** (the macOS LaunchAgent), and a
  **drag-to-set fight zone** over the taskbar (Save / Reset to auto; written to the data folder's own `minis.json`, which
  overrides the hand-written one; the fighters restart). Every row is a command too: `settings list|set`, `startup`, `zone`,
  `results|cards|signals on|off`. The app writes only under its data folder, or to a path you choose (plus the startup entry
  you turn on yourself).
- **The UI has its own pixel font** (`minis_core/pixelfont.py`, generated in code: cap height 7, proportional, regular /
  bold / tall variants for 8-12 px). FreeType's monochrome hinting of the OS fonts tore 9-10 px words apart ("m inis",
  "C laude") and macOS drew them with other fonts again; now every small-text surface (plates, scoreboard, select screen and
  every new window) renders pixel for pixel the same on Windows, macOS and in the frozen bundle, with no OS font involved.
  OS fonts remain only for the large banners and the arena HUD. No help line, caption or toast is cut with "..." any more:
  they wrap.
- **First-run guide + legend**: three cards pointing at the real fighter, plates and scoreboard, once (ux.json); tray >
  *What am I looking at?* / `minis.py guide` shows a 10-second legend.
- **Hover cards**: rest the mouse on a fighter or plate for the program, its state in words with how long, context, plan,
  record and head-to-head against the current opponent. Click-through, no focus, no content.
- **Event signals**: done flag until hovered; needs-you amber halo pulse and a wave; SECOND WIND on a context compaction with
  the plate meter refilling; DANGER near the limit and FINISH! with the K.O.  Paused / quiet / flash-off keep them still.
- **Results moment**: a 4-second strip over the scoreboard ("CODEX WINS 2-1 · 21 hits · best combo 5 · ultimate landed"),
  the winner poses and the loser bows on the taskbar.
- **Rival countdown** on a sleeping plate ("rival match in ~6 min") and in its hover card.
- **Instant replay, GIF export and fight codes**: tray > *Replay last K.O.* plays the deciding exchange (K.O. in slow motion)
  in a window above the taskbar; *Save last fight as GIF* writes the whole match to `<data folder>\exports` and opens that folder with the file
  selected (`replay --gif PATH` writes where you say); both are
  offline renders from the stored plan (`replay.json`, numbers and ids only). `minis.py replay code` prints a short code
  (`TF2-claude-codex-...`: seed, characters, positions, odds as a ratio, outcome check) that `minis.py replay CODE` plays.
  Fighter ids in a code are checked against an allowlist (`pack-shadow-ronin` style ids round-trip, a hyphen written as a
  dot), GIF file names are built from sanitized ids and the default output is refused unless it resolves under `exports`.
- `ux.json`, `collection.json` and the data folder's `minis.json` are written under a small lock file (`filelock.py`): the
  CLI, the director and both fighter processes share them, and two read-modify-writes no longer drop each other's change.
- **Move book** (tray > *Move book...*, `minis.py book`): every move, set piece and finisher per fighter, seen ones animated,
  unseen as silhouettes; seen move ids in `collection.json`.
- Tray menu gains Settings..., Move book..., What am I looking at?, Replay last K.O., Save last fight as GIF.
- New modules: `minis_core/{ux,ux_runtime,ux_cli,settings_ui,guide,hovercard,signals,results,replay,collection}.py`,
  `minis_win/{ux_window,settings_window,book_window,guide_window,replay_window,startup}.py`, `minis_mac/startup.py`;
  `tools/ux_previews.py` renders every new window offline; `tests/test_ux.py`.
- macOS: the same windows through the NSPanel overlay; PgUp/PgDn/Home keys mapped for the book; real-Mac checks are
  MAC-30 to MAC-37 in docs/MAC-HANDOFF.md.

### Windows on strangers' PCs (branch `win-robust`)

- **Any taskbar edge.** Bottom: on the taskbar as before. Top / left / right: a strip along the bottom of the work area
  beside the taskbar. Auto-hide at the bottom: shown only while the taskbar is revealed (never over its 2 px reveal strip).
- **The zone finds itself.** The empty stretch of the taskbar is detected from the RECTS of its elements (UI Automation
  bounding rects, the shell's `Start` / `MSTaskListWClass` / `TrayNotifyWnd` windows as a fallback; no names or titles),
  for centred and left-aligned icons, Windows 10 and 11, re-read every 5 s. A `zone` in `minis.json` still wins
  (`zone_auto`); `monitor` picks another monitor's taskbar.
- **DPI.** Per-monitor v2 awareness with fallbacks (reported by `doctor`); integer sprite / HUD scale from the band at every
  DPI; the tray icon reloads at the new size on a DPI change; `monitors` and `doctor` show each monitor's scale.
- **Live re-layout** on a display change, DPI change, work-area change and an Explorer restart (TaskbarCreated).
- `doctor` prints the detected edge, DPI, layout and zone.

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
