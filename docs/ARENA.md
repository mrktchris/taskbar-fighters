# Arena mode

Arena mode lets the two fighters leave the taskbar and fight across one whole monitor, in the style of a platform-fighter
game crossed with an anime battle. Window edges become walls and ledges, the taskbar line becomes the floor, and glass
cracks, shatters and rains letters.

![Arena mode](img/arena.png)

**Visual only: nothing real happens to your windows.** The arena is one click-through overlay window, and everything you see
is paint on it. The program reads one thing from the desktop: the rectangles of visible windows, as numbers. It never reads
titles or contents. It never moves, resizes, focuses, closes, minimizes or types into any window. Screen shake moves the
overlay itself and nothing else. Desktop weapons (below) and the optional freeze backdrop (`--freeze`) use one picture of the
monitor that stays in memory and is never written to disk. A test proves this: `VisualOnly7` in `tests/test_arena.py` runs the real arena process with a
recording shell and a recording `user32`. The test requires that the only shell call is the single-instance mutex and that
`user32` is never called.

## Starting and stopping

```
python minis.py arena [--monitor N] [--seconds S] [--freeze]
```

ESC, the EXIT button (top right), `python minis.py arena stop`, or the scoreboard's Arena button ends the arena. Pausing the
fighters (`minis.py pause`) pauses the arena too.

## Options

The arena takes six options. They are validated, and any bad value falls back to its default without an error.

| option | values | default | what it does |
| --- | --- | --- | --- |
| `rounds` | `1`, `3`, `5` (`0` or `"endless"` = endless) | `3` | best of 1, 3 or 5 |
| `endless` | `true` / `false` | `false` | free-for-all: rounds continue until stopped, no winner pose, nothing recorded |
| `intensity` | `calm`, `normal`, `wild` | `normal` | how much destruction and effects (table below) |
| `seconds` | number > 0 | none | the arena leaves on its own after this many seconds |
| `intro` | `true` / `false` | `true` | the VS card before round 1 |
| `outro` | `true` / `false` | `true` | the winner flies to the highest window to pose, then both dive back into the taskbar |

Where they come from, each layer overriding the one before:

1. the defaults above
2. `minis.json`, as `"arena": {"rounds": 5, "intensity": "wild"}`
3. `control.json` in the data folder, as `"arena_opts": {...}`. The scoreboard or menu can write this for one session.
4. `Arena(..., options={...})`, which is what the CLI flags map to

| intensity | `calm` | `normal` | `wild` |
| --- | --- | --- | --- |
| particles and letters | half | 1x | 1.8x |
| stage hazards | off | every ~8 s | every ~4 s |
| letter rain after a shatter | 1.2 s | 2.6 s | 4.5 s |
| zoom punch | 1.07x | 1.14x | 1.20x |
| letterbox | 70 % | 100 % | 120 % |
| colour flashes, speed lines | off | on | on |
| beam clashes per match | 1 (30 %) | 1 (55 %) | 2 (85 %) |
| meteor spike chance | 25 % | 50 % | 80 % |
| craters kept | 2 | 4 | 7 |
| knock-through speed | 1250 px/s | 950 px/s | 760 px/s |
| set-piece chance per exchange | 15 % | 25 % | 40 % |
| desktop weapons per match | 1 | 2-4 | 5-7 |
| forged weapon lasts (exchanges) | 2 | 3 | 4 |
| a heavy crack knocks a piece loose | 25 % | 50 % | 75 % |

## What happens in a match

### Intro and outro

The fighters burst out of the taskbar with a ring and land. Two name plates slide in from the sides, and "VS" drops in
between them. Then the round banner and FIGHT! appear. At the end, the winner flies to the highest window top and holds its
victory pose under a "<NAME> WINS" banner. The loser slumps up. Then both hop and dive back down into the taskbar.

![Intro and outro](img/arena-intro.png)

### Stage interaction

![Stage interaction](img/arena-stage.png)

- **Wall bounces.** A fighter knocked into a monitor edge, or into a window's side faster than 380 px/s, bounces back. It
  keeps 55 % of its speed, after a 60 ms stop and a spark. Slower hits just stop.
- **Tech recoveries.** On a bounce, the fighter sometimes flips off the wall onto its feet (35 to 55 % of bounces,
  depending on intensity).
- **Ledge grabs.** A fighter falling past a window's side catches the ledge, hangs with a small damped bob, and climbs up.
  The climb goes up first and then over the lip, eased at both ends. Defenders also fly to a ledge on purpose and catch it.
- **Knock-through.** A fighter knocked into glass fast enough goes through it. Its own silhouette is left cracked into that
  window: a frosted outline with radial cracks, clipped to the window. Slower hits crack or bounce. Three cracks shatter a
  window, as in V4.
- **Skids.** Landing a knock-back faster than 360 px/s slides at a constant 1500 px/s² deceleration. That gives about
  220 px from a knockdown. On a window top, sparks fly up and back. On the floor, dust rises. A fighter can skid off the end
  of a window top and fall, and sometimes catches the ledge.
- **Craters.** Landing on the taskbar line faster than 1500 px/s, or taking a ground-slam move there, leaves a crater:
  a dent with a lit rim and cracks running into the taskbar, plus rubble that bounces once. Craters stay for the match,
  up to the intensity's cap.

### Aerial game

![Aerial game](img/arena-air.png)

- **Double jumps.** Air-to-air exchanges start with a jump and a second jump at its apex, with a ring under the feet. The
  second jump is sized to peak exactly at the meeting height, so the hover never snaps.
- **Air dashes.** In the air, an approach longer than 160 px is a dash, with afterimages and speed lines.
- **Juggles.** A launcher pops the defender up with light gravity, which gives hang time. The attacker jumps after it and
  strikes in the air.
- **Meteor spikes.** A knockdown in the air can spike the defender straight down. It falls through every window top it
  crosses, cracking each one with sparks, and lands in a crater with one bounce.
- **Recovery jumps.** A fighter knocked off into the air gets one jump back up, towards a nearby ledge if there is one.

### Camera

![Camera](img/arena-camera.png)

- **Letterbox.** Black bars ease in for supers, ultimates, clashes, set pieces and the final KO. The bars are drawn behind
  the fighters, so they never hide a foot on the taskbar line.
- **Zoom punch.** A seamless lens zooms the region around the fighters by up to 1.07x, 1.14x or 1.20x. The middle of the
  region is scaled while its rim stays fixed, so there is no seam. The zoom never reaches past the monitor. It is driven by
  a critically damped spring, so it eases in and out, and a second punch during a zoom continues the first instead of
  jumping.
- **Speed lines.** Speed lines appear behind dashes, air dashes, meteor falls and hard knock-backs.
- **Final KO.** The match-deciding blow freezes on contact, then plays the fall in slow motion behind animated radial
  focus lines, with a colour flash in the winner's accent. In endless mode, every KO gets this.
- **Flashes.** Colour flashes, white flashes, impact frames and ink frames all obey `minis.py flash off` (control.json
  `flashes`). With flashes off, there are no full-screen frames at all.

### Beam clash

![Beam clash](img/arena-clash.png)

When a super meets a super, or both fighters are charged (meter of at least 70 after the third exchange of a round), the
exchange can become an anime beam duel:

1. Both fighters fly to marks 720 px apart in the air and charge.
2. They fire. Two beams grow from their hands and meet in the middle.
3. The meeting point sways back and forth for about 2 s. The whole overlay trembles, sparks fly, and the fighters
   mash-shake.
4. In the last 40 %, the point drifts towards the loser. The winner overpowers: its beam races to the loser, and there is
   an explosion, impact frames, a zoom punch and a colour flash. The loser takes the winner's super or ultimate damage and
   is knocked down.

The winner follows the `winners` mode (`decided` biases it by the health score) blended with the current HP. A clash
spends both fighters' meters. There is at most one clash a match, or two on wild.

### Set pieces

![Set pieces](img/arena-setpieces.png)

Set pieces are hand-authored sword scenes: one timeline for both fighters, polished frame by frame, played 2 to 4 times a
match at dramatic moments and mixed with the procedural fight. A match always gets at least 2, and the last ones come
when a round may be the deciding one.

| set piece | what you see |
| --- | --- |
| `vanishing_cut` | A low stance as the blade is drawn in its element. The attacker vanishes, leaving a painted streak, and reappears behind the defender in its follow-through. Both hold still for a frozen beat. Then the cut lands: an ink-wash frame and a diagonal painted slash, and the defender falls. |
| `flurry` | A dash in, then five rapid cuts with afterimages, each a short painted arc across the body while the defender staggers back. A wind-up, then one big cut sends it down. |
| `stance_finisher` | A long stance and charge: three element swirls round the blade, focus lines and a slow zoom. A vanishing dash, a long frozen key pose with speed lines, then the finisher: a wide slash, an ink frame and a colour flash. |

**Elements.** Each fighter's trails are painted in one element, chosen from its colours: flame, water, lightning, wind,
petal or ink. An `element` key in the character's anim.json overrides the choice. Every element is an original design:

- flame: tongues licking off the arc
- water: curls breaking off it
- lightning: a forked zig-zag in the fighter's own tint
- wind: streaks riding the ribbon
- petal: petals shed along it
- ink: dry-brush gaps and splatter

A trail is a wide ribbon that follows the blade arc. It is painted on fast, held, then thinned from the tail and faded. The
big cuts pass through the defender's torso instead of circling it. Ribbons are drawn at the arena's full HD scale and
cached in 16 progress steps.

**Ink-wash impact frames.** When a set piece's cut lands, it shows an ink-wash frame for 180 ms: a black brush splash
behind the struck fighter, the struck fighter as a white silhouette, and a white cut across the splash. The attacker stays
drawn normally.

**Authoring format** (`minis_core/arena_setpieces.py`). A set piece is
`dict(gap, span, dur, dmg, keys=[(t, op, *args)])`. Times are real seconds from the set piece's start, and positions are
1-D along the line between the fighters: x = 0 is the attacker's mark, `gap` is the defender's, positive x is the way the
attacker faces. The ops are:

- `pose` (role, slot): every frame index comes from the atlas (`arena_setpieces.frame_of`: hit_frame, the jump's `air`
  keys for rise / apex / land, smear_frames, a reaction's held pose), never a number written here
- `pos` (role, `x` or `near` = offset from the attacker's striking distance, `dur`, `ease`, `ghosts`)
- `alpha` (role, a)
- `ghost` (role)
- `face` (role, `toward` | `away`)
- `trail` (role, `cut(...)` or `dict(path='arc' | 'line', ...)`)
- `ink` (role)
- `hit` (`dmg`, `react` = `stagger` | `recoil` | `knockdown`, `push`, `final`)
- `spark`, `shake`, `flash`
- `cam` (`box`, `punch`, `lines`, `radial`)
- `forge` (role): V8, the role forges a desktop weapon during the stance when desktop weapons are on and the match still owes one; `cut` poses swing a weapon in hand, and a `final` hit shatters it

**Pose slots** keep set pieces working for any pairing. Each slot reads a move from the fighter's own atlas, never by a
move's name:

| slot | pose |
| --- | --- |
| `stance` | low ready stance |
| `charge` | the power-up loop |
| `dash` | the dash smear frame |
| `wind`, `cut`, `follow` | the strongest blade strike's frame before contact, contact frame, and follow-through |
| `cut2`, `cut3` | the next strikes' contact frames |
| `guard` | block |
| `stagger`, `recoil` | hit / heavy hit |
| `idle` | release back to the normal animation |

The strikes are ranked from the atlas: grounded slashes first, then by power, with kicks, punches and aerial moves last.
A missing move falls back to idle and never raises.

To add a set piece, add an entry to `SETPIECES`, render it with the QA scripts described under Verification, and check
every frame at 1x and 2x before shipping it.

### Forging: desktop weapons

![Desktop weapons](img/arena-forge.png)

![Desktop weapons animated](img/arena-forge.gif)

The owner's decision: weapons are forged from REAL screen pixels, always (on by default; `python minis.py forge off` turns
it off). The images above are rendered headless on a synthetic desktop, never a screen grab.

1. **Reach and cut.** The forger turns to a nearby region, throws an arm out and a glowing tether runs to it. An outline in
   its element colour draws round the region's torn edge (0.32 s), then flashes white (0.08 s).
2. **The hole.** The piece lifts off and the arena paints a dark, jagged hole where it was: a dark wall, a lit torn edge,
   glowing in the forger's colour for 0.9 s. The real window under it is never touched. Holes go away when their window
   moves or closes; at most 10 are kept.
3. **Lift and morph.** The piece (the region's pixels, clipped to the torn outline, with a rim and glow) flies in front of
   the fighter (0.30 s). Then 8 frames at 30 fps of pixel-shatter and re-assembly: 10-px blocks of the piece scatter
   outwards and gather into the weapon's silhouette, carrying the weapon's texture in the second half; the unused part
   of the piece falls away as debris. The weapon settles into the hand (0.12 s).
4. **Held in the hand.** While a weapon is held, the fighter is drawn from its unarmed sheet (its own weapon disappears)
   and the forged weapon sits at every drawn frame's `grip` from anim.json: pivot at the grip point, extending along the
   grip angle, so it moves exactly with the arm through strikes, jumps, hits and falls. Dual-wielders (a second grip at
   a different angle: gemini, codex, kunoichi, monk, nomad, generic) hold a second copy at `grip2`, drawn behind the body;
   for a two-handed weapon `grip2` is the other hand on the same weapon. Around a strike's contact (hit_frame +/- 1),
   when the grip turns 25 deg or more between drawn frames, two ghosts at the previous grips and a crescent swept along
   the tip's real path make the swing smear. A frame with no grip holds nothing. It hides only while its holder has
   vanished in a set piece. After the shatter the native weapon is back on the next frame.
5. **Cracks and shatter.** Every hit it lands (or a block) adds a crack (a heavy hit two); the third shatters it. It also
   shatters when its uses run out (calm 2, normal 3, wild 4 exchanges), when its holder is KO'd, and on a set piece's
   finishing cut. Shattered, it breaks into squares of its own pixels that burst, fall with gravity, bounce once on the
   taskbar line and fade in four steps (about 1 s).
6. **Slabs.** A fighter that is already armed (or 30 % of the time) rips out a jagged slab instead and hurls it: the slab
   spins along an arc to the opponent, shatters into debris on contact, and hits for 10.
7. **Loose pieces.** A heavy crack or a shatter can knock a chunk of real window off (calm 25 %, normal 50 %, wild 75 %,
   at most 3 at once). It falls, lands on the first top below it and lies there for 14 s; a forger nearby dashes to it,
   crouches and forges it instead of cutting a new piece.

**Families** (`forge.family_for`: anim.json `forge` / `weapon` when the art names one, else the roster table, else a blade):

| family | fighters | cut from | shape |
| --- | --- | --- | --- |
| blade | claude, lmstudio, gemini, generic | a long strip of a window's title bar (264 x 34) | 232 px curved blade, guard, dark grip |
| greatsword | knight | a big window chunk (210 x 230) | 252 px broad blade, crossguard, pommel |
| axe | barbarian | a window chunk (190 x 200) | haft with a crescent head and a beard |
| spear | cursor, ollama | a thin taskbar strip (360 x 16) | 330 px shaft, collar, leaf tip, held at a third |
| club | oni, monk | a square block (124 x 124) | tapered, a round studded head |
| shards | codex, nomad, kunoichi | a pane (176 x 132) | a fan of three glass shards between the fingers |
| slab | anyone (thrown) | a desktop chunk (156 x 116) | the torn rectangle itself |

The piece's pixels are turned a quarter if that keeps more of them, cropped to the weapon's aspect (never squashed),
resampled, and clipped to the silhouette. A bevel (a lit top edge, a shaded bottom edge), a one-pixel bright rim and a glow in
the fighter's element colour make it read on any desktop, white windows included.

**How many.** 2-4 forges a match at `normal`, exactly 1 at `calm`, 5-7 at `wild` (`forge.TARGETS`). They are spread over the
rounds that must still be played and favour dramatic moments: the fighter under 35 HP rips out a weapon, match point and a
comeback raise the chance, and the `stance_finisher` set piece forges a blade during its stance (the finishing cut then
shatters it). Region choice prefers windows near the fighter, unoccluded, clear of the HUD and of earlier holes; the
taskbar strip is the spear's home.

**Privacy: engineering rules, not options.**

- The monitor is grabbed ONCE, when the arena starts (`minis.grab_monitor`): Windows uses PIL's in-memory BitBlt grab
  (BGRA to RGBA), macOS uses Quartz only when the Screen Recording permission is already granted. A headless run never grabs.
- The grab is held as `forge.ScreenImage`: regions are cropped from it, it cannot be pickled, and its repr names only a size.
  No captured pixel is written to disk, logs, `arena.json`, temp files or crash dumps. The heartbeat says only
  `screen_pixels: true|false` and a forge count.
- `arena capture` refuses while the arena holds the grab (and while `--freeze` is on).
- `minis.py forge off` (control.json `forge`), or unticking **Desktop weapons** in the tray menu or a fighter's right-click
  menu, drops the grab within 2 s in a running arena, together with every image made from it (weapons, pieces, morph
  frames, debris, caches); the overlay repaints those rectangles without them. The next arena does not grab at all.
- The grab is dropped when the arena closes (`Forge.purge` in `run_arena`'s finally).
- A window that moved since the grab no longer matches its pixels: its pieces are forged from its shape.

**Without pixels** (macOS without Screen Recording, a failed grab, a moved window), the weapons are forged from window
SHAPES: the same cut, hole, morph and weapon, textured with a stylized frosted glass (window chunks) or brushed steel (title
bars, taskbar strips) drawn from the rectangle's outline. `python minis.py doctor` reports which mode applies and how to
grant the permission. Taskbar Fighters never calls `CGRequestScreenCaptureAccess`.

### Moves from the roster

The arena plays every move through the choreography API and reads what a move does from its traits. `move_traits()` reads
them from the beat's flags first, then the anim.json `traits` / `tags` / `family`, then the move's name:

| trait | what the defender does |
| --- | --- |
| `launcher` | popped up with juggle hang time |
| `throw` | hurled into walls and windows |
| `pull` | dragged back in |
| `boomerang` | the projectile flies back to its owner |
| `pound` | a crater, or a crack in the window top underfoot |

An attack kind the arena has never heard of still plays as an attack, and a move missing from an atlas is skipped.

### Stage hazards

![Stage hazards](img/arena-hazards.png)

- **Letter rain.** A shattered window rains random glyphs for a few seconds. The glyphs are random, never text read from
  anywhere.
- **Shard platforms.** Every few seconds (normal and wild only), a crack spreads across a window and a glass shard drops
  out of it. The shard lands on the first top below it and becomes a platform you can stand on for 12 s, then crumbles.

## Performance

These figures come from a headless benchmark: six seeded matches, 1920x1080, the premultiply conversion the real window
does on every write included, 30 fps. They are milliseconds per frame (tick + render + premultiply).

| | mean | p50 | p95 | max |
| --- | --- | --- | --- | --- |
| V6 (before) | 3.16 | 2.35 | 7.16 | 182 |
| V7 calm | 2.03 | 1.02 | 8.16 | 48 |
| V7 normal | 2.61 | 1.17 | 9.97 | 71 |
| V7 wild | 3.05 | 1.50 | 10.36 | 50 |

V7 costs less on average than V6, even though it draws more. Two changes pay for the new effects:

- The compositor now repaints only the drawables that appeared, moved, changed image or disappeared. An unchanged HUD,
  decal or banner is no longer repainted every frame.
- The letterbox repaints only the strip it grew or shrank by.

V8 (desktop weapons), measured with `python tests/arena_harness.py bench --seeds 4` (same method, 1920x1080, claude vs
knight, the Windows premultiply included):

| | mean | p50 | p95 | max | CPU at 30 fps |
| --- | --- | --- | --- | --- | --- |
| V8 normal, forge off (= V7) | 2.43 | 1.06 | 9.00 | 40.5 | 7.3 % |
| V8 calm, forge on | 2.06 | 0.99 | 8.82 | 64.7 | 6.2 % |
| V8 normal, forge on | 2.80 | 1.35 | 10.64 | 62.9 | 8.4 % |
| V8 wild, forge on | 3.34 | 1.73 | 11.51 | 57.0 | 10.0 % |

Hand tracking (2026-10-16) adds the per-frame grip lookup and the unarmed sprite; measured while the PC was under other load,
forge on cost about 30 % over forge off for the same matches, so the absolute figures in the table are the earlier run.
Forging costs about 0.4 ms a frame on average at `normal`: weapon rotations are cached per 6 deg step and crack level, morph
frames are built once per forge, and weapon art is built once (the morph's first frame). The max frames are a forge's
first morph frame and a shatter.

**macOS** (FOUND-2): the same bench with `--backend mac` simulates the macOS window's per-frame work (RGBa conversion and
bytes of every touched tile):

| macOS window | ms/frame mean | p95 | tiles uploaded / frame | tiles skipped / frame | pixels uploaded / frame |
| --- | --- | --- | --- | --- | --- |
| V7: 256-pt tiles, full-frame flashes | 2.74 | 9.27 | 8.9 | 0 | ~583 k |
| V8: 128-pt tiles, empty tiles skipped, GPU flash layer | 2.31 | 7.77 | 15.9 | 4.9 | ~261 k |

That is 55 % fewer pixels converted and handed to Core Animation per frame. What the PC cannot measure is the Core Animation
cost per layer update on a real Mac (V8 makes more, smaller updates); `MINIS_ARENA_PROFILE=1` logs it there
(docs/MAC-HANDOFF.md).

The expensive frames are the zoom lens (a 0.45-monitor region, nearest-neighbour mesh) and the few full-screen flash
frames. The process starts at `arena_fps` (60) and steps down to 30, then 20, while it measures over `arena_cpu_budget_pct`.

**V9 (2026-10-21, "arena 30 fps"):** `python tests/arena_harness.py bench --backend winblit --seeds 3 --size WxH --json`,
`normal`, forge on, claude vs knight, the Windows premultiply and the layered-window write emulated (tile 128), three seeded
matches, about 5100 frames each run. Before = the V8 compositor (vendored as `tests/v8_compositor.py`), after = V9.

| 30 fps, ms/frame | mean | p50 | p95 | p99 | max | frames > 33 ms | CPU at 30 fps | px written / frame |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1920x1080 before | 3.01 | 1.57 | 10.52 | 22.38 | 159.5 | 33 | 9.0 % | 193 665 |
| 1920x1080 V9 | 2.83 | 1.43 | 10.77 | 23.4 | 58.4 | 17 | 8.5 % | 170 197 |
| 2560x1440 before | 3.63 | 1.48 | 14.15 | 37.3 | 109.0 | 59 | 10.9 % | 277 672 |
| 2560x1440 V9 | 3.53 | 1.44 | 15.19 | 34.57 | 64.1 | 57 | 10.6 % | 244 604 |

What changed, and what each fixed (every change pixel-identical to V8, or closer to the full recomposition where V8 left a
stale pixel - `tests/test_arena_perf.py` runs both compositors in lockstep over whole matches and compares every frame):

- sprites are cut to their opaque box once per cached sprite (`_sprite_trim`): a fighter's dirty rect, premultiply and
  upload shrink from the 256 px cell to the body (12 % fewer pixels written per frame);
- `_merge` pools small rects per 64 px cell past 64 of them and reduces the excess from a heap of pair costs: a shatter's
  100+ debris rects cost up to 33 ms in the merge alone, now under 1 ms (the 159 ms max frame was that plus a forge);
- the forge decodes both fighters' unarmed sheets before the first frame (a 130 ms stall on the first forge);
- a flash frame is one window fill plus the drawables (no backdrop), and the second and later frames of one steady flash
  write only what moved under it;
- the letterbox bars are recognised by a mark on the image, not by `id()` (a freed id was reused by a sprite once).

The frames still over 33 ms are the final-KO focus lines over the whole monitor (a full-screen composite by design) and the
first morph frame of a forge; at 1440p the lens region alone is 1.6 M px. 60 fps is reached between those frames; the fps
ladder keeps the CPU under the budget on the frames that are not.

### Task-finished boost, sound, frame data (V9)

- **Boost.** When an agent finishes a task, its slot writes a short-lived marker (`boost`, 20 s) into its bus file. A
  running arena polls both bus files every 0.5 s and opens the next exchange with that fighter's signature super (the first
  two exchanges after the marker, once per marker). Nothing else is shared between the processes; `tests/test_boost.py`.
- **Sound.** Off by default; `python minis.py sound on`. The arena plays its own events (hits by power, clashes, whooshes,
  the KO, the forge crackle and shatter, the round bell) through `minis_core/sfx.py`; rate-limited, quiet while paused.
- **Frame data.** The same model as the taskbar (`docs/ANIMATION-NOTES.md` section 12): each hit freezes both fighters for
  a hitlag that grows with its damage, adds to a damage % shown under the HUD names, knocks back along the move's angle with
  a speed from damage, % and weight (x 7 px per unit per frame), stuns for 0.4 frames per unit of knockback, knocks down
  past the tumble line, pushes a blocker back with shieldstun; the shake follows the knockback.

## Verification

- `tests/test_arena.py` holds the V4 to V7 arena tests, 50 in all. The V7 classes are:
  - `Options`: validation and layering, best of 1 and 5, endless with seconds, the VS card and the outro perch
  - `Stage7`: wall bounce, tech, ledge grab and smooth climb, knock-through crack, linear skid, meteor and crater cap,
    double-jump hover, recovery, shard platform, letter rain
  - `Camera7`: the lens never leaves the monitor and eases with no jumps, a second punch continues the first, the
    letterbox eases and is drawn behind the fighters, colour flashes and ink frames obey `flashes`
  - `Intensity7`: effect counts scale with the intensity
  - `Clash7`: event order, the winner's damage, the sway, the per-match cap
  - `SetPieces7`: 2 to 4 per match, every set piece for two pairings, slot fallbacks, every element
  - `Moves7`: traits, and an unknown attack kind still plays
  - `VisualOnly7`: no window API is ever called
- `tests/test_forge.py` holds the V8 desktop-weapons tests: the shape of every family, pixels clipped to the silhouette with
  a rim, progressive cracks, the whole cut / hole / lift / morph / arm / swing / crack / shatter / debris lifecycle, uses
  running out, a thrown slab, a loose piece picked up, shape mode, moved windows, forges per intensity, `forge off` = zero
  forges, pacing with forging on, the forge inside `stance_finisher`, hand tracking (`HandTracking`: unarmed sheet, the
  weapon at every frame's grip / grip2 for blade, greatsword, spear, club, twin blades and shards, the native weapon back
  after the shatter), frame indices from metadata (`FramesFromMetadata`: no referenced frame past its row, hits equal
  hit_frame, hang / climb use the jump row's own poses), and privacy: `disable()` drops every derived image and
  the overlay repaints without them, `ScreenImage` never pickles, `grab_monitor` refuses under tests, a real headless
  `run_arena` with every write path recorded (open, Path writes, os.write, Image.save, json, logging) leaks no byte run of
  the synthetic screen, `arena capture` refuses while pixels are held and a `forge off` overlay carries none, and
  `VisualOnly8` (no window API while forging). Every "screen" in those tests is a synthetic image; the real screen is never
  grabbed.
- V9: `tests/test_arena_perf.py` (the V8 compositor in lockstep: every frame identical or closer to the full recomposition,
  fewer pixels written, a steady flash written once, sprite trimming is identity, the merge covers every input rect, the
  unarmed sheets are warm), the freeze-mode hole's repaint rect covering every painted pixel (`tests/test_arena.py`
  `Destruction`), `tests/test_boost.py` (the marker's lifetime, the poll, one super per marker, a stale marker ignored, no
  bus read without a config) and `test_arena_hits_use_the_same_model` in `tests/test_framedata.py` (the arena's hitlag,
  hitstun and knockback equal the shared formulas).
- Previews are rendered headless onto a RAM surface over a synthetic busy desktop, never a screen grab. The doc images are
  made by `tools/doc_images.py` (`arena_overview()`, `arena_v7_imgs()`, `arena_forge_imgs()`;
  `python tools/doc_images.py --only forge`, with `FORGE_QA_DIR=<folder>` to dump every frame of the forge, swing, crack and
  shatter at 1x and 2x for frame-by-frame review).
