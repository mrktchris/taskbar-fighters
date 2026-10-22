"""Generate MOVELIST.md from assets/*/anim.json (every character on disk).  'Used' is decided from the planner's real
triggers: a move counts only if minis_core/brain.py names it, or it is a character's signature move (the planner reads
signature strike / special / super from the atlas).   python tools/gen_movelist.py"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from minis_core.atlas import Atlas, available  # noqa: E402
from minis_core.sources import RULES, PROGRAM  # noqa: E402
from minis_core import setpieces  # noqa: E402

brain_src = ''.join(open(os.path.join(ROOT, 'minis_core', f), encoding='utf-8').read() for f in ('brain.py', 'rounds.py', 'arena.py', 'choreo.py', 'setpieces.py'))   # the planners that trigger moves
CHARS = available()
ORDER = ['claude', 'codex', 'gemini', 'cursor', 'ollama', 'lmstudio', 'generic']
CHARS = [c for c in ORDER if c in CHARS] + [c for c in CHARS if c not in ORDER]
A = {c: Atlas(c) for c in CHARS}
SIG = {c: A[c].signature() for c in CHARS}
sig_moves = {m for c in CHARS for m in SIG[c].values() if m}

WHEN = {
    'idle': 'Default guard stance (idle, done).', 'idle_flourish': 'Every 6-10 s while idle: shoulder roll and a hop (1 in 4 is the super instead).',
    'walk': 'Walking to a bout, wandering, or visiting. Stride-locked: 40 px/s, feet do not slide.',
    'walk_back': 'Backing away while still facing the other fighter.',
    'dash': 'Hop-step forward to close distance.', 'backdash': 'Evasive hop back with afterimages.', 'turn': 'Pivot to face the other way.',
    'crouch': 'Low stance.', 'jump': 'Neutral jump with squash on landing.',
    'jab': 'Spar / clash: fast lead-hand strike, light hit.', 'cross': 'Spar / clash: rear-hand power punch.', 'uppercut': 'Spar / clash: rising launcher.',
    'low_kick': 'Spar / clash: ground sweep.', 'roundhouse': 'Spar / clash: high kick, heavy hit, longest hit-stop.',
    'block': 'Spar / duel: the defender raises guard just before a strike lands.', 'block_hit': 'Spar / duel: the guard absorbs the hit with a flash.',
    'crouch_block': 'Low guard.', 'parry': 'Swat a strike aside. Counter window.',
    'hit': 'Spar: head snap when a strike lands.', 'hit_heavy': 'Spar: slides back and wobbles after a heavy strike.',
    'knockdown': 'Falls flat. (Spar is friendly, so it is reserved for a finisher.)', 'getup': 'After a KO: kip up.',
    'dizzy': 'Stagger with stars: shown while a fighter stays at its limit.', 'ko': 'Context or plan limit reached (90%+): knocked out, stars orbit.',
    'victory': 'A task finished (15 s+ of work, not a timeout): fist pump with a hop.', 'victory2': 'Flex. The bigger-win version.',
    'taunt': 'End of a ranged duel: come-on beckon.', 'bow': 'Respect bow before and after a spar (a clash skips the bows).',
    'fistbump': 'Ends every spar, clash and handoff, on the same frame for both.', 'highfive': 'Alternative spar ending: jump high-five.',
    'wave': 'After consoling a KO.', 'thumbs_up': 'The reviewer approves the diff.', 'facepalm': 'Something broke.',
    'shrug': 'Waiting state: every 10-16 s, unsure.', 'work': 'Working state: shadowboxing.', 'type': 'Working state: typing on an air keyboard.',
    'review': 'Handoff: the receiving fighter strokes its chin and reads the diff.', 'wait': 'Waiting? state: foot tap, hands on hips (no new activity for 45 s).',
    'sleep': 'Sleeping state: no session in 30 minutes (dimmed).', 'wake': 'Stretch and yawn when a sleeping fighter gets a session.',
    'powerup': 'Working while context is past 70%: visibly charging.', 'rage': 'Idle while context is past 85%: aura on.',
    'handoff_give': 'Handoff: the fighter that just finished holds out the diff.', 'handoff_take': 'Handoff: the other fighter takes the diff to review it.',
    'console': 'The other fighter hit its limit: pats it on the shoulder.',
}
CATS = [('locomotion', 'Locomotion'), ('strike', 'Strikes'), ('defense', 'Defense'), ('reaction', 'Reactions'),
        ('emote', 'Emotes'), ('state', 'State animations (what an agent is doing)'), ('pair', 'Paired moves')]

shared = [n for n in A[CHARS[0]].anim if all(n in A[c].anim for c in CHARS) and n not in sig_moves
          and not A[CHARS[0]].anim[n].get('family')]
# V7: the planner picks weapon moves and reactions by their anim.json `type`, so a typed row is wired by construction
wired = {n: (f"'{n}'" in brain_src) or n in sig_moves or bool(A[CHARS[0]].anim.get(n, {}).get('type')) for n in set(shared) | sig_moves}
unwired = [n for n in shared if not wired[n]]
first = A[CHARS[0]]
programs = {}
for r in RULES:
    if r['source'] in ('claude', 'codex'):
        continue
    programs.setdefault(r.get('character', r['source']), []).append(PROGRAM[r['source']])

L = []
w = L.append
w('# Fighter move list\n')
w('Generated from `assets/*/anim.json` by `tools/gen_movelist.py`; every number below is read from the real sheets. '
  '"Used" is decided from the planner: a move says *yes* only if `minis_core/brain.py` triggers it or it is a signature move '
  '(the planner reads each character\'s signature strike / special / super from its atlas).\n')
w('## At a glance\n')
w(f"- **{len(CHARS)} characters**: {', '.join(A[c].display for c in CHARS)}. Each has the same **{len(shared)} shared moves**, its **signature moves**, "
  f"and **its weapon family's moves** (V7: {min(sum(1 for m in A[c].anim.values() if m.get('family')) for c in CHARS)}-"
  f"{max(sum(1 for m in A[c].anim.values() if m.get('family')) for c in CHARS)} per character; "
  f"{len(first.anim)} moves, {sum(len(a['frames']) for a in first.anim.values())} frames for {first.display}).")
w(f"- {sum(1 for n in shared if wired[n])} of {len(shared)} shared moves are triggered by the planner today, and every signature move is; "
  f"{len(unwired)} shared moves are built and waiting for a trigger (listed at the end).")
w('- Which character appears is decided by the **director** from what is running (at most two at a time, slot `a` left and slot `b` right).\n')

w('## The roster\n')
w('| character | plate tag | accent | strike | special (projectile) | super | ultimate (40 dmg) | shown for |\n| --- | --- | --- | --- | --- | --- | --- | --- |')
for c in CHARS:
    a, s = A[c], SIG[c]
    shown = {'claude': 'Claude Code transcripts', 'codex': 'Codex transcripts (CLI, Emdash, desktop app)'}.get(c) or ', '.join(programs.get(c, [])) or '-'
    if c == 'generic':
        shown += ' (and any character whose art is missing)'
    acc = '#%02X%02X%02X' % tuple(a.accent)
    w(f"| {a.display} | `{a.tag}` | {acc} | `{s['strike']}` | `{s['special']}` | `{s['super']}` | `{a.ultimate()}` | {shown} |")
w('')
w('### Signature moves\n')
w('| character | move | role | frames | length | what it is |\n| --- | --- | --- | ---: | ---: | --- |')
for c in CHARS:
    for role in ('strike', 'special', 'super', 'ultimate'):
        n = SIG[c].get(role)
        if not n:
            continue
        m = A[c].anim[n]
        extra = f" · reach {m['reach']:g} px, contact at frame {m['hit_frame']}" if 'reach' in m else ''
        if role == 'ultimate':
            extra += ' · 40 damage · effects: ' + ', '.join(f'`{name}`' for _, name, _ in A[c].move_fx(n))
        w(f"| {A[c].display} | `{n}` | {role} | {len(m['frames'])} | {A[c].total_ms(n)} ms | {m.get('desc', '')}{extra} |")
w('')

# ---------------------------------------------------------------- V7: every fighter, move by move
ARROW = {'fwd': '→', 'back': '←', 'down': '↓', 'up': '↑'}
FAMILY_TITLE = {'blade': 'blade (katana)', 'dual': 'dual weapons', 'polearm': 'polearm (spear)', 'staff': 'staff',
                'chain': 'chain and kunai', 'bow': 'bow and dagger', 'fans': 'fans / chakrams', 'heavy': 'heavy weapon'}
SHARED_INPUT = {'jab': 'Strike', 'cross': '→ + Strike', 'uppercut': '↓ ↑ + Strike', 'low_kick': '↓ + Kick', 'roundhouse': '→ + Kick'}
ROLE_INPUT = {'strike': '→ ↓ → + Kick', 'special': '↓ → + Special', 'super': '↓ ↓ + Super (meter)', 'ultimate': 'Super (below 30 HP, once a match)'}
TYPE_LABEL = {'string': 'weapon strike', 'riposte': 'counter (after a parry)', 'air': 'air juggle', 'spike': 'air spike',
              'throw': 'throw', 'through': 'dash-through', 'guard_break': 'guard break', 'pull': 'chain pull', 'gust': 'wind gust',
              'boomerang': 'boomerang projectile', 'taunt': 'taunt'}


def arrows(s):
    import re
    return re.sub(r'\b(fwd|back|down|up)\b', lambda m: ARROW[m.group(1)], s).replace(', ', ' ')


def tier(a, n, role=None):
    if role == 'ultimate':
        return 'ultimate (40)'
    if role == 'super':
        return 'super (24)'
    if a.get('cat') == 'special' and 'proj_frame' in a:
        return f"projectile ({int(a.get('power') or 1) * 12})"
    if 'hit_frame' not in a:
        return '-'
    p = int(a.get('power') or 1)
    return f"{('light', 'medium', 'heavy')[min(2, p - 1)]} ({p * 12})"


def family(c):
    return next((m['family'] for m in A[c].anim.values() if m.get('family')), '-')


w('## Every fighter, move by move (V7)\n')
w('Each fighter fights like its weapon: the shared strikes are swung with it, and every character has its weapon family\'s own '
  'moves plus the shared move *types* (air juggle, throw, dash-through, guard break, riposte, a taunt variant).  The input '
  'labels are fighting-game notation for reading the list (→ forward, ← back, ↓ down, ↑ up); nothing reads them as input - the '
  'choreographer picks every move itself.  Damage tiers: light 12, medium 24, heavy 36, super 24, ultimate 40.  '
  '"Frames" and "length" are read from the real sheet; contact-frame and reach notes come from the art.\n')
for c in CHARS:
    a = A[c]
    fam = family(c)
    combo = a.meta.get('combo') or []
    w(f"### {a.display} - {FAMILY_TITLE.get(fam, fam)}\n")
    if combo:
        w(f"3-hit string: {' → '.join(f'`{m}`' for m in combo)} (each hit cancels into the next on its cancel frame).\n")
    w('| move | input | type | damage | frames | length | what it is |\n| --- | --- | --- | --- | ---: | ---: | --- |')
    rows = []
    for role in ('strike', 'special', 'super', 'ultimate'):
        n = SIG[c].get(role)
        if n:
            rows.append((n, ROLE_INPUT[role], f'signature {role}', tier(a.anim[n], n, role)))
    for n in ('jab', 'cross', 'uppercut', 'low_kick', 'roundhouse'):
        if n in a.anim:
            rows.append((n, SHARED_INPUT[n], 'shared strike' + (' (launcher)' if n == 'uppercut' else ''), tier(a.anim[n], n)))
    for n, m in a.anim.items():
        if m.get('type') in TYPE_LABEL:
            rows.append((n, arrows(m.get('input', '-')), TYPE_LABEL[m['type']], tier(m, n)))
    for n, inp, typ, dmg in rows:
        m = a.anim[n]
        extra = []
        if 'hit_frame' in m and 'reach' in m:
            extra.append(f"contact frame {m['hit_frame']}, reach {m['reach']:g} px")
        if m.get('hit'):
            extra.append(f"{m['hit']} hit, {m['height']}")
        if m.get('armor'):
            extra.append('armour: no flinch from a light hit in the wind-up')
        desc = m.get('desc', '') + (' · ' + '; '.join(extra) if extra else '')
        w(f"| `{n}` | {inp} | {typ} | {dmg} | {len(m['frames'])} | {a.total_ms(n)} ms | {desc} |")
    w('')

w('## How the fight uses them (V7)\n')
w('| move type | what happens on the taskbar |\n| --- | --- |')
for k, v in [
    ('weapon strike', 'Picked by the no-repeat picker with the shared strikes (which now weigh a little less); a family strike opens, chains in combos, and is the 3-hit string\'s material.'),
    ('3-hit string', 'Riposte → two family moves: each hit starts on the previous move\'s cancel frame (contact + hitstop), so the string flows instead of resetting to guard.'),
    ('air juggle', 'A landed launcher (`uppercut`) pops the defender up (`launched`, it hangs on its last frame), the attacker leaps after it with its `air` move (`air_hit`) and spikes it into the floor (`spiked`), then the get-up.'),
    ('throw', 'Close range only.  The defender\'s `thrown` row starts on the attacker\'s grab frame; both rows share one clock, so the flat landing falls on the attacker\'s slam.  The defender is hoisted in close, then slammed out in front; a slipped grab ends in a backdash.'),
    ('chain pull', 'From range: the chain bites on contact and yanks the opponent to arm\'s length on the pull frame - often straight into the launcher and a juggle.'),
    ('dash-through', 'From range: the attacker slides THROUGH the defender during its burst, stops on the far side with its back turned, and the cut registers on the frozen pose (`hit_back`: pitched forward).  The attacker then vaults back over to its own side.'),
    ('guard break', 'The guard is broken open (`guard_crush`, 12 chip damage) and the next strike is free.'),
    ('riposte', 'When a strike is parried, the defender answers with its own riposte row most of the time.'),
    ('clash', 'About a third of blocked or parried weapon strikes become a weapon lock instead: both fighters play `clash` on the same instant (sparks, a straining push), then both skid apart.'),
    ('armour', 'Heavy cleaves: a light poke from the defender lands during the wind-up for 12, the attacker does not flinch and the cleave still lands.'),
    ('boomerang', 'The chakram leaves the hand on its projectile frame, flies out to the defender and back, and is caught on the catch frame.'),
    ('contact', 'Every landed hit draws a spark for its kind (slash: a thin bright arc; blunt: a shock ring and dust; pierce: a streak and spray), blocks draw deflected sparks, light hits play a high / low reaction by the move\'s height, and the screen shakes by power.'),
]:
    w(f'| {k} | {v} |')
w('')
w('### Set pieces\n')
w('Hand-authored joint exchanges for both fighters (`minis_core/setpieces.py`), written against weapon-family slots so any pairing '
  'plays them; a match plays one to three at its dramatic moments (a round\'s second exchange, the comeback, match point).  '
  'Preview one with `python tools/setpiece_preview.py <piece> --a claude --b codex`.\n')
w('| set piece | when | what happens |\n| --- | --- | --- |')
for n in setpieces.ORDER:
    pc = setpieces.PIECES[n]
    w(f"| {pc['title']} (`{n}`) | {', '.join(pc['when'])} | {pc['desc']} |")
w('')

w('## What makes them move\n')
w('| the agent is... | the fighter does |\n| --- | --- |')
for a, b in [('working (context under 70%)', '`work` and `type`, alternating every 8-14 s'), ('working, context 70%+', '`powerup` (aura charging)'),
             ('idle', '`idle`, with an `idle_flourish` every 6-10 s (1 in 4 is its signature super)'), ('idle, context 85%+', '`rage` (aura on)'),
             ('quiet for 45 s mid-turn', '`wait` (foot tap), with a `shrug` every 10-16 s'), ('no session for 30 min', '`sleep` (dimmed), then `wake` when it comes back'),
             ('finished a task (15 s+ of work)', '`victory`'), ('at its limit (90%+)', '`ko` for 6 s, then `getup`, then `dizzy` while it stays there'),
             ('paused (`minis.py pause` or the right-click menu)', 'one static `idle` frame; the plate keeps updating; no walking, no bouts')]:
    w(f'| {a} | {b} |')
w('\nProgram sources without numbers (Cursor, Ollama, LM Studio, Gemini, aider, opencode, Windsurf) are *working* while their process tree uses more '
  'than 15% of one CPU core (averaged over 6 s), otherwise *idle*; their plate shows `ctx -`.\n')
w('## Matches, HP and winners (V4)\n')
w('A **match** is best-of-3 rounds: both fighters start a round at 100 HP; a landed move does power x 12 (12 / 24 / 36), a super 24, '
  'the ultimate 40; a round ends at 0 HP or after 25 s (higher HP wins).  `ROUND n` / `FIGHT!` / `K.O.` / `WINNER` texts and every hit, '
  'block and KO effect come from the effects sheet.  Winners are drawn from the seed: **decided** (default) weights each exchange by the '
  'health score = (100 - ctx%) + 20 if not at the limit + 10 if working; **random** is even.  `python minis.py winners random|decided` or the '
  'right-click menu switches it.  W/L per character live in `%LOCALAPPDATA%\\minis\\record.json` and show on the scoreboard widget.  '
  'A match starts every 3-6 minutes while both are awake, from `minis.py demo match`, the menu, or the scoreboard\'s *Bout now*; the same '
  'fighters fight the same way in **arena mode** (`minis.py arena --monitor N`).\n')
w('## What makes them *interact* (separate processes; only tiny bus events pass between them)\n')
w('| trigger | what happens |\n| --- | --- |')
for a, b in [('both agents working', '**Clash** every 20-40 s: two quick exchanges and a fist-bump, no bows'),
             ('both idle', '**Spar** or **ranged duel** every 60-120 s: slot `a` invites, slot `b` accepts, both derive the same timeline'),
             ('one finishes a task', '**Handoff**: the finished fighter gives, the other walks over, takes the diff, reviews it for 6 s, gives a thumbs-up, they fist-bump'),
             ('one hits its limit', '**Console**: the other walks over (only if the knocked-out one is at home) and pats it on the shoulder, waves, goes home'),
             ('one asleep or paused', 'no bouts'),
             ('a mouse drag, a pause, a reassignment, or one hitting its limit mid-bout', 'the bout is cancelled on both sides; each walks home')]:
    w(f'| {a} | {b} |')
w('\n**Spar**: bow, four exchanges (attacker move, defender block / hit), then fist-bump or high-five, bow. The strike pool is the five shared strikes plus '
  'the attacker\'s signature strike. A strike\'s contact frame and the defender\'s reaction start on the same instant (tested to 0.01 s).  '
  '**Ranged duel**: each fighter casts its signature special, the projectile crosses the gap, the other blocks, then a taunt.  '
  '**Handoff**: the giver releases the diff on the exact frame the taker grabs it.\n')

w('## Shared moves by category\n')
for key, title in CATS:
    ms = [n for n in shared if first.anim[n]['cat'] == key]
    if not ms:
        continue
    w(f'### {title}\n')
    w('| move | frames | length | used | what it is |\n| --- | ---: | ---: | :---: | --- |')
    for n in ms:
        a = first.anim[n]
        extra = f" · reach {a['reach']:g} px, contact at frame {a['hit_frame']}" if 'reach' in a else ''
        w(f"| `{n}` | {len(a['frames'])} | {first.total_ms(n)} ms{'↻' if a['loop'] else ''} | {'yes' if wired[n] else 'not yet'} | {WHEN.get(n, a.get('desc', ''))}{extra} |")
    w('')
w(f'↻ = loops. Frame counts and lengths are {first.display}\'s; reach differs slightly per body.\n')

w('## HUD plate\n')
w('A dark pill behind each fighter (it flips to the front side only when the back side would leave the zone). Line 1: the character\'s tag + the state word. '
  'Line 2: a 10-segment bar for **context fill of the active session** (`ctx 69%`), then the plan figure when one can be trusted '
  '(`wk 1%` for Codex under the trust rules, `5h 35%` for Claude only from the optional feed). The bar colour follows **context only**: accent under 70%, '
  'amber 70-89%, blinking red 90%+. Numbers and a state word only: never titles, prompts, file names or client names.\n')
w('## Built but not triggered yet\n')
w((', '.join(f'`{n}`' for n in unwired) or 'none') + '. These have art, timing and tests; they need a trigger in `minis_core/brain.py`.\n')

w('## Ideas to expand\n')
for head, items in [
    ('More fighting', ['**Combo counter and hit-streak** text above a fighter ("3 HIT") when a string or a juggle chains.',
                       '**Super meter** that fills from something real, e.g. the cache-hit ratio, and spends on the signature super.',
                       '**More set pieces**: a projectile duel where the two specials collide mid-air; a double knockout.']),
    ('Real signals instead of flair', ['**CI pass or fail** becomes win or lose; a failing test is a `facepalm`.',
                                      'A **click** opens that agent\'s window; hover shows exact numbers and "resets in 2d 4h".']),
    ('Polish', ['Hand-polish key frames: drop a 64x64 PNG with the character\'s palette at `art/hand/<character>/<move>_<frame>.png` '
                '(or point `MINIS_HAND_DIR` elsewhere) and rebuild with `python art/build_fighters.py`.',
                'Second monitor support; per-monitor DPI scaling above 100%.']),
]:
    w(f'**{head}**\n')
    for it in items:
        w(f'- {it}')
    w('')
open(os.path.join(ROOT, 'MOVELIST.md'), 'w', encoding='utf-8').write('\n'.join(L))
print('MOVELIST.md written:', len(CHARS), 'characters,', len(shared), 'shared moves,', len(unwired), 'not triggered:', unwired)
