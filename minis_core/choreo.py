"""Fight choreography shared by the taskbar timeline (rounds.py, brain.py spar / clash) and the arena (arena.py).

Why: the V4 planner picked every attack with `rng.choice(strikes)`, so a match was the same six strikes in a row and the
defence, locomotion, specials, supers and the ultimate almost never appeared ("same moves over and over").  Everything
here is a pure function of one `random.Random` and the two atlases, so the two fighter processes (and the preview
simulator) derive the identical exchange from the shared seed without talking.

Vocabulary
  Picker        seeded no-repeat move picker: never the same move twice in a row, no move more than MAX_PER_ROUND times
                per round (relaxed only when nothing else is left), weighted by category and situation.
  plan_exchange one exchange as a list of *beats* the caller plays in order:
    {'who': 'att'|'dfn', 'kind': 'move',    'anim': dash|jump|backdash|walk_back, 'dx': +1 toward / -1 away}
    {'who': 'att'|'dfn', 'kind': 'strike'|'special'|'super'|'ultimate'|'counter', 'anim': move, 'dmg': n,
       'outcome': 'hit'|'block'|'crouch_block'|'parry'|'whiff', 'pre': defender anim before contact or None,
       'react': defender anim at contact or None, 'hitstop': ms, 'knock': px (RES 1, along the attacker's facing),
       'down': bool (big hit: knockdown then getup, not a KO)}
    {'who': 'dfn', 'kind': 'emote', 'anim': 'taunt'}                 after a whiffed ultimate
  The caller owns HP: a `hit` whose damage empties the bar becomes a knockdown / KO and the rest of the exchange is dropped.
  Every move name is read from the atlases (`signature`, `anims`), never assumed.

V7 (weapon move families, docs/ANIMATION-NOTES.md section 8).  Every V7 row carries `type` in anim.json and is picked by
type, never by name.  New optional beat fields (an engine that does not know them can play the beat as a plain strike):
  throw      the attack is a throw: the defender's `react` row (`thrown`) starts on the attacker's grab_frame, not on contact
  pull       the defender (`pulled`) is yanked toward the attacker on contact
  through    a dash-through: the attacker ends up BEHIND the defender (sides swap); the cut registers on the hit frame
  juggle     part of an air juggle: launcher (react `launched`) -> `air` move (react `air_hit`) -> `spike` (react `spiked`)
  string     part of the character's 3-hit string (anim.json `combo`): the next hit starts on this move's `cancel_frame`
  boomerang  a special whose projectile flies out and comes back to the thrower on its `catch_frame`
  armor      {'anim', 'dmg'}: the defender's poke lands during the wind-up and the attacker does not flinch
  riposte    a counter that is the defender's own riposte row
New outcome: 'guard_break' (react `guard_crush`): the guard is broken open, chip damage, and a free follow-up lands.
"""
from __future__ import annotations
from collections import Counter

STRIKES = ('jab', 'cross', 'uppercut', 'low_kick', 'roundhouse')
STRIKE_W = {'jab': 1.2, 'cross': 1.0, 'uppercut': 0.9, 'low_kick': 0.9, 'roundhouse': 0.7}
HIGHS = ('uppercut', 'roundhouse', 'spin_kick', 'ground_pound', 'cross')      # a crouch block slips under these
KICKS = ('low_kick', 'roundhouse', 'spin_kick')
COMBOS = (('jab', 'cross', 'uppercut'), ('jab', 'jab', 'roundhouse'), ('low_kick', 'cross'), ('jab', 'cross'),
          ('cross', 'uppercut'), ('jab', 'low_kick', 'roundhouse'), ('low_kick', 'uppercut'))
MAX_PER_ROUND = 2
METER_SUPER = 250                     # hit meter (damage dealt + half the damage taken) that unlocks a super (V6: was 72 -> 3 per match)
SUPER_CHANCE = 0.4
ULT_HP = 30                           # V6: the ultimate is a desperation move: only an attacker below this HP may fire it
ULT_CHANCE = 0.35                     # ... and then only this often per exchange; one per MATCH between both fighters (rounds.Bout)
HITSTOP_FLOOR_MS = 100                # V6: below ~100 ms the freeze falls between two taskbar redraws and is never seen
BLOCK_HITSTOP_K = 0.7
EDGE_MAX = 0.25                       # story: how far HP / round score may tilt hit-vs-defence odds toward the trailing fighter
DMG_PER_POWER = 12
DMG_SUPER = 24
DMG_ULTIMATE = 40
HITSTOP_K = {'strike': 0.5, 'counter': 0.5, 'special': 0.6, 'super': 1.0, 'ultimate': 1.0}   # the art already holds its hit frame
DEFAULT_HITSTOP = {'strike': 150, 'counter': 150, 'special': 150, 'super': 220, 'ultimate': 300}
KNOCK_PX = {'hit': 6, 'hit_heavy': 18, 'knockdown': 42, 'block_hit': 3, 'parry': 0,
            'launched': 8, 'air_hit': 4, 'spiked': 18, 'thrown': 24, 'pulled': 0, 'guard_crush': 10,   # V6: real travel (was
            'hit_high': 8, 'hit_low': 5, 'hit_back': 18, 'clash': 14}                                    # 4 / 10 / 18); V7 rows
ATTACK_KINDS = ('strike', 'special', 'super', 'ultimate', 'counter')
# V7 picker weights: the shared unarmed-era strikes step back so the weapon moves carry the fight
SHARED_K = 0.55
TYPE_W = {'string': 1.0, 'gust': 0.9, 'riposte': 0.25}
P_THROW, P_GUARD_BREAK, P_THROUGH, P_PULL, P_STRING, P_BOOMERANG, P_ARMOR, P_LAUNCH = 0.10, 0.08, 0.12, 0.4, 0.22, 0.5, 0.45, 0.6
GUARD_CHIP = 12
P_CLASH = 0.35                          # share of blocked / parried weapon strikes that become a weapon lock instead
CLASH_PUSH = 14                         # px each fighter skids back when a clash breaks
NO_CLASH = ('bow',)                     # families whose weapon cannot lock blades


def strike_pool(atlas):
    pool = [m for m in STRIKES if m in atlas.anim]
    s = atlas.signature()['strike']
    if s and s not in pool:
        pool.append(s)
    return pool


def of_type(atlas, typ):
    """V7: the atlas's moves of one `type` (anim.json), in row order."""
    return [n for n, a in atlas.anim.items() if a.get('type') == typ]


def first_of_type(atlas, typ):
    m = of_type(atlas, typ)
    return m[0] if m else None


def combo_of(atlas):
    """V7: the character's 3-hit string (anim.json top-level `combo`), only when every move of it exists."""
    c = (getattr(atlas, 'meta', None) or {}).get('combo') or []
    return list(c) if len(c) >= 2 and all(m in atlas.anim for m in c) else []


def can_clash(A, D, move):
    """V7: both fighters have the clash row, the move is a weapon strike of a family that can lock, and so is the guard."""
    if 'clash' not in A.anim or 'clash' not in D.anim:
        return False
    a, fa = A.anim.get(move) or {}, (A.anim.get('clash') or {}).get('family')
    fam = lambda X: next((m.get('family') for m in X.anim.values() if m.get('family')), None)
    return a.get('hit') in ('slash', 'pierce') and fam(A) not in NO_CLASH and fam(D) not in NO_CLASH


def directional(A, D, beats):
    """V7 contact: a light hit plays the defender's high / low reaction by the move's `height`, a dash-through cut plays
    `hit_back` (pitched forward).  Beats keep their damage, timing and knock; only `react` changes, and only to rows the
    defender really has."""
    for b in beats:
        if b.get('outcome') != 'hit' or b.get('kind') not in ATTACK_KINDS:
            continue
        X, Y = (A, D) if b.get('who') == 'att' else (D, A)
        h = (X.anim.get(b['anim']) or {}).get('height')
        if b.get('react') == 'hit' and h in ('high', 'low') and f'hit_{h}' in Y.anim:
            b['react'] = f'hit_{h}'
        elif b.get('through') and b.get('react') in ('hit', 'hit_heavy') and 'hit_back' in Y.anim:
            b['react'] = 'hit_back'
    return beats


def can_juggle(A, D):
    return bool(first_of_type(A, 'air')) and all(n in D.anim for n in ('launched', 'air_hit', 'spiked'))


def has_projectile(atlas, move):
    a = atlas.anim.get(move) or {}
    return bool(move) and 'proj_frame' in a and getattr(atlas, 'proj', None) is not None


def damage_of(atlas, move, kind):
    if kind == 'ultimate':
        return DMG_ULTIMATE
    if kind == 'super':
        return DMG_SUPER
    return int(atlas.power(move, 1)) * DMG_PER_POWER


def hitstop_ms(atlas, move, kind):
    """Engine freeze on contact: the move's `hitstop_ms` (or a default per kind) scaled by HITSTOP_K, because the sheets
    already hold the hit frame for most of that time (docs/ANIMATION-NOTES.md)."""
    a = atlas.anim.get(move) or {}
    base = a.get('hitstop_ms') or DEFAULT_HITSTOP.get(kind, 150)
    return max(HITSTOP_FLOOR_MS, int(round(float(base) * HITSTOP_K.get(kind, 0.5))))


def block_hitstop(hs):
    """A blocked hit freezes shorter than a landed one, but still long enough to be drawn."""
    return max(int(HITSTOP_FLOOR_MS * BLOCK_HITSTOP_K), int(hs * BLOCK_HITSTOP_K))


def reach_of(atlas, move, default=20):
    """How far (RES 1 px from the hip) the move's hit frame reaches: anim.json `reach`, else a typical strike."""
    try:
        return float((atlas.anim.get(move) or {}).get('reach') or default) / max(1, getattr(atlas, 'res', 1))
    except (TypeError, ValueError):
        return float(default)


def move_shake(atlas, move):
    """{'frames', 'amp'} the move itself asks for on its hit frame (anim.json `shake`), or None."""
    sh = (atlas.anim.get(move) or {}).get('shake')
    if isinstance(sh, dict) and sh.get('frames'):
        return dict(frames=int(sh['frames']), amp=float(sh.get('amp', 0)))
    return None


def weighted(rng, items):
    """Deterministic weighted choice from [(item, weight)] with the caller's rng."""
    total = sum(max(0.0, w) for _, w in items)
    if total <= 0:
        return items[0][0]
    r = rng.random() * total
    acc = 0.0
    for it, w in items:
        acc += max(0.0, w)
        if r < acc:
            return it
    return items[-1][0]


class Picker:
    """One fighter's move picker.  `counts` is the per-match tally (tests, previews)."""

    def __init__(self, rng, atlas):
        self.rng, self.atlas = rng, atlas
        self.sig = atlas.signature()
        self.last = None
        self.used = Counter()
        self.counts = Counter()

    def new_round(self):
        self.used = Counter()

    def strikes(self):
        """Shared strikes + the signature strike + (V7) the weapon family's moves, weighted so no one move dominates."""
        pool = strike_pool(self.atlas)
        sig = self.sig['strike']
        v7 = [(m, TYPE_W[a['type']]) for m, a in self.atlas.anim.items() if a.get('type') in TYPE_W and a.get('cat') == 'strike']
        k = SHARED_K if v7 else 1.0
        return [(m, STRIKE_W.get(m, 0.8) * k if m != sig else 0.8) for m in pool] + v7

    def pick(self, cands, prefer=None):
        """cands: [(move, weight)].  Never the last move again, never a third use in a round, while anything else is
        available; `prefer` (a list of names) multiplies those weights."""
        if not cands:
            return None
        if prefer:
            cands = [(m, w * (2.5 if m in prefer else 1.0)) for m, w in cands]
        ok = [(m, w) for m, w in cands if m != self.last and self.used[m] < MAX_PER_ROUND and w > 0]
        if not ok:
            ok = [(m, w) for m, w in cands if m != self.last and w > 0]
        if not ok:
            ok = [(m, w) for m, w in cands if w > 0] or [(m, 1.0) for m, _ in cands]
        m = weighted(self.rng, ok)
        self.note(m)
        return m

    def note(self, move):
        self.last = move
        self.used[move] += 1
        self.counts[move] += 1


# ---------------------------------------------------------------- the exchange grammar
def plan_exchange(rng, att, dfn, sit):
    """-> dict(kind, beats, range_after, air, opener).  `att` / `dfn` are Pickers; `sit` describes the moment:
         range     'close' | 'far'
         meter     the attacker's hit meter (unlocks a super at METER_SUPER)
         ult_ok    the attacker still has its once-per-match ultimate
         dramatic  the attacker is below ULT_HP (dramatic()): when the ultimate is allowed
         ult_sure  the caller already rolled ULT_CHANCE (rounds.make_match rolls once per match): no second roll
         edge      story tilt in [-EDGE_MAX, EDGE_MAX] (edge_for): + lands more often, - gets defended more
         comeback  the round's comeback exchange: a strike that lands, then a full combo
         boost     the attacker's agent just finished a task: its signature super lands (signature strike without one)
         friendly  spar / clash: no supers, no ultimates, no knockdowns, nothing that empties a bar
         air       an air-to-air exchange (jump-in kicks; the arena hovers both)
         k         exchange index within the round
       Every random draw goes through `rng`; same inputs -> same beats on both sides."""
    A, D = att.atlas, dfn.atlas
    far = sit.get('range') == 'far'
    friendly = bool(sit.get('friendly'))
    air = bool(sit.get('air'))
    sig = att.sig
    beats = []
    kind = 'strike'
    fresh = lambda m: bool(m) and m != att.last and att.used[m] < MAX_PER_ROUND      # the no-repeat rule binds specials and supers too
    boost = bool(sit.get('boost'))                                       # V6: the agent just finished a task: its signature super lands
    comeback = bool(sit.get('comeback')) and not boost
    sup_ok = bool(sig['super']) and sig['super'] != A.ultimate()
    if boost and sup_ok:
        kind = 'super'
    elif boost or comeback:
        kind = 'strike'
    elif not friendly:
        if sit.get('ult_ok') and sit.get('dramatic') and A.ultimate() and (sit.get('ult_sure') or rng.random() < ULT_CHANCE):
            kind = 'ultimate'
        elif sup_ok and fresh(sig['super']) and sit.get('meter', 0) >= METER_SUPER and rng.random() < SUPER_CHANCE:
            kind = 'super'
        elif has_projectile(A, sig['special']) and fresh(sig['special']) and rng.random() < (0.4 if far else 0.08):
            kind = 'special'
    elif far and has_projectile(A, sig['special']) and fresh(sig['special']) and rng.random() < 0.3:
        kind = 'special'
    opener = None
    if air:
        opener = 'jump'
    elif far:
        if kind == 'strike':
            opener = weighted(rng, [('dash', 0.4), ('jump', 0.3), ('lunge', 0.3)])   # dash-in jab / jump-in kick / long sliding lunge
        elif kind == 'super' or (kind == 'ultimate' and not sit.get('ult_reaches')):
            opener = 'dash'                                                  # close-range finishers close the gap first
    elif kind == 'strike':
        opener = weighted(rng, [(None, 0.6), ('jump', 0.15), ('sweep', 0.25)])
    if opener in ('dash', 'jump'):
        if opener in A.anim:
            beats.append(dict(who='att', kind='move', anim=opener, dx=1))
        else:
            opener = None
    # ---- the first attack
    if kind == 'strike':
        if boost and sig['strike']:
            move = sig['strike']
            att.note(move)
        elif opener == 'sweep':                                         # through the picker: a sweep prefers the low kick, never forces it
            move = att.pick(att.strikes(), prefer=['low_kick'] if 'low_kick' in A.anim else None)
        elif opener == 'lunge':                                         # one long sliding strike from range (rounds.py slides it in)
            move = att.pick(att.strikes(), prefer=['roundhouse', 'low_kick'])  # a sliding kick (cross is already favoured by dash-ins, counters, combos)
        elif comeback:
            move = att.pick(att.strikes(), prefer=['uppercut', 'roundhouse'])
        elif opener == 'jump':
            move = att.pick(att.strikes(), prefer=[k for k in KICKS if k in A.anim])
        elif opener == 'dash':
            move = att.pick(att.strikes(), prefer=['jab', 'cross'])
        else:
            move = att.pick(att.strikes())
    elif kind == 'special':
        move = sig['special']
        att.note(move)
    elif kind == 'super':
        move = sig['super']
        att.note(move)
    else:
        move = A.ultimate()
        att.note(move)
    # ---- V7: the weapon-family variants of a plain strike exchange (throw, guard break, dash-through, chain pull, string)
    plain = kind == 'strike' and not (air or boost or comeback)
    v7 = _v7_variant(rng, att, dfn, sit, far, friendly) if plain and opener != 'sweep' else None
    if v7 is not None:
        if v7[0] in ('through', 'pull') and opener in ('dash', 'jump', 'lunge'):
            beats = [b for b in beats if b.get('kind') != 'move']    # these close the gap themselves
        opener = v7[0] if v7[0] in ('through', 'pull') else opener
        beats.extend(v7[1])
        return _finish(rng, att, dfn, A, D, beats, kind, air, opener, boost, comeback)
    if kind == 'special' and far and not friendly:
        bm = first_of_type(A, 'boomerang')
        if bm and has_projectile(A, bm) and fresh(bm) and rng.random() < P_BOOMERANG:
            move = bm
            att.note(move)
    dmg = damage_of(A, move, kind)
    first = _resolve(rng, A, D, move, kind, dmg, friendly, edge=float(sit.get('edge') or 0.0), force_hit=boost or comeback)
    if opener == 'lunge':
        first['lunge'] = True
    if boost:
        first['boost'] = True
    meta = A.anim.get(move) or {}
    if meta.get('type') == 'boomerang':
        first['boomerang'] = True
    if first['outcome'] == 'hit' and meta.get('armor') and not friendly and 'jab' in D.anim and rng.random() < P_ARMOR:
        first['armor'] = dict(anim='jab', dmg=DMG_PER_POWER)          # the defender's poke bounces off the wind-up
    if meta.get('type') == 'gust' and first['outcome'] == 'hit':
        first['knock'] = KNOCK_PX['hit_heavy'] + 10                   # the wind shoves
    beats.append(first)
    # ---- what follows the first attack
    if first['outcome'] == 'parry' and not air:
        rip = first_of_type(D, 'riposte')
        if rip and dfn.last != rip and rng.random() < 0.7:
            counter = rip
            dfn.note(rip)
        else:
            counter = dfn.pick(dfn.strikes(), prefer=['cross', 'uppercut'])
        cdmg = damage_of(D, counter, 'strike')
        react = 'hit_heavy' if cdmg >= 2 * DMG_PER_POWER else 'hit'
        beats.append(dict(who='dfn', kind='counter', anim=counter, dmg=cdmg, outcome='hit', pre=None, react=react,
                          hitstop=hitstop_ms(D, counter, 'counter'), knock=KNOCK_PX[react], down=False, riposte=counter == rip))
    elif first['outcome'] == 'whiff' and kind == 'ultimate' and 'taunt' in D.anim:
        beats.append(dict(who='dfn', kind='emote', anim=_taunt(rng, D)))
    elif (first['outcome'] == 'hit' and plain and move == 'uppercut' and not friendly and can_juggle(A, D)
          and rng.random() < P_LAUNCH):
        _launch(rng, att, beats, first)                                     # V7: the launcher pops them up: juggle, spike
    elif first['outcome'] == 'hit' and kind == 'strike' and not air and not boost and not first['down'] and (comeback or rng.random() < 0.55):
        chain = _combo(rng, att, move)
        for i, m in enumerate(chain):
            d = damage_of(A, m, 'strike')
            if comeback or rng.random() < 0.85:
                last = i == len(chain) - 1
                big = d >= 3 * DMG_PER_POWER or (last and len(chain) >= 2 and d >= 2 * DMG_PER_POWER)
                down = (not friendly) and last and big and rng.random() < 0.6
                react = 'knockdown' if down else ('hit_heavy' if d >= 2 * DMG_PER_POWER else 'hit')
                beats.append(dict(who='att', kind='strike', anim=m, dmg=d, outcome='hit', pre=None, react=react,
                                  hitstop=hitstop_ms(A, m, 'strike'), knock=KNOCK_PX[react], down=down))
                if last and m == 'uppercut' and not down and not friendly and can_juggle(A, D) and rng.random() < P_LAUNCH:
                    _launch(rng, att, beats, beats[-1])                  # V7: launcher -> air slash -> spike
                elif last and m == 'uppercut' and not down and 'jump' in A.anim and rng.random() < 0.5:
                    _juggle(rng, att, beats, friendly)                   # the launcher pops them up: jump after them, kick
            else:
                pre = 'block' if 'block' in D.anim else None
                beats.append(dict(who='att', kind='strike', anim=m, dmg=0, outcome='block', pre=pre, react='block_hit' if 'block_hit' in D.anim else None,
                                  hitstop=block_hitstop(hitstop_ms(A, m, 'strike')), knock=KNOCK_PX['block_hit'], down=False))
                break
    return _finish(rng, att, dfn, A, D, beats, kind, air, opener, boost, comeback)


def _finish(rng, att, dfn, A, D, beats, kind, air, opener, boost, comeback):
    """Pressure or a spacing reset after the exchange's attacks -> the plan_exchange result."""
    range_after = 'close'
    if air:
        range_after = 'close'
    elif rng.random() < 0.35:
        loser = 'dfn' if beats[-1].get('outcome') == 'hit' and beats[-1]['who'] == 'att' else 'att'
        anim = weighted(rng, [('backdash', 0.5), ('walk_back', 0.5)])
        who = loser if anim == 'backdash' else 'att'
        actor = A if who == 'att' else D
        if anim in actor.anim:
            beats.append(dict(who=who, kind='move', anim=anim, dx=-1))
            range_after = 'far'
    elif beats[-1].get('down'):
        range_after = 'far'
    directional(A, D, beats)
    return dict(kind=kind, beats=beats, range_after=range_after, air=air, opener=opener, boost=boost, comeback=comeback)


def _juggle(rng, att, beats, friendly):
    """Air juggle after a landed launcher: the attacker jumps in place and meets the airborne defender with a kick."""
    A = att.atlas
    m = att.pick([(k, 1.0) for k in KICKS if k in A.anim] or att.strikes())
    if not m:
        return
    d = damage_of(A, m, 'strike')
    down = not friendly
    react = 'knockdown' if down else 'hit_heavy'
    beats.append(dict(who='att', kind='move', anim='jump', dx=0, juggle=True))
    beats.append(dict(who='att', kind='strike', anim=m, dmg=d, outcome='hit', pre=None, react=react, juggle=True,
                      hitstop=hitstop_ms(A, m, 'strike'), knock=KNOCK_PX[react], down=down))


def _taunt(rng, atlas):
    """V7: the character's own taunt variant half the time."""
    return 'taunt2' if 'taunt2' in atlas.anim and rng.random() < 0.5 else 'taunt'


def _strike_beat(A, move, outcome='hit', react=None, down=False, dmg=None, **flags):
    d = damage_of(A, move, 'strike') if dmg is None else dmg
    if react is None and outcome == 'hit':
        react = 'hit_heavy' if d >= 2 * DMG_PER_POWER else 'hit'
    b = dict(who='att', kind='strike', anim=move, dmg=d, outcome=outcome, pre=None, react=react,
             hitstop=hitstop_ms(A, move, 'strike'), knock=KNOCK_PX.get(react, KNOCK_PX['hit']) if react else 0, down=down)
    b.update(flags)
    return b


def _launch(rng, att, beats, launcher):
    """V7 air juggle: the landed launcher pops the defender up (`launched`), the attacker leaps after it with its `air`
    move (`air_hit`), then spikes it into the floor (`spiked`, a knockdown with a get-up)."""
    A = att.atlas
    launcher.update(react='launched', knock=KNOCK_PX['hit'], down=False, juggle=True, launch=True)
    air = first_of_type(A, 'air')
    att.note(air)
    beats.append(_strike_beat(A, air, react='air_hit', juggle=True))
    beats[-1]['knock'] = 4
    sp = first_of_type(A, 'spike')
    if sp:
        att.note(sp)
        beats.append(_strike_beat(A, sp, react='spiked', down=True, juggle=True, spike=True))
        beats[-1]['knock'] = KNOCK_PX['hit_heavy']
    else:
        beats[-1].update(react='spiked', down=True)


def _v7_variant(rng, att, dfn, sit, far, friendly):
    """-> (variant, beats) or None.  One draw decides which weapon-family variant (if any) this exchange is; the beats
    follow the same grammar as every other exchange (one attack beat per move, the defender's answer inside it)."""
    A, D = att.atlas, dfn.atlas
    has = lambda n: n in D.anim
    r = rng.random()
    if far:
        pull = first_of_type(A, 'pull')
        thr = first_of_type(A, 'through')
        pull_ok = bool(pull) and has('pulled') and att.last != pull and att.used[pull] < MAX_PER_ROUND
        p_pull = P_PULL if pull_ok else 0.0
        if pull_ok and r < p_pull:
            att.note(pull)
            if rng.random() >= 0.8:                                             # the chain misses: the defender hops back
                b = _strike_beat(A, pull, outcome='whiff', dmg=0)
                b.update(pre='backdash', hitstop=0)
                return 'pull', [b]
            beats = [_strike_beat(A, pull, react='pulled', pull=True)]
            beats[0]['knock'] = 0
            if 'uppercut' in A.anim and not friendly and can_juggle(A, D) and rng.random() < 0.7:
                att.note('uppercut')
                up = _strike_beat(A, 'uppercut', chain=True)                    # chain pull into the launcher, then the juggle
                beats.append(up)
                _launch(rng, att, beats, up)
            else:
                beats.append(_strike_beat(A, att.pick(att.strikes()), chain=True))
            return 'pull', beats
        if thr and att.used[thr] < MAX_PER_ROUND and att.last != thr and p_pull <= r < p_pull + P_THROUGH:
            att.note(thr)
            out = weighted(rng, [('hit', 0.65), ('block', 0.2 if has('block') else 0.0), ('whiff', 0.15)])
            if out == 'hit':
                return 'through', [_strike_beat(A, thr, through=True)]
            if out == 'block':
                b = _strike_beat(A, thr, outcome='block', dmg=0, through=True,
                                 react='block_hit' if has('block_hit') else 'block')
                b.update(pre='block', hitstop=block_hitstop(b['hitstop']), knock=KNOCK_PX['block_hit'])
                return 'through', [b]
            b = _strike_beat(A, thr, outcome='whiff', dmg=0, through=True)
            b['hitstop'] = 0
            return 'through', [b]
        return None
    thw = first_of_type(A, 'throw')
    gb = first_of_type(A, 'guard_break')
    if thw and not friendly and has('thrown') and att.last != thw and att.used[thw] < MAX_PER_ROUND and r < P_THROW:
        att.note(thw)
        if rng.random() < 0.78:
            return 'throw', [_strike_beat(A, thw, react='thrown', down=True, throw=True)]
        b = _strike_beat(A, thw, outcome='whiff', dmg=0, throw=True)            # the defender slips the grab
        b.update(pre='backdash', hitstop=0)
        return 'throw', [b]
    if gb and has('guard_crush') and att.last != gb and att.used[gb] < MAX_PER_ROUND and r < P_THROW + P_GUARD_BREAK:
        att.note(gb)
        b = _strike_beat(A, gb, outcome='guard_break', react='guard_crush', dmg=GUARD_CHIP, guard_break=True)
        b['pre'] = 'block' if has('block') else None
        nxt = att.pick(att.strikes(), prefer=of_type(A, 'string'))
        return 'guard_break', [b, _strike_beat(A, nxt, chain=True)]                     # the opening is free
    combo = combo_of(A)
    if combo and r < P_THROW + P_GUARD_BREAK + P_STRING and att.last != combo[0] and att.used[combo[0]] < MAX_PER_ROUND:
        beats = []
        for i, m in enumerate(combo):
            att.note(m)
            if i == 0:
                b = _resolve(rng, A, D, m, 'strike', damage_of(A, m, 'strike'), friendly, edge=float(sit.get('edge') or 0.0))
                b['string'] = True
                beats.append(b)
                if b['outcome'] != 'hit' or b['down']:
                    break
            else:
                last = i == len(combo) - 1
                big = damage_of(A, m, 'strike') >= 3 * DMG_PER_POWER
                down = (not friendly) and last and big and rng.random() < 0.6
                beats.append(_strike_beat(A, m, react='knockdown' if down else None, down=down, string=True))
        return 'string', beats
    return None


def edge_for(hp_att, hp_dfn, wins_att=0, wins_dfn=0):
    """Story tilt for one exchange, in [-EDGE_MAX, EDGE_MAX]; positive favours the attacker.  The fighter behind on HP or
    on rounds lands a little more often and the leader gets defended a little more, so matches swing instead of snowballing."""
    e = (float(hp_dfn) - float(hp_att)) / 100.0 * 0.5 + 0.12 * (int(wins_dfn) - int(wins_att))
    return max(-EDGE_MAX, min(EDGE_MAX, e))


def _resolve(rng, A, D, move, kind, dmg, friendly, edge=0.0, force_hit=False):
    """The defender's answer to the first attack, as a strike beat.  `edge` tilts hit vs defence (edge_for); `force_hit`
    (a comeback exchange, a boost super) skips the defender's choice."""
    has = lambda n: n in D.anim
    if force_hit:
        outcome = 'hit'
    elif kind == 'ultimate':
        outcome = weighted(rng, [('hit', 0.8), ('whiff', 0.2 if has('backdash') else 0.0)])
    elif kind == 'super':
        outcome = weighted(rng, [('hit', 0.78), ('whiff', 0.14 if has('backdash') else 0.0), ('parry', 0.08 if has('parry') else 0.0)])
    elif kind == 'special':
        outcome = weighted(rng, [('hit', 0.45), ('block', 0.55 if has('block') else 0.0)])
    elif dmg >= 3 * DMG_PER_POWER:
        outcome = weighted(rng, [('hit', 0.6), ('whiff', 0.14 if has('backdash') else 0.0), ('parry', 0.12 if has('parry') else 0.0),
                                 ('crouch_block', 0.14 if has('crouch_block') and move in HIGHS else 0.0)])
    else:
        outcome = weighted(rng, [('hit', 0.46), ('block', 0.2 if has('block') else 0.0), ('parry', 0.11 if has('parry') else 0.0),
                                 ('whiff', 0.09 if has('backdash') else 0.0), ('crouch_block', 0.14 if has('crouch_block') and move in HIGHS else 0.0)])
    if kind == 'strike' and outcome in ('block', 'parry') and can_clash(A, D, move) and rng.random() < P_CLASH:
        outcome = 'clash'                                    # V7: the two weapons meet and lock instead
    if edge and not force_hit and kind != 'ultimate':
        r = rng.random()                                     # always one extra draw, so both processes stay in step
        if outcome == 'hit' and edge < 0 and r < -edge and (has('block') or has('parry')):
            outcome = 'block' if has('block') else 'parry'
        elif outcome != 'hit' and edge > 0 and r < edge:
            outcome = 'hit'
    pre = react = None
    knock = 0
    down = False
    hs = hitstop_ms(A, move, kind)
    if outcome == 'hit':
        heavy = dmg >= 2 * DMG_PER_POWER
        down = (not friendly) and (kind in ('ultimate', 'super') or dmg >= 3 * DMG_PER_POWER) and rng.random() < (0.9 if kind == 'ultimate' else 0.5)
        react = 'knockdown' if down else ('hit_heavy' if heavy else 'hit')
        knock = KNOCK_PX[react] * (2 if kind == 'ultimate' else 1)
    elif outcome == 'block':
        pre, react, knock, dmg, hs = 'block', ('block_hit' if has('block_hit') else 'block'), KNOCK_PX['block_hit'], 0, block_hitstop(hs)
    elif outcome == 'crouch_block':
        pre, react, knock, dmg, hs = 'crouch_block', ('block_hit' if has('block_hit') else 'crouch_block'), 2, 0, block_hitstop(hs)
    elif outcome == 'parry':
        pre, react, dmg = None, 'parry', 0
    elif outcome == 'clash':
        pre, react, knock, dmg, hs = None, 'clash', CLASH_PUSH, 0, block_hitstop(hs)
    else:                                                    # whiff: the defender is already gone when the hit frame lands
        pre, react, dmg, hs = 'backdash', None, 0, 0
    return dict(who='att', kind=kind, anim=move, dmg=dmg, outcome=outcome, pre=pre, react=react, hitstop=hs, knock=knock, down=down)


def _combo(rng, att, first):
    """Follow-ups after a landed opener: a known chain that starts with it (or a short improvised one), picked without repeats."""
    A = att.atlas
    chains = [c[1:] for c in COMBOS if c[0] == first and all(m in A.anim for m in c)]
    if chains and rng.random() < 0.8:
        chain = list(chains[rng.randrange(len(chains))])
        for m in chain:
            att.note(m)
        return chain
    n = 1 + (rng.random() < 0.4)
    out = []
    for _ in range(n):
        m = att.pick(att.strikes(), prefer=['cross', 'uppercut', 'roundhouse'])
        if m:
            out.append(m)
    return out


def dramatic(wins_att, hp_att, hp_dfn, k, rounds_to_win=2):
    """When an ultimate may come out (V6): only as a desperation move of an attacker below ULT_HP, never in the first two
    exchanges of a round.  (V5 allowed it to anyone up a round, 70% per exchange: 1.7 ultimates per match.)  The caller
    still rolls ULT_CHANCE (plan_exchange) and allows one ultimate per match between both fighters."""
    return k >= 2 and hp_att < ULT_HP


def tally(beats_by_slot):
    """{slot: Counter(move)} of attack picks (strike / special / super / ultimate / counter) from played beats; tests + previews."""
    out = {}
    for slot, beats in beats_by_slot.items():
        c = Counter()
        for b in beats:
            if b.get('kind') in ATTACK_KINDS:
                c[b['anim']] += 1
        out[slot] = c
    return out


# ---------------------------------------------------------------- V7.1: the `air` curve of an airborne row
def _ease(kind, u):
    """The segment shapes of an `air` curve: 'o' rises like a thrown body (fast, then slowing toward the apex), 'i' falls
    like one (slow, then faster), 'h' eases in and out (a hang / float), anything else is linear."""
    if kind == 'o':
        return 1.0 - (1.0 - u) * (1.0 - u)
    if kind == 'i':
        return u * u
    if kind == 'h':
        return u * u * (3.0 - 2.0 * u)
    return u


def air_lift(anim, el_ms):
    """Height (RES 1 px above the floor) of a row's `air` curve `el_ms` into its animation clock (the clock its frames run
    on: hitstop stands still, slow motion slows).  anim.json `air` = [[t_ms, h], [t_ms, h, ease], ...]: before the first
    key the first height, after the last key the last height (a launched fighter keeps hanging), and between two keys
    the later key's ease (_ease).  No `air`: 0.  The art draws the pose (crouch, stretch, tuck, reach); this curve is the
    trajectory, so the motion is smooth at the redraw rate whatever the frame count."""
    keys = (anim or {}).get('air') if isinstance(anim, dict) else None
    if not keys:
        return 0.0
    if el_ms <= keys[0][0]:
        return float(keys[0][1])
    for k0, k1 in zip(keys, keys[1:]):
        if el_ms < k1[0]:
            u = (el_ms - k0[0]) / max(1e-6, float(k1[0] - k0[0]))
            return float(k0[1]) + (float(k1[1]) - float(k0[1])) * _ease(k1[2] if len(k1) > 2 else 'l', u)
    return float(keys[-1][1])


def air_window(anim):
    """-> (t_up, t_down) ms of a row's flight: the last key on the floor before it leaves it, and the first key back on
    the floor after it was up (None when the row ends in the air).  (None, None) for a row without `air`."""
    keys = (anim or {}).get('air') if isinstance(anim, dict) else None
    if not keys:
        return None, None
    up = down = None
    for i, k in enumerate(keys):
        if up is None and float(k[1]) <= 0.0 and i + 1 < len(keys) and float(keys[i + 1][1]) > 0.0:
            up = float(k[0])
        elif up is not None and float(k[1]) <= 0.0:
            down = float(k[0])
            break
    if up is None and keys and float(keys[0][1]) > 0.0:
        up = float(keys[0][0])                                    # a row that starts in the air (air_hit, spiked)
    return up, down
