# Fighter move list

Generated from `assets/*/anim.json` by `tools/gen_movelist.py`; every number below is read from the real sheets. "Used" is decided from the planner: a move says *yes* only if `minis_core/brain.py` triggers it or it is a signature move (the planner reads each character's signature strike / special / super from its atlas).

## At a glance

- **13 characters**: Claude, Codex, Gemini, Cursor, Ollama, LM Studio, Agent, Barbarian, Knight, Kunoichi, Monk, Nomad, Oni. Each has the same **56 shared moves**, its **signature moves**, and **its weapon family's moves** (V7: 8-10 per character; 68 moves, 393 frames for Claude).
- 56 of 56 shared moves are triggered by the planner today, and every signature move is; 0 shared moves are built and waiting for a trigger (listed at the end).
- Which character appears is decided by the **director** from what is running (at most two at a time, slot `a` left and slot `b` right).

## The roster

| character | plate tag | accent | strike | special (projectile) | super | ultimate (40 dmg) | shown for |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude | `/reverse` | #F0A184 | `spin_kick` | `slash_wave` | `reverse` | `radiant_beam` | Claude Code transcripts |
| Codex | `$reverse` | #A99DFF | `ground_pound` | `deploy` | `sudo` | `spiral_orb` | Codex transcripts (CLI, Emdash, desktop app) |
| Gemini | `*gemini` | #7FA8F2 | `spin_kick` | `star_shot` | `twin_flash` | `crescent_fang` | Gemini |
| Cursor | `>cursor` | #5FD3F3 | `ground_pound` | `tab_bolt` | `autocomplete` | `grapple_strike` | Cursor |
| Ollama | `ollama` | #E9E2D2 | `ground_pound` | `pull_shot` | `serve` | `gale_rend` | Ollama |
| LM Studio | `lmstudio` | #7CF8EA | `spin_kick` | `load_wave` | `hot_swap` | `awakening` | LM Studio |
| Agent | `agent` | #E0C46C | `spin_kick` | `energy_bolt` | `overclock` | `star_core` | Windsurf, aider, opencode, Copilot CLI, Qwen Code, Perplexity, Grok (and any character whose art is missing) |
| Barbarian | `barbarian` | #FF8A4A | `axe_spin` | `axe_toss` | `berserk` | `earthsplitter` | - |
| Knight | `knight` | #7FA8FF | `crusher` | `sword_wave` | `valor` | `holy_crescent` | - |
| Kunoichi | `kunoichi` | #FF5A7A | `fan_whirl` | `petal_shot` | `vanish` | `petal_dance` | - |
| Monk | `monk` | #F2C14E | `palm_crash` | `chi_bolt` | `meditate` | `chi_sphere` | - |
| Nomad | `nomad` | #2A9D8F | `ring_spin` | `chakram_throw` | `mirage` | `ring_storm` | - |
| Oni | `oni` | #E04A3A | `club_slam` | `oni_fire` | `rampage` | `oni_roar` | - |

### Signature moves

| character | move | role | frames | length | what it is |
| --- | --- | --- | ---: | ---: | --- |
| Claude | `spin_kick` | strike | 8 | 920 ms | Claude's signature spinning kick. · reach 26 px, contact at frame 4 |
| Claude | `slash_wave` | special | 7 | 900 ms | Throws a "/" slash wave across the taskbar. Costs nothing; looks cool. |
| Claude | `reverse` | super | 7 | 760 ms | "/reverse": rewinds to where it stood a second ago, dodging everything. Afterimage trail. |
| Claude | `radiant_beam` | ultimate | 8 | 2060 ms | Cups both hands at the hip, charges for a full second, then fires a horizontal beam the width of the taskbar. · reach 29 px, contact at frame 6 · 40 damage · effects: `radiant_beam_charge`, `radiant_beam` |
| Codex | `ground_pound` | strike | 8 | 1090 ms | Codex's heavy leaping slam with a ground shockwave. · reach 19 px, contact at frame 5 |
| Codex | `deploy` | special | 8 | 1010 ms | Types a command and hits ENTER: fires a ">_" bolt across the taskbar. |
| Codex | `sudo` | super | 7 | 890 ms | "$reverse": raises a giant $ and powers up with elevated permissions. |
| Codex | `spiral_orb` | ultimate | 8 | 1280 ms | Spins a sphere of energy in one hand, dashes in with afterimages and drives it home in a spiral burst. · reach 27 px, contact at frame 6 · 40 damage · effects: `spiral_orb_core`, `spiral_orb_burst` |
| Gemini | `spin_kick` | strike | 8 | 920 ms | Gemini's spinning kick, both blades whipping round. · reach 26 px, contact at frame 4 |
| Gemini | `star_shot` | special | 7 | 900 ms | Two-handed push that fires a "*" sparkle along the taskbar. |
| Gemini | `twin_flash` | super | 7 | 760 ms | Flash-steps back a second in time, leaving a sparkle and an afterimage trail. |
| Gemini | `crescent_fang` | ultimate | 8 | 1440 ms | Raises an arm, gathers energy and swings down a giant crescent slash wave. · reach 30 px, contact at frame 5 · 40 damage · effects: `crescent_fang_charge`, `crescent_fang` |
| Cursor | `ground_pound` | strike | 8 | 1090 ms | Cursor's leaping slam with a ground shockwave. · reach 19 px, contact at frame 5 |
| Cursor | `tab_bolt` | special | 8 | 1010 ms | Accepts a suggestion and hits TAB: fires a ">|" caret bolt across the taskbar. |
| Cursor | `autocomplete` | super | 7 | 890 ms | Raises a giant ">" and powers up: the whole line completes itself. |
| Cursor | `grapple_strike` | ultimate | 8 | 1010 ms | Fires two grapple lines, zips across them and finishes with a spinning cross slash. · reach 28 px, contact at frame 6 · 40 damage · effects: `grapple_lines`, `grapple_slash` |
| Ollama | `ground_pound` | strike | 8 | 1090 ms | Ollama's llama stomp with a ground shockwave. · reach 19 px, contact at frame 5 |
| Ollama | `pull_shot` | special | 8 | 1010 ms | "ollama pull": hurls a wool-white orb across the taskbar. |
| Ollama | `serve` | super | 7 | 890 ms | "ollama serve": raises a giant "o" and powers up, local and unstoppable. |
| Ollama | `gale_rend` | ultimate | 8 | 1540 ms | Raises both arms, then slams down and rips three claws of energy along the ground. · reach 26 px, contact at frame 5 · 40 damage · effects: `gale_rend_charge`, `gale_rend` |
| LM Studio | `spin_kick` | strike | 8 | 920 ms | LM Studio's spinning kick, the energy blade trailing. · reach 26 px, contact at frame 4 |
| LM Studio | `load_wave` | special | 7 | 900 ms | Loads a model and throws it as a teal-and-magenta wave across the taskbar. |
| LM Studio | `hot_swap` | super | 8 | 850 ms | Hot-swaps back to where it stood a second ago, afterimage trail and a giant "L". |
| LM Studio | `awakening` | ultimate | 8 | 1270 ms | Releases a pillar of aura, then lands three flash-step strikes faster than the eye. · reach 28 px, contact at frame 4 · 40 damage · effects: `awakening_aura`, `awakening_slash` |
| Agent | `spin_kick` | strike | 8 | 920 ms | A spinning kick: every agent learns this one. · reach 26 px, contact at frame 4 |
| Agent | `energy_bolt` | special | 8 | 1010 ms | Types a command and fires an energy orb across the taskbar. |
| Agent | `overclock` | super | 7 | 890 ms | Raises a giant "+" and powers up: everything runs faster. |
| Agent | `star_core` | ultimate | 8 | 1760 ms | Raises both hands, gathers a huge slow ball of energy overhead and hurls it. · reach 24 px, contact at frame 5 · 40 damage · effects: `star_core_orb`, `star_core` |
| Barbarian | `axe_spin` | strike | 8 | 920 ms | A wild spinning kick, axe swinging round with it. · reach 27 px, contact at frame 4 |
| Barbarian | `axe_toss` | special | 8 | 1010 ms | Hurls a spinning hand-axe across the taskbar. |
| Barbarian | `berserk` | super | 7 | 890 ms | Roars under a giant "V" and goes berserk. |
| Barbarian | `earthsplitter` | ultimate | 8 | 1540 ms | Raises the axe, then splits the ground with three tearing shock claws. · reach 23 px, contact at frame 5 · 40 damage · effects: `gale_rend_charge`, `gale_rend` |
| Knight | `crusher` | strike | 8 | 1090 ms | Leaps and brings the greatsword down with a ground-shaking crash. · reach 19 px, contact at frame 5 |
| Knight | `sword_wave` | special | 7 | 900 ms | A two-handed sweep that sends a steel wave across the taskbar. |
| Knight | `valor` | super | 7 | 890 ms | Raises the greatsword under a giant "T" and steels itself. |
| Knight | `holy_crescent` | ultimate | 8 | 1440 ms | Raises the greatsword, gathers light and cleaves a giant crescent down the taskbar. · reach 31 px, contact at frame 5 · 40 damage · effects: `crescent_fang_charge`, `crescent_fang` |
| Kunoichi | `fan_whirl` | strike | 8 | 920 ms | A spinning kick with both fans snapping open. · reach 26 px, contact at frame 4 |
| Kunoichi | `petal_shot` | special | 7 | 900 ms | Sweeps a fan and sends a spinning blade-petal across the taskbar. |
| Kunoichi | `vanish` | super | 7 | 760 ms | Vanishes back a second in a swirl of petals, a giant "x" where she stood. |
| Kunoichi | `petal_dance` | ultimate | 8 | 1270 ms | A burst of crimson aura, then three flash-step fan cuts faster than the eye. · reach 29 px, contact at frame 4 · 40 damage · effects: `awakening_aura`, `awakening_slash` |
| Monk | `palm_crash` | strike | 8 | 1090 ms | Leaps and drives both tonfa into the ground. · reach 19 px, contact at frame 5 |
| Monk | `chi_bolt` | special | 8 | 1010 ms | Thrusts a tonfa and fires a ball of chi across the taskbar. |
| Monk | `meditate` | super | 7 | 890 ms | Centres itself under a giant "O"; the aura flares. |
| Monk | `chi_sphere` | ultimate | 8 | 1760 ms | Raises both tonfa, gathers a huge sphere of chi overhead and hurls it. · reach 28 px, contact at frame 5 · 40 damage · effects: `star_core_orb`, `star_core` |
| Nomad | `ring_spin` | strike | 8 | 920 ms | A spinning kick, both chakrams whirling. · reach 26 px, contact at frame 4 |
| Nomad | `chakram_throw` | special | 7 | 900 ms | Whips a chakram across the taskbar. |
| Nomad | `mirage` | super | 7 | 760 ms | Slips back a second like a heat mirage, a giant "Y" left behind. |
| Nomad | `ring_storm` | ultimate | 8 | 1010 ms | Throws two chakrams on lines, zips after them and finishes with a spinning cross cut. · reach 22 px, contact at frame 6 · 40 damage · effects: `grapple_lines`, `grapple_slash` |
| Oni | `club_slam` | strike | 8 | 1090 ms | Leaps and smashes the kanabo into the ground. · reach 19 px, contact at frame 5 |
| Oni | `oni_fire` | special | 8 | 1010 ms | Spits a ball of oni-fire across the taskbar. |
| Oni | `rampage` | super | 7 | 890 ms | Swells under a giant "H", eyes blazing. |
| Oni | `oni_roar` | ultimate | 8 | 2060 ms | Plants the kanabo, draws a breath for a full second and roars a beam of fire across the taskbar. · reach 33 px, contact at frame 6 · 40 damage · effects: `radiant_beam_charge`, `radiant_beam` |

## Every fighter, move by move (V7)

Each fighter fights like its weapon: the shared strikes are swung with it, and every character has its weapon family's own moves plus the shared move *types* (air juggle, throw, dash-through, guard break, riposte, a taunt variant).  The input labels are fighting-game notation for reading the list (→ forward, ← back, ↓ down, ↑ up); nothing reads them as input - the choreographer picks every move itself.  Damage tiers: light 12, medium 24, heavy 36, super 24, ultimate 40.  "Frames" and "length" are read from the real sheet; contact-frame and reach notes come from the art.

### Claude - blade (katana)

3-hit string: `riposte` → `iai_slash` → `cross_cut` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `spin_kick` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 920 ms | Claude's signature spinning kick. · contact frame 4, reach 26 px; blunt hit, high |
| `slash_wave` | ↓ → + Special | signature special | projectile (24) | 7 | 900 ms | Throws a "/" slash wave across the taskbar. Costs nothing; looks cool. |
| `reverse` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 760 ms | "/reverse": rewinds to where it stood a second ago, dodging everything. Afterimage trail. |
| `radiant_beam` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 2060 ms | Cups both hands at the hip, charges for a full second, then fires a horizontal beam the width of the taskbar. · contact frame 6, reach 29 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 29 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 29 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 14 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `iai_slash` | ↓ → + Strike | weapon strike | medium (24) | 8 | 1090 ms | Iai: crouches with the blade low at the hip, then draws and cuts in one flash. · contact frame 3, reach 28 px; slash hit, mid |
| `cross_cut` | → → + Strike | weapon strike | heavy (36) | 8 | 900 ms | Two strokes that cross in an X: a falling diagonal, then the rising back-cut. · contact frame 5, reach 17 px; slash hit, high |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: a straight lunging stab, the answer to a parry. · contact frame 2, reach 29 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 29 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 25 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 26 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 31 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 26 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the blade, flicks it and sheathes it at the hip. |

### Codex - chain and kunai

3-hit string: `riposte` → `kunai_toss` → `guard_break` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `ground_pound` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 1090 ms | Codex's heavy leaping slam with a ground shockwave. · contact frame 5, reach 19 px; blunt hit, high |
| `deploy` | ↓ → + Special | signature special | projectile (24) | 8 | 1010 ms | Types a command and hits ENTER: fires a ">_" bolt across the taskbar. |
| `sudo` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | "$reverse": raises a giant $ and powers up with elevated permissions. |
| `spiral_orb` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1280 ms | Spins a sphere of energy in one hand, dashes in with afterimages and drives it home in a spiral burst. · contact frame 6, reach 27 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 22 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 26 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 11 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `chain_pull` | ← + Grab | chain pull | light (12) | 8 | 880 ms | Slings the rear kunai out on its chain, then yanks the opponent in. · contact frame 3, reach 33 px; pierce hit, mid |
| `kunai_toss` | → + Strike (throw) | weapon strike | light (12) | 7 | 830 ms | Cocks a kunai behind the ear and flings it across the gap. · contact frame 3, reach 33 px; pierce hit, mid |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: a reverse-grip stab with the rear kunai. · contact frame 2, reach 21 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 25 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 24 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 24 px; blunt hit, mid |
| `shadow_step` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 23 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 25 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Spins a kunai round one finger and points it at the opponent. |

### Gemini - dual weapons

3-hit string: `riposte` → `flurry` → `scissor_cut` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `spin_kick` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 920 ms | Gemini's spinning kick, both blades whipping round. · contact frame 4, reach 26 px; blunt hit, high |
| `star_shot` | ↓ → + Special | signature special | projectile (24) | 7 | 900 ms | Two-handed push that fires a "*" sparkle along the taskbar. |
| `twin_flash` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 760 ms | Flash-steps back a second in time, leaving a sparkle and an afterimage trail. |
| `crescent_fang` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1440 ms | Raises an arm, gathers energy and swings down a giant crescent slash wave. · contact frame 5, reach 30 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 26 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 28 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 12 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `flurry` | Strike Strike Strike | weapon strike | medium (24) | 8 | 780 ms | Three alternating cuts, lead, rear, lead rising; the third one lands. · contact frame 6, reach 18 px; slash hit, mid |
| `scissor_cut` | ← → + Strike | weapon strike | heavy (36) | 7 | 970 ms | Both weapons thrown wide, then snapped shut across the opponent like scissors. · contact frame 3, reach 27 px; slash hit, high |
| `blade_dance` | ↓ ← + Strike | weapon strike | medium (24) | 8 | 920 ms | A full spin with both weapons held out; the lead one sweeps through. · contact frame 4, reach 28 px; slash hit, mid |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: the rear weapon snaps out in a straight stab. · contact frame 2, reach 25 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 27 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 25 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 25 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 27 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 26 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Spins one weapon, then crosses both in front of the face. |

### Cursor - polearm (spear)

3-hit string: `riposte` → `long_thrust` → `pole_spin` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `ground_pound` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 1090 ms | Cursor's leaping slam with a ground shockwave. · contact frame 5, reach 19 px; blunt hit, high |
| `tab_bolt` | ↓ → + Special | signature special | projectile (24) | 8 | 1010 ms | Accepts a suggestion and hits TAB: fires a ">|" caret bolt across the taskbar. |
| `autocomplete` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | Raises a giant ">" and powers up: the whole line completes itself. |
| `grapple_strike` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1010 ms | Fires two grapple lines, zips across them and finishes with a spinning cross slash. · contact frame 6, reach 28 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 31 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 31 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 12 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `long_thrust` | → + Strike (hold) | weapon strike | medium (24) | 7 | 950 ms | Draws the spear all the way back, then lunges to its full length. · contact frame 3, reach 28 px; pierce hit, mid |
| `pole_sweep` | ↓ + Strike | weapon strike | light (12) | 7 | 770 ms | Drops low and sweeps the spear flat along the ankles. · contact frame 3, reach 31 px; slash hit, low |
| `vault_kick` | → ↑ + Kick | weapon strike | heavy (36) | 8 | 850 ms | Plants the spear, rides up it and whips a flying kick off the top. · contact frame 5, reach 27 px; blunt hit, high |
| `pole_spin` | Strike (hold) release | weapon strike | medium (24) | 8 | 850 ms | Whirls the spear overhead, faster each turn, then brings it down. · contact frame 5, reach 29 px; slash hit, high |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 640 ms | Riposte: chokes up and snaps the shaft forward. · contact frame 2, reach 28 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 31 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 27 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 26 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 31 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 31 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the spear and plants it upright with a head tilt. |

### Ollama - staff

3-hit string: `riposte` → `staff_sweep` → `overhead_slam` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `ground_pound` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 1090 ms | Ollama's llama stomp with a ground shockwave. · contact frame 5, reach 19 px; blunt hit, high |
| `pull_shot` | ↓ → + Special | signature special | projectile (24) | 8 | 1010 ms | "ollama pull": hurls a wool-white orb across the taskbar. |
| `serve` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | "ollama serve": raises a giant "o" and powers up, local and unstoppable. |
| `gale_rend` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1540 ms | Raises both arms, then slams down and rips three claws of energy along the ground. · contact frame 5, reach 26 px; blunt hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 32 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 32 px; blunt hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 14 px; blunt hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 27 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 30 px; blunt hit, high |
| `overhead_slam` | ↓ ↑ + Strike | weapon strike | heavy (36) | 8 | 1180 ms | Raises the staff, rises on the toes, then cracks it into the ground. · contact frame 4, reach 27 px; blunt hit, high |
| `staff_sweep` | ↓ + Strike | weapon strike | light (12) | 7 | 770 ms | Drops low and sweeps the staff along the ground. · contact frame 3, reach 26 px; blunt hit, low |
| `pole_vault` | → ↑ + Kick | weapon strike | heavy (36) | 8 | 850 ms | Plants the staff, vaults up it and kicks off the top. · contact frame 5, reach 29 px; blunt hit, high |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 640 ms | Riposte: drives the end of the staff straight out. · contact frame 2, reach 32 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 32 px; blunt hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 28 px; blunt hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 27 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 32 px; blunt hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 32 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the staff and plants it with a head tilt. |

### LM Studio - blade (katana)

3-hit string: `riposte` → `iai_slash` → `cross_cut` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `spin_kick` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 920 ms | LM Studio's spinning kick, the energy blade trailing. · contact frame 4, reach 26 px; blunt hit, high |
| `load_wave` | ↓ → + Special | signature special | projectile (24) | 7 | 900 ms | Loads a model and throws it as a teal-and-magenta wave across the taskbar. |
| `hot_swap` | ↓ ↓ + Super (meter) | signature super | super (24) | 8 | 850 ms | Hot-swaps back to where it stood a second ago, afterimage trail and a giant "L". |
| `awakening` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1270 ms | Releases a pillar of aura, then lands three flash-step strikes faster than the eye. · contact frame 4, reach 28 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 29 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 29 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 14 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `iai_slash` | ↓ → + Strike | weapon strike | medium (24) | 8 | 1090 ms | Iai: crouches with the blade low at the hip, then draws and cuts in one flash. · contact frame 3, reach 29 px; slash hit, mid |
| `cross_cut` | → → + Strike | weapon strike | heavy (36) | 8 | 900 ms | Two strokes that cross in an X: a falling diagonal, then the rising back-cut. · contact frame 5, reach 16 px; slash hit, high |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: a straight lunging stab, the answer to a parry. · contact frame 2, reach 29 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 31 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 26 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 27 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 31 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 26 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the blade, flicks it and sheathes it at the hip. |

### Agent - bow and dagger

3-hit string: `riposte` → `point_blank` → `arrow_volley` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `spin_kick` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 920 ms | A spinning kick: every agent learns this one. · contact frame 4, reach 26 px; blunt hit, high |
| `energy_bolt` | ↓ → + Special | signature special | projectile (24) | 8 | 1010 ms | Types a command and fires an energy orb across the taskbar. |
| `overclock` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | Raises a giant "+" and powers up: everything runs faster. |
| `star_core` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1760 ms | Raises both hands, gathers a huge slow ball of energy overhead and hurls it. · contact frame 5, reach 24 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 21 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 28 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 19 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `point_blank` | Shoot | weapon strike | medium (24) | 7 | 920 ms | Draws to the cheek, holds, and looses an arrow at point-blank range. · contact frame 3, reach 34 px; pierce hit, mid |
| `arrow_volley` | Shoot Shoot Shoot | weapon strike | medium (24) | 8 | 810 ms | Three arrows in quick succession; the third one lands. · contact frame 6, reach 34 px; pierce hit, mid |
| `leap_shot` | ← ← + Shoot | weapon strike | medium (24) | 8 | 820 ms | Springs backwards and shoots from the top of the leap. · contact frame 5, reach 31 px; pierce hit, mid |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: a quick stab with the dagger in the rear hand. · contact frame 2, reach 22 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 27 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 31 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 31 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 22 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1170 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 30 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the bow and raises it overhead. |

### Barbarian - heavy weapon

3-hit string: `riposte` → `guard_break` → `cleave` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `axe_spin` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 920 ms | A wild spinning kick, axe swinging round with it. · contact frame 4, reach 27 px; blunt hit, high |
| `axe_toss` | ↓ → + Special | signature special | projectile (24) | 8 | 1010 ms | Hurls a spinning hand-axe across the taskbar. |
| `berserk` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | Roars under a giant "V" and goes berserk. |
| `earthsplitter` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1540 ms | Raises the axe, then splits the ground with three tearing shock claws. · contact frame 5, reach 23 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 32 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 30 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 15 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 27 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 29 px; blunt hit, high |
| `cleave` | ← + Heavy | weapon strike | heavy (36) | 8 | 1450 ms | A huge wind-up it will not flinch out of, then one cleave into the ground. · contact frame 4, reach 28 px; slash hit, high; armour: no flinch from a light hit in the wind-up |
| `ground_slam` | ↓ ↓ + Heavy | weapon strike | heavy (36) | 8 | 1300 ms | Smashes the ground; the shock wave runs along the floor into the opponent. · contact frame 4, reach 33 px; slash hit, low |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 690 ms | Riposte: no time to swing, so the pommel is driven straight out. · contact frame 2, reach 26 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 910 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 30 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 1070 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 29 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 27 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 1060 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 31 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1360 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 28 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the weapon and rests it on the shoulder. |

### Knight - heavy weapon

3-hit string: `riposte` → `guard_break` → `cleave` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `crusher` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 1090 ms | Leaps and brings the greatsword down with a ground-shaking crash. · contact frame 5, reach 19 px; blunt hit, high |
| `sword_wave` | ↓ → + Special | signature special | projectile (24) | 7 | 900 ms | A two-handed sweep that sends a steel wave across the taskbar. |
| `valor` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | Raises the greatsword under a giant "T" and steels itself. |
| `holy_crescent` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1440 ms | Raises the greatsword, gathers light and cleaves a giant crescent down the taskbar. · contact frame 5, reach 31 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 29 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 29 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 15 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 27 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 28 px; blunt hit, high |
| `cleave` | ← + Heavy | weapon strike | heavy (36) | 8 | 1450 ms | A huge wind-up it will not flinch out of, then one cleave into the ground. · contact frame 4, reach 27 px; slash hit, high; armour: no flinch from a light hit in the wind-up |
| `ground_slam` | ↓ ↓ + Heavy | weapon strike | heavy (36) | 8 | 1300 ms | Smashes the ground; the shock wave runs along the floor into the opponent. · contact frame 4, reach 33 px; slash hit, low |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 690 ms | Riposte: no time to swing, so the pommel is driven straight out. · contact frame 2, reach 25 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 910 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 29 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 1070 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 27 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 27 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 1060 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 31 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1360 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 27 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the weapon and rests it on the shoulder. |

### Kunoichi - fans / chakrams

3-hit string: `riposte` → `fan_flurry` → `fan_cut` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `fan_whirl` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 920 ms | A spinning kick with both fans snapping open. · contact frame 4, reach 26 px; blunt hit, high |
| `petal_shot` | ↓ → + Special | signature special | projectile (24) | 7 | 900 ms | Sweeps a fan and sends a spinning blade-petal across the taskbar. |
| `vanish` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 760 ms | Vanishes back a second in a swirl of petals, a giant "x" where she stood. |
| `petal_dance` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1270 ms | A burst of crimson aura, then three flash-step fan cuts faster than the eye. · contact frame 4, reach 29 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 25 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 29 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 15 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `fan_gust` | ← → + Strike | wind gust | medium (24) | 7 | 930 ms | Sweeps both fans back, then fans a gust of wind across the gap. · contact frame 3, reach 34 px; slash hit, mid |
| `fan_cut` | ← → + Strike | weapon strike | heavy (36) | 7 | 970 ms | Both fans thrown wide, then snapped shut across the opponent. · contact frame 3, reach 28 px; slash hit, high |
| `fan_flurry` | Strike Strike Strike | weapon strike | medium (24) | 8 | 780 ms | Three alternating fan cuts; the third one lands. · contact frame 6, reach 22 px; slash hit, mid |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: the rear fan snaps out edge-first. · contact frame 2, reach 24 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 29 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 28 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 28 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 25 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 23 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls a fan and hides a smile behind it. |

### Monk - dual weapons

3-hit string: `riposte` → `tonfa_flurry` → `tonfa_crush` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `palm_crash` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 1090 ms | Leaps and drives both tonfa into the ground. · contact frame 5, reach 19 px; blunt hit, high |
| `chi_bolt` | ↓ → + Special | signature special | projectile (24) | 8 | 1010 ms | Thrusts a tonfa and fires a ball of chi across the taskbar. |
| `meditate` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | Centres itself under a giant "O"; the aura flares. |
| `chi_sphere` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1760 ms | Raises both tonfa, gathers a huge sphere of chi overhead and hurls it. · contact frame 5, reach 28 px; blunt hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 23 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 26 px; blunt hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 11 px; blunt hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `tonfa_flurry` | Strike Strike Strike | weapon strike | medium (24) | 8 | 780 ms | Three alternating tonfa strikes; the third one lands. · contact frame 6, reach 18 px; blunt hit, mid |
| `tonfa_crush` | ← → + Strike | weapon strike | heavy (36) | 7 | 970 ms | Both tonfa thrown wide, then slammed together on the opponent. · contact frame 3, reach 28 px; blunt hit, high |
| `tonfa_whirl` | ↓ ← + Strike | weapon strike | medium (24) | 8 | 920 ms | A full spin with both tonfa out; the lead one sweeps through. · contact frame 4, reach 26 px; blunt hit, mid |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: the rear weapon snaps out in a straight stab. · contact frame 2, reach 23 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 26 px; blunt hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 24 px; blunt hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 25 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 25 px; blunt hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 25 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Spins one weapon, then crosses both in front of the face. |

### Nomad - fans / chakrams

3-hit string: `riposte` → `ring_flurry` → `ring_slash` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `ring_spin` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 920 ms | A spinning kick, both chakrams whirling. · contact frame 4, reach 26 px; blunt hit, high |
| `chakram_throw` | ↓ → + Special | signature special | projectile (24) | 7 | 900 ms | Whips a chakram across the taskbar. |
| `mirage` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 760 ms | Slips back a second like a heat mirage, a giant "Y" left behind. |
| `ring_storm` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 1010 ms | Throws two chakrams on lines, zips after them and finishes with a spinning cross cut. · contact frame 6, reach 22 px; slash hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 27 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 31 px; slash hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 12 px; slash hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 26 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 27 px; blunt hit, high |
| `chakram_boomerang` | ↓ → + Throw | boomerang projectile | projectile (24) | 8 | 1110 ms | Whips a chakram out; it curves back and is caught. |
| `ring_slash` | ← → + Strike | weapon strike | heavy (36) | 7 | 970 ms | Both chakrams thrown wide, then snapped shut across the opponent. · contact frame 3, reach 30 px; slash hit, high |
| `ring_flurry` | Strike Strike Strike | weapon strike | medium (24) | 8 | 780 ms | Three alternating chakram cuts; the third one lands. · contact frame 6, reach 21 px; slash hit, mid |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 650 ms | Riposte: the rear fan snaps out edge-first. · contact frame 2, reach 26 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 830 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 31 px; slash hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 970 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 27 px; slash hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 27 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 970 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 27 px; slash hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1160 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 24 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls a fan and hides a smile behind it. |

### Oni - heavy weapon

3-hit string: `riposte` → `guard_break` → `cleave` (each hit cancels into the next on its cancel frame).

| move | input | type | damage | frames | length | what it is |
| --- | --- | --- | --- | ---: | ---: | --- |
| `club_slam` | → ↓ → + Kick | signature strike | heavy (36) | 8 | 1090 ms | Leaps and smashes the kanabo into the ground. · contact frame 5, reach 19 px; blunt hit, high |
| `oni_fire` | ↓ → + Special | signature special | projectile (24) | 8 | 1010 ms | Spits a ball of oni-fire across the taskbar. |
| `rampage` | ↓ ↓ + Super (meter) | signature super | super (24) | 7 | 890 ms | Swells under a giant "H", eyes blazing. |
| `oni_roar` | Super (below 30 HP, once a match) | signature ultimate | ultimate (40) | 8 | 2060 ms | Plants the kanabo, draws a breath for a full second and roars a beam of fire across the taskbar. · contact frame 6, reach 33 px; blunt hit, mid |
| `jab` | Strike | shared strike | light (12) | 7 | 640 ms | Fast lead-hand thrust. Light hit, small hit-stop. · contact frame 3, reach 30 px; pierce hit, mid |
| `cross` | → + Strike | shared strike | medium (24) | 7 | 830 ms | Big diagonal power slash. Medium hit, forces a block-stagger. · contact frame 3, reach 33 px; blunt hit, high |
| `uppercut` | ↓ ↑ + Strike | shared strike (launcher) | medium (24) | 7 | 800 ms | Rising launcher slash. Pops the opponent up. · contact frame 3, reach 16 px; blunt hit, high |
| `low_kick` | ↓ + Kick | shared strike | light (12) | 7 | 730 ms | Sweep along the ground with a hip turn. Trips guard-high opponents. · contact frame 3, reach 27 px; blunt hit, low |
| `roundhouse` | → + Kick | shared strike | heavy (36) | 8 | 1010 ms | High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through. · contact frame 3, reach 30 px; blunt hit, high |
| `cleave` | ← + Heavy | weapon strike | heavy (36) | 8 | 1450 ms | A huge wind-up it will not flinch out of, then one cleave into the ground. · contact frame 4, reach 30 px; blunt hit, high; armour: no flinch from a light hit in the wind-up |
| `ground_slam` | ↓ ↓ + Heavy | weapon strike | heavy (36) | 8 | 1300 ms | Smashes the ground; the shock wave runs along the floor into the opponent. · contact frame 4, reach 33 px; blunt hit, low |
| `riposte` | (after a parry) Strike | counter (after a parry) | medium (24) | 6 | 690 ms | Riposte: no time to swing, so the pommel is driven straight out. · contact frame 2, reach 27 px; pierce hit, mid |
| `air_slash` | ↑ + Strike (air) | air juggle | medium (24) | 8 | 910 ms | Jumps after a launched opponent and strikes down through it in mid-air. · contact frame 5, reach 33 px; blunt hit, high |
| `spike` | (air) ↓ + Strike | air spike | heavy (36) | 8 | 1070 ms | Leaps, raises the weapon overhead and spikes the airborne opponent into the ground. · contact frame 5, reach 31 px; blunt hit, high |
| `throw` | close: → + Grab | throw | medium (24) | 8 | 1020 ms | Grabs the opponent, hoists it overhead and slams it down. · contact frame 5, reach 30 px; blunt hit, mid |
| `dash_slash` | → → + Strike (dash) | dash-through | medium (24) | 8 | 1060 ms | Bursts through the opponent and stops on the far side; the cut lands a beat later. · contact frame 5, reach 33 px; blunt hit, back |
| `guard_break` | ← → + Strike (hold) | guard break | medium (24) | 8 | 1360 ms | A long heavy wind-up, then the pommel smashes the guard open. · contact frame 4, reach 30 px; blunt hit, mid |
| `taunt2` | Taunt | taunt | - | 8 | 1130 ms | Twirls the weapon and rests it on the shoulder. |

## How the fight uses them (V7)

| move type | what happens on the taskbar |
| --- | --- |
| weapon strike | Picked by the no-repeat picker with the shared strikes (which now weigh a little less); a family strike opens, chains in combos, and is the 3-hit string's material. |
| 3-hit string | Riposte → two family moves: each hit starts on the previous move's cancel frame (contact + hitstop), so the string flows instead of resetting to guard. |
| air juggle | A landed launcher (`uppercut`) pops the defender up (`launched`, it hangs on its last frame), the attacker leaps after it with its `air` move (`air_hit`) and spikes it into the floor (`spiked`), then the get-up. |
| throw | Close range only.  The defender's `thrown` row starts on the attacker's grab frame; both rows share one clock, so the flat landing falls on the attacker's slam.  The defender is hoisted in close, then slammed out in front; a slipped grab ends in a backdash. |
| chain pull | From range: the chain bites on contact and yanks the opponent to arm's length on the pull frame - often straight into the launcher and a juggle. |
| dash-through | From range: the attacker slides THROUGH the defender during its burst, stops on the far side with its back turned, and the cut registers on the frozen pose (`hit_back`: pitched forward).  The attacker then vaults back over to its own side. |
| guard break | The guard is smashed open (`guard_crush`, 12 chip damage) and the next strike is free. |
| riposte | When a strike is parried, the defender answers with its own riposte row most of the time. |
| clash | About a third of blocked or parried weapon strikes become a weapon lock instead: both fighters play `clash` on the same instant (sparks, a straining push), then both skid apart. |
| armour | Heavy cleaves: a light poke from the defender lands during the wind-up for 12, the attacker does not flinch and the cleave still lands. |
| boomerang | The chakram leaves the hand on its projectile frame, flies out to the defender and back, and is caught on the catch frame. |
| contact | Every landed hit draws a spark for its kind (slash: a thin bright arc; blunt: a shock ring and dust; pierce: a streak and spray), blocks draw deflected sparks, light hits play a high / low reaction by the move's height, and the screen shakes by power. |

### Set pieces

Hand-authored joint exchanges for both fighters (`minis_core/setpieces.py`), written against weapon-family slots so any pairing plays them; a match plays one to three at its dramatic moments (a round's second exchange, the comeback, match point).  Preview one with `python tools/setpiece_preview.py <piece> --a claude --b codex`.

| set piece | when | what happens |
| --- | --- | --- |
| Blade lock (`blade_lock`) | opener, mid | The weapons meet and lock; a straining push, both skid apart, a stand-off, then the defender ripostes. |
| Pull and launch (`pull_launch`) | mid, opener | Yanked in (or closed down), popped into the air, cut in mid-air, spiked into the floor. |
| Cross-cut freeze (`crosscut_freeze`) | mid, finisher | A dash THROUGH the opponent; both stand frozen, back to back, then the cut lands in slow motion. |
| Vault overhead (`vault_overhead`) | opener, mid | A vaulting attack from range, then the heavy follow-up while the opponent is still reeling. |
| Parry, riposte (`parry_riposte`) | comeback, mid | The big swing is swatted aside with a flash; the riposte answers before the swing has finished. |
| Guard crush (`guard_crush_combo`) | mid, opener | The guard is smashed open, and the 3-hit string goes straight through the opening. |
| Reversal (`comeback_reversal`) | comeback | Two attacks blocked under pressure, then the grab out of nowhere: a throw that turns the round. |
| Aerial finish (`aerial_finish`) | finisher, mid | Launched, juggled, and spiked, the last blow in slow motion. |

## What makes them move

| the agent is... | the fighter does |
| --- | --- |
| working (context under 70%) | `work` and `type`, alternating every 8-14 s |
| working, context 70%+ | `powerup` (aura charging) |
| idle | `idle`, with an `idle_flourish` every 6-10 s (1 in 4 is its signature super) |
| idle, context 85%+ | `rage` (aura on) |
| quiet for 45 s mid-turn | `wait` (foot tap), with a `shrug` every 10-16 s |
| no session for 30 min | `sleep` (dimmed), then `wake` when it comes back |
| finished a task (15 s+ of work) | `victory` |
| at its limit (90%+) | `ko` for 6 s, then `getup`, then `dizzy` while it stays there |
| paused (`minis.py pause` or the right-click menu) | one static `idle` frame; the plate keeps updating; no walking, no bouts |

Program sources without numbers (Cursor, Ollama, LM Studio, Gemini, aider, opencode, Windsurf) are *working* while their process tree uses more than 15% of one CPU core (averaged over 6 s), otherwise *idle*; their plate shows `ctx -`.

## Matches, HP and winners (V4)

A **match** is best-of-3 rounds: both fighters start a round at 100 HP; a landed move does power x 12 (12 / 24 / 36), a super 24, the ultimate 40; a round ends at 0 HP or after 25 s (higher HP wins).  `ROUND n` / `FIGHT!` / `K.O.` / `WINNER` texts and every hit, block and KO effect come from the effects sheet.  Winners are drawn from the seed: **decided** (default) weights each exchange by the health score = (100 - ctx%) + 20 if not at the limit + 10 if working; **random** is even.  `python minis.py winners random|decided` or the right-click menu switches it.  W/L per character live in `%LOCALAPPDATA%\minis\record.json` and show on the scoreboard widget.  A match starts every 3-6 minutes while both are awake, from `minis.py demo match`, the menu, or the scoreboard's *Bout now*; the same fighters fight the same way in **arena mode** (`minis.py arena --monitor N`).

## What makes them *interact* (separate processes; only tiny bus events pass between them)

| trigger | what happens |
| --- | --- |
| both agents working | **Clash** every 20-40 s: two quick exchanges and a fist-bump, no bows |
| both idle | **Spar** or **ranged duel** every 60-120 s: slot `a` invites, slot `b` accepts, both derive the same timeline |
| one finishes a task | **Handoff**: the finished fighter gives, the other walks over, takes the diff, reviews it for 6 s, gives a thumbs-up, they fist-bump |
| one hits its limit | **Console**: the other walks over (only if the knocked-out one is at home) and pats it on the shoulder, waves, goes home |
| one asleep or paused | no bouts |
| a mouse drag, a pause, a reassignment, or one hitting its limit mid-bout | the bout is cancelled on both sides; each walks home |

**Spar**: bow, four exchanges (attacker move, defender block / hit), then fist-bump or high-five, bow. The strike pool is the five shared strikes plus the attacker's signature strike. A strike's contact frame and the defender's reaction start on the same instant (tested to 0.01 s).  **Ranged duel**: each fighter casts its signature special, the projectile crosses the gap, the other blocks, then a taunt.  **Handoff**: the giver releases the diff on the exact frame the taker grabs it.

## Shared moves by category

### Locomotion

| move | frames | length | used | what it is |
| --- | ---: | ---: | :---: | --- |
| `idle` | 8 | 1190 ms↻ | yes | Default guard stance (idle, done). |
| `idle_flourish` | 6 | 620 ms | yes | Every 6-10 s while idle: shoulder roll and a hop (1 in 4 is the super instead). |
| `walk` | 6 | 600 ms↻ | yes | Walking to a bout, wandering, or visiting. Stride-locked: 40 px/s, feet do not slide. |
| `walk_back` | 6 | 660 ms↻ | yes | Backing away while still facing the other fighter. |
| `dash` | 5 | 360 ms | yes | Hop-step forward to close distance. |
| `turn` | 2 | 120 ms | yes | Pivot to face the other way. |
| `crouch` | 3 | 300 ms↻ | yes | Low stance. |
| `jump` | 8 | 930 ms | yes | Neutral jump with squash on landing. |

### Strikes

| move | frames | length | used | what it is |
| --- | ---: | ---: | :---: | --- |
| `jab` | 7 | 640 ms | yes | Spar / clash: fast lead-hand strike, light hit. · reach 29 px, contact at frame 3 |
| `cross` | 7 | 830 ms | yes | Spar / clash: rear-hand power punch. · reach 29 px, contact at frame 3 |
| `uppercut` | 7 | 800 ms | yes | Spar / clash: rising launcher. · reach 14 px, contact at frame 3 |
| `low_kick` | 7 | 730 ms | yes | Spar / clash: ground sweep. · reach 26 px, contact at frame 3 |
| `roundhouse` | 8 | 1010 ms | yes | Spar / clash: high kick, heavy hit, longest hit-stop. · reach 27 px, contact at frame 3 |

### Defense

| move | frames | length | used | what it is |
| --- | ---: | ---: | :---: | --- |
| `backdash` | 5 | 350 ms | yes | Evasive hop back with afterimages. |
| `block` | 4 | 370 ms↻ | yes | Spar / duel: the defender raises guard just before a strike lands. |
| `block_hit` | 3 | 230 ms | yes | Spar / duel: the guard absorbs the hit with a flash. |
| `crouch_block` | 2 | 200 ms↻ | yes | Low guard. |
| `parry` | 4 | 420 ms | yes | Swat a strike aside. Counter window. · reach 31 px, contact at frame 1 |

### Reactions

| move | frames | length | used | what it is |
| --- | ---: | ---: | :---: | --- |
| `hit` | 5 | 360 ms | yes | Spar: head snap when a strike lands. |
| `hit_heavy` | 6 | 490 ms | yes | Spar: slides back and wobbles after a heavy strike. |
| `knockdown` | 7 | 610 ms | yes | Falls flat. (Spar is friendly, so it is reserved for a finisher.) |
| `getup` | 6 | 590 ms | yes | After a KO: kip up. |
| `dizzy` | 4 | 520 ms↻ | yes | Stagger with stars: shown while a fighter stays at its limit. |
| `ko` | 7 | 890 ms↻ | yes | Context or plan limit reached (90%+): knocked out, stars orbit. |
| `launched` | 5 | 590 ms | yes | Launched: popped up and hanging in the air, open for a juggle. |
| `air_hit` | 4 | 450 ms | yes | Juggled: hit again while airborne. |
| `spiked` | 7 | 600 ms | yes | Spiked: slammed out of the air, bounces once and lies there. |
| `thrown` | 7 | 990 ms | yes | Thrown: grabbed, hoisted overhead and slammed flat. · reach 18 px, contact at frame 4 |
| `pulled` | 5 | 470 ms | yes | Pulled: yanked in by a chain and stumbles forward. |
| `guard_crush` | 6 | 700 ms | yes | Guard crushed: the guard flies open and the fighter staggers, wide open. |
| `hit_high` | 5 | 370 ms | yes | Hit high: the head snaps back first, the arms follow. |
| `hit_low` | 5 | 410 ms | yes | Hit low: doubles over the blow, knees buckle. |
| `hit_back` | 5 | 440 ms | yes | Hit from behind: pitched forward, stumbles, catches itself. |
| `clash` | 7 | 760 ms | yes | Clash: the weapons lock with a spark, a straining push, then both shove off. |

### Emotes

| move | frames | length | used | what it is |
| --- | ---: | ---: | :---: | --- |
| `victory` | 7 | 1270 ms | yes | A task finished (15 s+ of work, not a timeout): fist pump with a hop. |
| `victory2` | 4 | 560 ms | yes | Flex. The bigger-win version. |
| `taunt` | 6 | 720 ms | yes | End of a ranged duel: come-on beckon. |
| `wave` | 5 | 570 ms | yes | After consoling a KO. |
| `thumbs_up` | 4 | 600 ms | yes | The reviewer approves the diff. |
| `facepalm` | 5 | 650 ms | yes | Something broke. |
| `shrug` | 4 | 540 ms | yes | Waiting state: every 10-16 s, unsure. |
| `taunt2` | 8 | 1130 ms | yes | Twirls the blade, flicks it and sheathes it at the hip. |

### State animations (what an agent is doing)

| move | frames | length | used | what it is |
| --- | ---: | ---: | :---: | --- |
| `work` | 6 | 540 ms↻ | yes | Working state: shadowboxing. |
| `type` | 6 | 540 ms↻ | yes | Working state: typing on an air keyboard. |
| `review` | 6 | 720 ms↻ | yes | Handoff: the receiving fighter strokes its chin and reads the diff. |
| `wait` | 4 | 600 ms↻ | yes | Waiting? state: foot tap, hands on hips (no new activity for 45 s). |
| `sleep` | 4 | 2400 ms↻ | yes | Sleeping state: no session in 30 minutes (dimmed). |
| `wake` | 4 | 700 ms | yes | Stretch and yawn when a sleeping fighter gets a session. |
| `powerup` | 5 | 400 ms↻ | yes | Working while context is past 70%: visibly charging. |
| `rage` | 4 | 320 ms↻ | yes | Idle while context is past 85%: aura on. |

### Paired moves

| move | frames | length | used | what it is |
| --- | ---: | ---: | :---: | --- |
| `bow` | 4 | 750 ms | yes | Respect bow before and after a spar (a clash skips the bows). |
| `fistbump` | 4 | 420 ms | yes | Ends every spar, clash and handoff, on the same frame for both. · reach 25 px, contact at frame 2 |
| `highfive` | 6 | 630 ms | yes | Alternative spar ending: jump high-five. · reach 18 px, contact at frame 2 |
| `handoff_give` | 6 | 840 ms | yes | Handoff: the fighter that just finished holds out the diff. |
| `handoff_take` | 6 | 780 ms | yes | Handoff: the other fighter takes the diff to review it. |
| `console` | 4 | 640 ms | yes | The other fighter hit its limit: pats it on the shoulder. |

↻ = loops. Frame counts and lengths are Claude's; reach differs slightly per body.

## HUD plate

A dark pill behind each fighter (it flips to the front side only when the back side would leave the zone). Line 1: the character's tag + the state word. Line 2: a 10-segment bar for **context fill of the active session** (`ctx 69%`), then the plan figure when one can be trusted (`wk 1%` for Codex under the trust rules, `5h 35%` for Claude only from the optional feed). The bar colour follows **context only**: accent under 70%, amber 70-89%, blinking red 90%+. Numbers and a state word only: never titles, prompts, file names or client names.

## Built but not triggered yet

none. These have art, timing and tests; they need a trigger in `minis_core/brain.py`.

## Ideas to expand

**More fighting**

- **Combo counter and hit-streak** text above a fighter ("3 HIT") when a string or a juggle chains.
- **Super meter** that fills from something real, e.g. the cache-hit ratio, and spends on the signature super.
- **More set pieces**: a projectile duel where the two specials collide mid-air; a double knockout.

**Real signals instead of flair**

- **CI pass or fail** becomes win or lose; a failing test is a `facepalm`.
- A **click** opens that agent's window; hover shows exact numbers and "resets in 2d 4h".

**Polish**

- Hand-polish key frames: drop a 64x64 PNG with the character's palette at `art/hand/<character>/<move>_<frame>.png` (or point `MINIS_HAND_DIR` elsewhere) and rebuild with `python art/build_fighters.py`.
- Second monitor support; per-monitor DPI scaling above 100%.
