> **STATUS 2026-10-13: superseded in part by V3** (`docs/V3-WORKORDER.md`). Fighters are now slots `a` / `b` assigned by a director to whatever AI
> program is in use (7-character roster), bouts start from usage, and animations can be paused. Current truth: `README.md`, `RESULT.md` (V3 section),
> `MOVELIST.md`. Where this brief differs, the code wins: the default zone is `[40, 900]` (`minis_core/config.py`), not `[16, 930]`; the Claude plan feed
> is only *read* by minis, never written; the fighter that finishes a task *gives* the diff in a handoff.
> 2026-10-12: v2 executed by Claude as failover (the Codex CLI rejected its model). This brief is kept as the design record.

# BRIEF v2 - Claude & Codex pixel fighters on the taskbar

Written by Claude (creative lead / reviewer), 2026-10-12. Writer: Codex. One writer in this folder: you.
House rules: plain words, never invent a number, never print or touch secrets, draft-only (nothing is sent, posted, uploaded or spent).

## What changed since v1

v1 never ran (the headless CLI rejected the model name before doing any work). The author then sent three pixel-art references and called the minis
**"our fighters"**. So: native pixel-art fighters (not the recolored cartoon kid), a sparring interaction, and the % drawn as a fighting-game bar.
The earlier recolour-a-Codex-pet sprite-sheet route is **dropped**. Do not read, copy or modify that pet sheet; it is the author's own Codex pet.

## Goal

Two small pixel-art fighters live in the empty part of the Windows taskbar.

1. **Claude fighter** - caps worn *reversed* (the pun), `/` sigil on the cap. His HUD plate reads `/reverse`.
2. **Codex fighter** - same reversed cap, `$` sigil. His HUD plate reads `$reverse`.
   (Claude invokes skills with `/`, Codex with `$`; both point at the `reverse-engineer-anything` skill. The sigil is one 5x7 px glyph so it stays legible
   at 40 px. The full word lives on the plate.)
3. **Two separate windows in two separate processes.** Close or crash one, the other keeps going.
4. They **spar**: friendly, pulled punches, bow, fist-bump. They react to each other's real state.
5. Each shows a **% bar** (HUD) built only from numbers that really exist (see "What the % is").

## Verified facts - do not re-derive, do not re-verify against real files

- The author's primary display: 2560x1440 at 100% DPI. Taskbar at the bottom: rect (0,1392)-(2560,1440), 48 px high; `SHAppBarMessage(ABM_GETTASKBARPOS)` returns it (edge 3 = bottom).
  A second 1920x1080 display sits at x=2560. Primary only for v1.
- Windows 11 centers the taskbar icons. Cluster is about x 955-1605; tray starts about x 2290. Empty stretches: **left 0-940** and **middle-right 1615-2285**.
  Default roam zone = left stretch `[16, 930]`, split at the midpoint: Claude home half left, Codex home half right. Put it in `minis.json`. Never walk over the icon cluster.
- **Feasibility is proven**: `reference/taskbar_spike.py` + `reference/spike-composite.png`. Two per-pixel-alpha layered windows
  (`WS_EX_LAYERED|TOPMOST|TOOLWINDOW|NOACTIVATE`, `UpdateLayeredWindow`, premultiplied BGRA) draw over the taskbar with soft alpha edges.
  When the taskbar re-raises itself (any click on it) both windows disappear. Re-calling `SetWindowPos(HWND_TOPMOST, NOMOVE|NOSIZE|NOACTIVATE)` brings them back.
  **Product requirement: keep-on-top tick every <= 250 ms.**

### Telemetry shapes (real key names, synthetic values, in `tests/fixtures/`)

Use **only the fixtures**. Do not open any real transcript, rollout, `.claude.json`, `auth.json` or credential file at any point - the real ones contain client work
and must not be sent to a model. The shipped program reads the real files at runtime on the author's PC; that is fine because it is local code that keeps numbers and enums only.

- **Claude** `~\.claude\projects\<project>\<session>.jsonl`, one JSON object per line. Top-level `type` seen: `user`, `assistant`, `queue-operation`, `attachment`,
  `last-prompt`, `custom-title`, `file-history-snapshot`, `file-history-delta`, `agent-name`, `atis-latch`.
  `assistant` lines carry `message.stop_reason` and `message.usage` `{input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens}`.
  `stop_reason` is `tool_use` while the model is mid-turn and `end_turn` when the turn is finished (both observed).
  Context tokens now = `input + cache_creation + cache_read` of the **newest** assistant line. Context window = **1,000,000** (config value, overridable per model;
  the app reports 1M for the current model). Only `user` and `assistant` lines count as activity; the other types are housekeeping.
  A `tool_use` unanswered for > 45 s may be a long tool or an approval prompt: show `waiting?`, not `working`.
- **Codex** `~\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl` **and** `~\.codex-emdash\sessions\...` (Emdash runs Codex under a second home with its own login).
  Lines are `{"timestamp","ordinal","type":"event_msg","payload":{"type":...}}`. Working = a `task_started` with no later `task_complete` in the same file.
  Context now = `payload.info.last_token_usage.input_tokens` of the newest `token_count`, over `payload.info.model_context_window` (258400 seen).
  Plan limit = `payload.rate_limits.primary.used_percent` (`window_minutes` 10080 = weekly, `resets_at` = epoch seconds).
  **Only trust it when** `limit_id == "codex"` **and** `primary` is not null **and** `resets_at` is in the future.
  Traps already seen: an entry with `limit_id: "premium"` and every field null (ignore it, never show 0%), and a window whose `resets_at` already passed (stale: show `-`).
- **Claude plan limits (5-hour / weekly) are not readable from outside a session.** Verified. Do not try, do not read credential files, do not call any Anthropic endpoint.
  v1 shows Claude plan % only if the optional feed `%LOCALAPPDATA%\minis\feeds\claude-plan.json` exists: `{"five_hour": 59, "weekly": 8, "ts": "<iso>"}`;
  ignore it if `ts` is older than 15 min. Claude (the reviewer) writes that file on demand. Without it the slot is simply absent.
- Neither agent writes a checklist in this setup (no `TodoWrite`, no `update_plan` anywhere). A true "task % complete" cannot be measured from outside.
  Do not fake one and do not build a checklist reader.

## What the % is (decided)

- **Headline bar = context fill of the active session**: `ctx 23%`. Same meaning for both agents. The bar fills as the context fills (it is usage, not health).
- **Codex secondary = weekly plan limit** `wk 1%` under the trust rules above. **Claude secondary** = `5h 59%` only from the optional feed.
- Unknown = `-`. Colors: under 70 accent, 70-89 amber, 90 and up red and the bar blinks slowly.
- Active session = newest file by mtime across that agent's homes, ignoring files older than 24 h. No session in 30 min = `sleeping`.

## References - STUDY ONLY

The author's three links. Distilled lessons are below. Do **not** trace, copy, redraw or recreate any of those pieces; our fighters are original (Pixel Joint's own
fighting-character challenge requires original characters). The downloaded reference files stay outside this folder and are never committed, shipped or posted.
Classic 2D arcade fighters are style inspiration only.

| Source | What it measured / said | Lesson we take |
| --- | --- | --- |
| Pixel Joint 31255 "protecteur" (IGoRge): https://pixeljoint.com/pixelart/31255.htm | 76 frames, 100x100, 55 colors, uniform 100 ms. Frames 0-24 are a near-still idle hold; 25-29 anticipation crouch; 30-47 spin; 48-55 lunge; 56-67 long follow-through where the cloak does the work; 68-75 recovery back to frame 0 (seamless loop). Spear spin drawn as a fan of copies. Cloak is two-tone and flips to read rotation. A commenter saw the cloak change color for 1-2 frames. | Long hold then a burst. Anticipation, action, follow-through, recovery. Secondary motion (cloth) carries the weight. Smear by drawing copies, not blur. Two-tone cloth reads as turning. A palette slip for 1-2 frames is a bug: test for it. |
| ArtStation XaBDDl "2D Fighting Game Boss - 128px" (Mudassir Khan): https://www.artstation.com/artwork/XaBDDl | 128 px tall on a 256 canvas. Pipeline stated by the artist: **gray structure (movement approval) -> clean line art with selout -> high-contrast shading and cleanup -> final animation**. Moves: idle 10 frames @100 ms, walk 6 @100, hurt 7 @100, death 13 (100/200 ms), afterimage dodge 11 (300/80/100/200 ms). About 65-70 colors. Tagged NoAI, hand-placed pixels. | Approve motion on a flat structure pass before spending on polish. Selout (outline tinted by the neighboring fill, lighter on the lit side) plus volumetric shading. Uneven timing: 80 ms bursts, 200-300 ms holds. A fighter's core move list. |
| Pixel Joint "Fighting Character" challenge (2007): https://pixeljoint.com/2007/05/21/2194/Pixel_Art_Challenge-_Fighting_Character.htm | Humanoid fighting-game character, standing animation, **32 colors max counting transparency**, transparent background, original only. A simple blink counts as animation. | Our palette cap: <= 32 incl. transparency per fighter. Idle can be tiny. |
| Pixel Joint 124256 "Soldier! STRIKE!" (Cyangmou): https://pixeljoint.com/pixelart/124256.htm | 64 frames @24 fps, ~100 px tall. Commenters: the strike hits empty air so it has no force; feet slide during the shake. | Hits must **connect** with something. No foot sliding. |
| Pixel Joint 61904 "HD Soldier Puncher": https://pixeljoint.com/pixelart/61904.htm | Commenter: a convincing fighting stance means redrawing the whole body each frame. | Re-pose limbs per frame (rig), never just translate or rotate one picture. |

The Pixel Joint "animated soldier" search page the author linked loads its results by JavaScript and cannot be read by a plain fetch. The list above came from a site search instead.

## Fighter design (Claude's creative direction)

- Chibi, about 3 heads tall: head ~14 px, big hands and feet, eyes 2 px, mouth 1-2 px. Readable as a solid-black silhouette at 1x, and **the two silhouettes must be distinguishable**.
- **Claude fighter**: lean, **42 px** standing. Terracotta `#D97757` hoodie, cream `#F0EEE6` scarf tail, ink `#1F1E1D` pants and outlines, reversed cap (terracotta) with a cream `/`.
  Fast jabs, spin kick. Precise, a little cocky.
- **Codex fighter**: stocky, **38 px** standing, shoulders ~2 px wider. Black `#16161A` hoodie, blue-to-violet trim `#5B6BFF` -> `#9B6BFF`, white sneakers, reversed black cap with a violet `$`.
  Slower, harder hits, longer hit-stop. A builder.
- Same dojo, same rig, different bodies and costumes. Skin ramps may differ. Both face **right** in the art; mirror in code (never author left-facing frames).
- Palette: <= 32 colors per fighter counting transparency, one palette for every frame. 3 tones per material, light from top-left, no dithering except the afterimage.

## Native format (our own, not the Pets atlas)

- Cell **64x64**, ground line y=58, feet bottom on y=58 in every grounded frame. The window's bottom edge sits on the screen bottom, so the taskbar band is cell rows 16-63:
  a standing fighter lives inside the bar, jumps and kicks may poke above it.
- Integer scaling only (nearest neighbor, never blur): scale = `max(1, floor((taskbar_px - 4) / 42))`. At 150% DPI that stays 1x, centered. Document it.
- Output per fighter: `assets/<who>/sheet.png` (cells in a grid, one row per animation) + `assets/<who>/anim.json`:
  `{cell:[64,64], ground_y:58, palette:[...], anims:{name:{row, loop, frames:[{i, ms, dx}], reach?, hit_frame?}}}`.
  `dx` is per-frame root motion in px. `reach`/`hit_frame` exist for attacks.

## Art pipeline (mirror the pro workflow) - generated by code, reproducible

Build `art/fighters/` so one command rebuilds everything: `python art/build_fighters.py --stage structure|lines|shade|all`.
Poses are **data** (joint targets per frame). A 2-bone solver places elbows and knees; parts are rasterized as thick polylines/capsules.
1. **structure** - flat colors per part, no outline, no shading. This is the motion-approval pass. **Approval gate: stop here and wait for the author/Claude.**
2. **lines** - 1 px outline with selout (tinted from the neighboring fill's dark tone; lighter on the lit side), 1 px internal separation lines where a limb crosses the body.
3. **shade** - 3 tones per material, top-left light, volume at the edges (not noise).
4. **cleanup** - palette lock to <= 32, no stray single pixels except intended ones, loop seams.
5. **effects** - hit spark (5x5 burst), afterimage by 50% checker dither, attached opaque `z`/stars; all inside the palette.
Hand-polish hook: if `art/fighters/hand/<who>/<anim>_<n>.png` (64x64, same palette) exists it replaces that generated frame, so an artist can fix single frames in Aseprite without touching code.

### Animations (names are API; the planner uses them)

Run 1 builds the **structure pass** of all of these. Run 2 (after approval) adds `kick`, `walk_back`, `bow`, `fistbump`, `flourish` and does the polish.

| name | frames | timing (ms per frame) | notes |
| --- | ---: | --- | --- |
| idle | 6 | 120, long hold feel (breathing 1 px) | cloth sways. Every 6-10 s a `flourish` (Run 2) |
| walk | 6 | 100 | stride-locked: world foot x of the planted foot stays within 1 px (test it) |
| jab | 5 | 100, 100, **60**, **140 (contact)**, 100 | anticipation, strike, contact hold, recover |
| block | 3 | 60, 120 (loop), 80 | |
| hit | 4 | **60 flash**, 100, 100, 100 | recoil <= 6 px, pulled, never falls |
| ko | 6 | 100 x4, then 200 x2 hold with attached stars | only at >= 90% |
| victory | 4 | 120 | fist pump |
| jump | 5 | 80, 60, 120, 60, 80 | crouch, rise, apex, fall, land |
| work | 6 | 90 | shadowboxing: the "running" state |
| review | 4 | 120 | lean in, chin stroke, nod |
| wait | 4 | 150 | foot tap, hands on hips: the `waiting?` state |
| sleep | 2 | 600 | sitting, head down, tiny `z` |

## Product spec

**Processes.** `pythonw minis.py run claude` and `pythonw minis.py run codex`. One named mutex per `who` (no duplicates). `minis.py start|stop|status`. `stop` kills only PIDs from
its own pidfile after confirming the command line matches; it never touches other processes. `print-startup` prints the Task Scheduler / Startup-folder commands; **do not run them**.

**Window.** Layered, per-pixel alpha, topmost with the 250 ms tick, no taskbar button, never steals focus, transparent pixels are click-through. Horizontal drag only.
Right-click menu: Hide 1 h, Swap stretch (left/right), Quit this mini. Double-click: victory. Per-monitor DPI v2; re-read the taskbar rect every 2 s and on `WM_DISPLAYCHANGE`.
Hide while a fullscreen app/video/presentation is active (`SHQueryUserNotificationState`). Taskbar not at the bottom or auto-hidden: park at the bottom of the work area and log it.
Budget <= 1% CPU each on average: 10 fps while moving or working, 4 fps idle, telemetry poll 1 Hz using tail reads (never parse a whole file).

**HUD plate** (fighting-game style) travels with the fighter: a dark ~70%-alpha pill so it reads on a light or dark taskbar. Line 1 = `/reverse` or `$reverse` in the fighter's accent + state word
`working | idle | done | waiting? | sleeping | limit`. Line 2 = a chunky segmented bar with `ctx 23%` and the secondary figure. Prefer an embedded 5x7 pixel font (hand-coded glyph table: digits,
`%`, `/`, `$`, letters used); Segoe UI is an acceptable fallback if time-boxed. Hover = every number plus "resets in 2d 4h".
Show only state and numbers: **never session titles, prompts, file names or client names**. No content is logged, stored or sent; no network at all.

**State -> animation.** idle=idle, working=work, done=jump then victory, waiting?=wait, limit=ko then wait, sleeping=sleep (dimmed), walking=walk, visiting a finished partner=review,
sparring=jab/block/hit, watching a partner=idle facing it.

**Sparring (loose coupling; roles: Codex writes, Claude reviews).** Bus: each mini atomically writes (`os.replace`) `%LOCALAPPDATA%\minis\bus\<who>.json` at least every 500 ms:
`{who, ts, state, ctx_pct, x, facing, anim, event:{seq,type}}`, and reads the partner's. No sockets, no shared memory, no startup order. Partner file missing or older than 5 s = solo; absence never raises.
- Both idle: stay in your home half. Every 60-120 s (jittered) do a **bout**: walk to `reach` px apart, bow, 3-4 exchanges (jab -> block, jab -> hit with hit-stop), fist-bump, go home.
- One is working: the other turns to face it and watches.
- **Codex finishes** (working -> idle after >= 15 s of work): Codex does `jump`; Claude walks over, plays `review` ~6 s, a short spar exchange, fist-bump, goes home.
  **Claude finishes**: Claude jumps; Codex does `victory` where it stands.
- A fighter at >= 90% (ctx or plan): `ko`, then `wait`; the partner walks over and offers a fist-bump.
- **Hits connect**: the attacker's `hit_frame` is aligned to the defender's hurtbox at `reach` px, then both freeze for the hit-stop (2-3 frames), then the defender plays `hit`. No swinging at air.
- Never overlap more than ~20 px, never leave the zone, never cross the icon cluster. The planner is pure: `(own snapshot, partner snapshot, clock, rng) -> intent`; test it with scripted scenarios and a fake clock.

**State inference (no hooks, no config edits).** Read-only polling of the newest session file per agent. Claude: last `user`/`assistant` line = working; assistant with `stop_reason` other than `tool_use` = idle (done for 8 s after);
> 45 s quiet while the last line is a `tool_use` = `waiting?`. Codex: `task_started` without `task_complete` = working. Guard: no new line for > 10 min = idle. Do not edit `~/.claude/settings.json`,
`~/.codex/config.toml`, hooks or `statusLine`.

## Layout (suggested; keep Win32 behind a thin shell so logic is headless-testable)

```
minis.py                 CLI: run | start | stop | status | selftest-gui | render-qa | print-startup
minis_core/              config, snapshot, telemetry_claude, telemetry_codex, bus, planner, atlas, render, geometry, font   (pure Python + Pillow)
minis_win/shell.py       layered window, keep-on-top tick, drag, menu, mutex, fullscreen check                            (ctypes)
art/build_fighters.py    + art/fighters/ (rig, solver, poses, lines, shade, effects, export)
tests/                   unittest (do not assume pytest); fixtures/ already provided
assets/  qa/  minis.json  README.md  RESULT-codex.md
```

Stdlib + Pillow only (Pillow is installed). Python 3.14. No pip, no network.

## Run 1 milestones - append a short section to `RESULT-codex.md` after each, so an early stop still leaves a trail

- **M1 structure fighters.** Both fighters, all 12 animations, flat structure pass, `assets/<who>/sheet.png` + `anim.json`. QA: `qa/structure-<who>-<anim>.gif` at 6x, plus `qa/structure-contact.png` showing both fighters side by side
  so the silhouette difference is visible. **Then continue to M2 with these flat fighters. Do not start lines/shade/polish.**
- **M2 Win32 shell.** Both fighters idle/walk on the taskbar, keep-on-top, drag, quit, HUD plate with placeholder numbers; `selftest-gui` written.
- **M3 telemetry + state** on the fixtures, every trust rule.
- **M4 bus + planner** (sparring scenarios).
- **M5** README, `print-startup`, final RESULT.

## Done-when (demonstrate each, do not claim it)

1. `python -m unittest discover -s tests` is green and covers: both parsers on every fixture (working / done / housekeeping-only / premium-null / stale-window), the 45 s waiting rule, the 24 h and 30 min session rules,
   atomic bus write + stale + missing partner, the planner scenarios (both idle -> bout; Codex finishes -> Claude visits; >= 90% -> partner consoles; partner absent -> solo; **hit_frame aligned to reach**),
   `anim.json` schema, geometry at 100% and 150% DPI.
2. **Art gates, as tests:** <= 32 colors incl. transparency per fighter; every frame's colors are a subset of one palette (the protecteur color-slip bug); feet bottom y = 58 in every grounded frame;
   sprite inside the 64x64 cell with >= 1 px margin except jump/kick frames; `walk` planted-foot drift <= 1 px; looping animations close (first/last frame distance under a threshold);
   the two fighters' idle silhouettes differ (IoU < 0.8); no orphan single pixels except eyes/sparks.
3. The structure GIFs and contact sheet exist in `qa/`.
4. `selftest-gui` exists and exits non-zero on failure: opens both windows for 6 s, checks via `ImageGrab` that each window's region differs from the bare taskbar, repeats the raise/re-assert test from the spike,
   writes `qa/gui-composite.png`. **The Codex sandbox cannot show windows on the author's desktop, so you cannot run it. Do not switch to `danger-full-access` to try.** Claude runs it on the real desktop. Say so in RESULT.
5. `RESULT-codex.md` (plain words): built, verified and how, not verified and why, every decision I did not specify.

## Stop rules

- Write only inside this folder. Everything else is read-only.
- No network, no pip installs, no new services, scheduled tasks or startup entries, no edits to `~/.claude/settings.json`, `~/.codex/config.toml`, hooks or `statusLine`. No pet tools, no image generation (the
  pixel art is built by code). No real transcripts or credentials (fixtures only). Do not look up, download or re-fetch the reference pieces.
- Do not kill or touch any other process. `stop` is pidfile-only.
- Three failed attempts at the same problem: write the blocker and who must clear it into RESULT and move to the next milestone.
- Do not widen scope (no settings UI, no auto-update, no telemetry upload, no extra characters, no polish pass before approval).

## Review plan

Claude reviews the diff, the structure GIFs and contact sheet, runs `selftest-gui` and the real windows on the author's desktop, screenshots the taskbar, and returns a must-fix / nice-to-fix list. You get one fix pass.
The author approves (or redirects) the fighters' motion and silhouettes at the gate. Run 2 is a separate brief written after that.
