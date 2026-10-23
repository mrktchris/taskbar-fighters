# Fighters learn (2026-10-22)

Owner: "make the fighters teach themselves new moves too - somehow figure that out."

Every program's fighter keeps a small skill memory and grows its own move set from what really happens to it on the
taskbar: the moves it throws, the moves that hit it, the opponents it watches, and the shadowboxing it already does while
its agent works. A new move is never drawn by hand and never shipped: it is generated from the existing pose keyframes
by a deterministic operator, has to pass the same QA bars as the shipped sheets, and is rebuilt from a handful of numbers on
whichever machine needs it.

Everything is offline and numbers-only: no network, no prompts, nothing read from the agents' content. The memory holds
move ids, character ids, program ids, operator names, counters and seeds (`tests/test_learning.py` `Privacy` audits every
leaf of the file).

Files: `minis_core/learning.py` (the loop, the overlay atlas, the views, the shared toast row), `minis_core/movegen.py`
(the no-new-art operators, their QA and the cache: in every install), `art/evolve.py` (the redrawn operators, their QA and
the review sheets: source checkout only), `tests/test_learning.py`, this file, and the hooks listed under [Hooks](#hooks).

**Every install learns.** A pip install and the Windows zip learn through `retime`, `twin` and `feint`, which reuse the
frames the character's sheet already has. Only a source checkout also redraws moves (`amplify`, `spin`, `mimic`), because
those go through the rig in `art/`; without it `learning.redraws()` is False, so a packaged install never learns a
borrowed move and never starts a build process.

## What learns from what

| event | experience | threshold | what is learned |
| --- | --- | --- | --- |
| **Mastery** | the move thrown in fights (1 each) and in shadowboxing reps (1/2 each) | 30 | an evolved variant of that move: `retime` (wind-up a third shorter, contact held 20 ms longer: "Iai Slash II"), `twin` (the first cut is pulled, a re-chamber, the second cut lands: "Twin Cross"), `feint` (a stutter between two wind-up keys, then the real strike: "Low Kick Feint"), or with the rig `amplify` ("Grand Cross": a longer reach, a bigger arc, a deeper lunge) / `spin` ("Spiral Iai Slash": a torso spin wound into the strike) |
| **Counter-learning** | landed hits taken, by kind (`hit`: slash / blunt / pierce) | 45 of one kind | a sharpened riposte that answers that kind: after a parry of a move of that kind the fighter ripostes with it first, and it parries that kind 1.6x as often ("Riposte vs Pierce") |
| **Mimicry** | an opponent's weapon move, watched or taken (per opponent program) | 24 | a borrowed copy: the opponent's poses drawn with the learner's own body and weapon, one power lower ("Borrowed Kunai Toss": the ronin's crude take on the ninja's throw). Render tier only; never a move the learner already has |
| **Invention** | shadowbox reps while its agent works | a trial every 90 reps; learned after 40 reps of it | a seeded `(base, operator, seed)` it tries out between reps (a third of the reps play the trial); learned once practised enough ("Jab Drift") |

Only one new move per bout, and only every **15 bouts** at most; mastery, counter and mimicry take turns at that slot.
A kit holds **6** learned moves: at most 3 evolved variants and 2 counters. When the kit is full, nothing new is learned
until a move has gone 25 bouts unused; that move then makes room. Unused moves lose weight: after 25 idle bouts the weight
halves every 10 more, and after 60 they are forgotten (counters fire only after a parry, so they age three times slower).
The pick weight of a learned strike grows with mastery: 0.6 + 0.15 per level, where a level is 30 more uses, capped at 1.2.
The shared strikes weigh 0.4-0.66 and the weapon-family moves 0.25-1.0. A learned move is one more choice in the no-repeat
picker, never a forced one.

Learning follows the program *and* the skin: a kit learned as the Knight stays home when that program is drawn as Claude.

## The visible moments

- **LEARNED: \<MOVE\>.** When a fighter learns something, the next time it stands at home and awake it plays the new move
  once under a green `LEARNED: IAI SLASH II` banner (`Learner.home`, `Learner.banner_image`: the same text-banner type as
  the winner's name banner).
- **Scoreboard toast.** `LEARNED Claude: Iai Slash II` for 3 s per new move, in the scoreboard's toast row, which it shares with
  the achievement toasts (`UNLOCKED Self-Taught`) through `learning.ToastSlot`: one queue, in arrival order, each toast
  held for its full 3 s, never two at once. The first look seeds silently, so an old file never floods the board.
- **Move book.** A LEARNED tab after FINISHERS: every move learned in that skin, drawn animated, typed mastered / counter /
  borrowed / invented, the footer saying who learned it and how ("Claude mastered iai slash (31 thrown in fights)").
  Learned moves count as seen and stay out of "N of M seen", since the tab grows.
- **Hover card.** One green line, `learned 4 moves`, under the record.
- **Achievements.** *Self-Taught* (a fighter teaches itself a new move) and *Student of the Game* (a fighter learns a
  counter to the attack that keeps hitting it), Discovery badges with their criteria and progress in the open, read from
  `learning.stats()` (counts of learned moves, nothing about usage).
- **Fights.** Learned moves appear in the move picker in later fights; the remap rows play the shipped frames in a new
  order and timing, and the render rows play rig-drawn frames from the cache.
- **`python minis.py learned [program]`.** Every learned move, how it was learned ("mastered iai slash (31 thrown in
  fights)", "learned the hard way: hit by pierce attacks 45 times", "borrowed from Codex after watching its kunai toss",
  "invented while shadowboxing (a twin variation of jab)"), uses and level, the trial being practised and any pending build.

## Procedural move synthesis (`minis_core/movegen.py`, `art/evolve.py`)

A variant is `(character, base move, operator, seed[, source character])`. Its id is derived from those numbers
(`iai_slash_ii`, `cross_twin`, `jab_x2d6` for an invention, `riposte_vs884` for a counter), and so is its display name.
Names are generic and original.

**Remap tier (`retime`, `twin`, `feint`; `minis_core/movegen.py`, every install).** These re-sequence and re-time the base row's own frames. A learned row is an
anim.json-shaped entry whose frames carry `src` (the base frame to draw). No rig, no cache, no image is written. `retime`
warps a row's `air` curve with its frames, so a retimed leap still lifts on the same frames.

**Render tier (`amplify`, `spin`, `mimic`; `art/evolve.py`, source checkout only).** These edit the pose keys (hand targets
scaled; for `spin` a side-on coil and a BACK-TURNED key - the coil drawn from the other facing with the hip kept on the
anchor column, so hips and shoulders swap - before the smear sweeps round from behind the back; another family's poses) and run them through every pass the shipped moves go through: `fit_weapons`, `_fit_chain`,
`settle_to_stance`, `inbetween_weapons`, `settle_frame` and `annotate_contact`. The real builder (`build_fighters.render_move`)
then draws them at 64 and 128 px in both facings, including the V9 pixel clean-up. Frames go to
`<data dir>/learned/<character>/<id>.r1.png|.r2.png` plus `<id>.json` (frame timings, reach, contact metadata). The cache is
capped at 24 MB with LRU eviction (`index.json` keeps the last-use times) and is never written into the repo. A fighter
process never renders: `learning.spawn_build` runs `python art/evolve.py build ...` out of process (windowless on Windows),
the unlock waits in `pending` until the files exist, and a rejected build leaves `<id>.rejected.json`; a mastery variant
then falls back to its remap form.

**The QA gate.** A variant is never learned unless it passes everything below.

| check | bar |
| --- | --- |
| timing (both tiers) | a smear before the contact, no smear held over 110 ms, the wind-up longer than the smear, no two consecutive frames of equal duration, hitstop >= 150 ms on the contact, at most 12 frames (the fluid-pass rules of `test_v5_timing_rules_on_every_strike`) |
| remap silhouettes | the two wind-up keys a feint stutters between differ as silhouettes (IoU < 0.65); a twin's re-chamber differs from its smear (IoU < 0.88) |
| anchors | between two grounded frames without authored travel the soles stay on the same row (<= 1 px at 64, <= 2 at 128) |
| weapon attached | weapon pixels within 3 px (x res) of the hand on every frame that holds one |
| silhouette | the contact pose differs from idle (IoU < 0.8) and from the last wind-up key (IoU < 0.92); the smear draws its crescent |
| novelty | at least one frame no base frame matches closely (IoU < 0.87): an operator whose edits the fit passes undid is the base move again |
| a spin turns | a spin contains a frame that matches the base move's OTHER facing at least 0.05 IoU better than its own facing (the back-turned frame); a near-symmetric coil that cannot read as a turn is rejected |
| no stray pixels | no opaque pixel off the body, weapon and effects on any frame that is not a smear (or the frame after one), unless the key authors an afterimage (`ghost`): smudges and leftover copies fail |
| reach | measured from the striking pixels (`hit_reach`), at least 10 px x res; a variant whose contact frame cannot be measured fails (a check that cannot run never passes) |
| cell | nothing touches the top edge or dips below the outline row, nothing leaves the cell |
| colours | inside the cap (31 / 63 plus transparency), and no colour the character's own sheet does not already have |
| facings and sizes | the left facing is the mirror (bounding boxes), checked at 64 and 128 px |

`learning.load_row` repeats the remap checks at the atlas's own resolution before a row is built, so a variant that fails
can never reach a fight.

## Determinism between the two fighter processes

The inviter reads `learning.json` at plan time and writes both sides' kits into the plan:
`plan['learn'] = {'v': <file version>, 'kit': {slot: {move id: {'w', 'kind', 'vs', 'spec'}}}}`. Both processes call
`learning.prepare(plan, atlases)` in `_possible` before they commit, and build every named row from its `spec`. The
learned-move state is therefore read once, travels inside the shared plan, and cannot drift between the invite and the
accept. A plan whose rows cannot be built on the accepting side (a missing render, an id that does not match its spec, a
row that fails QA here) is declined, never played with a different kit. `TwoProcesses` runs the same plan in two separate
interpreters with different hash seeds and checks that both build identical rows and an identical timeline hash, equal to
the in-process one.

Practice draws come from the program's own seed and its rep count, never the brain's rng, so the shadowbox sequence and
every existing seeded behaviour are unchanged. With no kit in the plan, `Picker` draws exactly as V9 did (test:
`test_a_picker_without_a_kit_is_unchanged`).

Both fighter processes write `learning.json` when a bout ends, each folding its own side only, under a lock file
(`learning.json.lock`, stale after 5 s) with an atomic replace; `v` counts every write.

## Trust boundaries (Codex review 3)

`learning.json` and the bus plan are files another process (or a person) can edit, so nothing read from them is trusted:

- **Ids.** Every character, move and source id is checked against `[a-z0-9_]{1,48}` (`movegen.valid_id`) before it can
  name anything. `movegen.cache_paths` resolves every path and refuses one outside `<data dir>/learned`, so a spec like
  `["../../outside", ...]` can never probe or load a file elsewhere. `prepare()` requires each spec's character to be the
  plan's fighter on that slot, and the spec to derive the kit's move id.
- **Kits.** Each entry is validated in `prepare()` (inside `brain._possible`, so before `_accept` emits anything): a
  finite weight in 0..1.2, a known kind and hit kind, at most 6 entries per slot. `kit_for` drops damaged entries from
  the file, and `Picker` skips a bad weight instead of raising.
- **Render workers.** `spawn_build` keeps its child handles: one build per spec, at most 2 at once, each killed after
  180 s (only our own children) and reaped on the next home tick and at exit. A pending build whose worker is gone is
  asked again.
- **Cache writes.** A build writes every file under a temp name and renames it into place, metadata last; a failure
  removes everything it wrote. Eviction counts every file in the cache and first removes orphan sheets (no metadata)
  and temp files left by a crash.
- **The lock.** `learning.update` uses `minis_core/filelock.py`, which now writes an owner token into the lock file. A
  holder deletes the lock only while it still carries its own token, so a holder that stalled past the 5 s takeover can
  no longer delete the next owner's lock. (On Windows an open lock file cannot be deleted at all, so that race exists
  only on macOS / Linux; the end-to-end test runs there.)

## Data format (`<data dir>/learning.json`)

```json
{"version": 1, "v": 412,
 "programs": {"claude": {
   "character": "claude", "seed": 182736451, "bouts": 61, "matches": 40, "wins": 22, "losses": 18,
   "practice": 233, "trials": 2, "forgotten": 0, "last_learn": 52, "last_invention": 180,
   "used":   {"iai_slash": {"n": 31, "hit": 14, "whiff": 3, "block": 14, "prac": 12}},
   "taken":  {"pierce": 47, "slash": 30},
   "seen":   {"codex:kunai_toss": 19},
   "pieces": {"blade_lock": 3},
   "learned": {"iai_slash_ii": {"how": "mastery", "spec": ["claude", "iai_slash", "retime", 52811, null, "mastery"],
                                "kind": "strike", "vs": null, "level": 1, "uses": 34, "last": 60, "ts": 1792700000.0}},
   "pending": [{"spec": ["claude", "cross", "amplify", 9132, null, "mastery"], "how": "mastery", "kind": "strike",
                "vs": null, "fallback": ["claude", "cross", "retime", 9132, null, "mastery"], "since": 58}],
   "trial": {"spec": ["claude", "jab", "twin", 811290, null, "invention"], "reps": 12, "since": 200}}}}
```

`spec` = `[character, base move, operator, seed, source character | null, how]`. Program ids are source ids (`claude`,
`codex`, `grok`, `bot`), the same ids `record.json` uses. The Brain publishes its program id on the bus (`who`), which is
how the opponent's id reaches the other process.

## Hooks

Everything outside the four new files, listed for the fight-quality integration. Each one is a single call or a parameter
with a default that keeps V9 behaviour.

| file | hook | what it does |
| --- | --- | --- |
| `minis_core/choreo.py` | `Picker(rng, atlas, learned=None)` | the slot's kit; `strikes()` adds learned strikes at their weights |
| `minis_core/choreo.py` | `Picker.counter_for(meta)`, `Picker.parry_k(meta)` | a learned counter answers its hit kind; parry weight x1.6 against it |
| `minis_core/choreo.py` | `_resolve(..., parry_k=1.0)` | the parry weight in the defender's answer is scaled by `parry_k` (two call sites pass `dfn.parry_k(...)`) |
| `minis_core/choreo.py` | `plan_exchange`: `rip = dfn.counter_for(...) or first_of_type(D, 'riposte')` | after a parry, a learned counter of that kind ripostes first |
| `minis_core/rounds.py` | `Bout.__init__`: `kits = plan['learn']['kit']`, `Picker(..., kits.get(s))` | each slot's kit into its picker |
| `minis_core/brain.py` | `import learning`; `Brain.__init__`: `self.atlases = learning.wrap_library(atlases)`, `self.atlas = self.atlases.wrap(atlas)`, `self.learner = learning.Learner(self)` | every atlas the brain serves carries the learned rows |
| `minis_core/brain.py` | `publish()`: `who=` | the program id on the bus |
| `minis_core/brain.py` | `view()`: banner kind `learned` -> `learner.banner_image` | the LEARNED banner |
| `minis_core/brain.py` | `set_atlas()`: `atlas = self.atlases.wrap(atlas)` | a skin change keeps the overlay |
| `minis_core/brain.py` | `_plan()`: `self.learner.plan(plan)` for spar / clash / match | kits into the plan (inviter) |
| `minis_core/brain.py` | `_possible()`: `... and self.learner.possible(plan)` | rows loaded before committing (both sides) |
| `minis_core/brain.py` | `_commit()`: `script['summary']` | the bout summary kept for the end of the bout |
| `minis_core/brain.py` | `_tick_script()` at `t_end`: `self.learner.after_bout(sc, now)` | experience folded, unlock queued |
| `minis_core/brain.py` | `_tick_home()` shadowboxing: `mv = self.learner.practice(mv, now)`; then `self.learner.home(now)` | practice and invention; the learned moment |
| `minis.py` | `Fighter.resolve_size`: `self.hd = learning.wrap_library(Library(hd=True))` | learned rows at 128 px |
| `minis.py` | `Fighter.setup`: `self.brain.learner.on = not os.environ.get('MINIS_LEARN_OFF')` | only the real fighter process writes experience; test brains and the simulator never do |
| `minis.py` | `learned [program]` subcommand | the CLI listing |
| `minis.py` | `Scoreboard`: `self.toaster = learning.toast_slot(wall=...)` (was `achievements.Toaster`) | achievements and learned moves share the toast row |
| `minis_core/scoreboard.py` | `_render`: `state['toast']` may be `(kind, text)`; `learned` draws `LEARNED` with a green mark | the LEARNED toast; a bare string is still a badge |
| `minis_core/collection.py` | `SECTIONS` + `('learned', 'LEARNED', ())`; `entries()` skips `type: learned` rows in the other tabs and fills `learned_entries(atlas)`; `counts()` skips the tab; `Book.__init__` wraps its library; `is_seen` is True for a learned entry | the move book's LEARNED tab |
| `minis_core/hovercard.py`, `minis_core/ux_runtime.py` | `lines()`: `info['learned']`; `card_info()`: `info['learned'] = learning.summary_line(src)` | the hover card line |
| `minis_core/filelock.py` | the lock file carries an owner token; `_release` deletes it only while it is still ours | a stalled holder never deletes a newer owner's lock (all users: learning.json, ux.json, collection.json) |
| `minis_core/achievements.py` | `stats()` + `learn=_learning_stats()`; badges `self_taught`, `student`; `Toaster._sig` also watches `learning.json` | the two badges |

`Learner` is off by default, so `sim.py`, the tests and the preview tools never touch `learning.json`. `MINIS_LEARN_OFF=1`
turns learning off in a real run; `MINIS_LEARN_NO_RENDER=1` keeps it to the remap tier (the tests set it).

Not hooked yet:
- **The arena** (`minis_core/arena.py`, `Arena.__init__` `self.pick`): it builds its own pickers, so learned moves do not
  appear there. Hook: pass `learning.kit_for(program, character)` per side into `choreo.Picker`, and wrap the arena's
  atlases with `learning.wrap_atlases`.
- **Set pieces** never use learned moves (they fill slots by `type`; learned rows have `type: learned`). Intentional.

## Numbers

**300-match simulation** (`python -m minis_core.learning sim 300`: four programs on four characters, every ordered pair,
3 shadowbox reps between matches, the real `rounds.make_match`, remap tier only). Before is the same 300 matches with no
learning.

| | before | after |
| --- | ---: | ---: |
| learned moves per program (match 25 / 50 / 100 / 150 / 225 / 300) | - | 0-1 / 1-2 / 3 / 4-5 / 6 / 6 (the cap) |
| first learned move (match no., per program) | - | 16 / 20 / 29 / 33 |
| how they were learned (all four programs, 24 moves) | - | 12 mastery, 8 counter, 4 invention |
| distinct attack moves per character | 17-18 | 23-24 |
| most-used move's share (worst character) | 13.3 % | 12.0 % |
| learned moves' share of all attacks | - | 6-9 % |
| moves forgotten | - | 0 (every learned move stayed in use; forgetting is covered by `test_the_kit_never_exceeds_its_cap_and_unused_moves_decay_then_go`) |
| privacy audit of learning.json | - | clean |

`Sim.test_300_match_balance` asserts the bounds: every kit at most 6, no move over 25 %, learned moves between 3 % and
35 % of a fighter's attacks, at least two learning sources, and a clean privacy audit.

**Frame-by-frame review (4x, three characters).** `python art/evolve.py review <character> --out <dir> [--onion]` writes one
sheet per variant: right and left facing at 64 px (4x) and 128 px (2x), ms / HIT / smear labels, a 1x taskbar strip, and
with `--onion` the previous frame's silhouette in dark red behind each frame (a review aid, labelled; never in the sprite).
Claude, Codex and Knight: 83 variants pass. Five defects found by eye became QA rules:
1. *Feints that are a stall.* Every jab feint and the heavies' ground-slam feint stuttered between two wind-up keys 1-2 px
   apart (the knight's ground slam: frames 0, 1, 0, 1), which reads as a pause, not a fake. Silhouette bar: IoU < 0.65
   (rejects 12 of the three characters' feints; the kicks', sweeps' and spins' chamber feints pass).
2. *A variant the fit passes undid.* The knight's amplified cleave rendered as the plain cleave (`fit_weapons` pulls a
   greatsword's hands back in). Novelty bar: IoU < 0.87 (rejects 8 amplify variants, among them every jab and riposte
   amplify).
3. *Borrowing what you already have.* The knight "borrowed" the barbarian's cleave, which is its own family move. Mimicry
   never offers a move the learner has.
4. *A spin that does not turn* (coordinator review of `claude-iai_slash_spiral-4x.png`). The first spin inserted only a
   side-on coil and read as the base iai slash. It now has a back-turned frame and a crescent from behind the back, and the
   rotation rule rejects spins that cannot read as a turn (12 pass, 9 rejected: every jab and low-kick spin, near-symmetric
   coils). Before / after: `qa/learning/claude-iai_slash_spiral-before-after.png`.
5. *Dark-red smudges behind the body* (same review). Audited: they were the review sheet's onion skin, not sprite pixels
   (no semi-transparent pixel, no colour outside the character's sheet, no afterimage key on any of the frames). The onion
   skin is now opt-in and labelled, and the gate has a stray-pixel budget so a real smudge fails automatically (a test
   injects one).

Reviewed sheets kept in the repo (one per operator per character): `qa/learning/*-4x.png`, plus the before / after above
and `qa/learning/surfaces-2x.png` (the LEARNED tab, the hover card and both toasts). The full set is regenerated by the
command above.

## Open items

- Not wired: the arena (above).
- The render tier has only run in the review tool and the tests, not inside a long live session. `spawn_build` starts one
  Python process per queued build (a few per week at these thresholds); an owner run should confirm it stays quiet.
- Inventions and mimicry depend on practice and on meeting the same opponent, so in real use they come slower than
  mastery. The thresholds live at the top of `minis_core/learning.py`.
