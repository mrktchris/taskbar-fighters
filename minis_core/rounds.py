"""Rounds, HP and winners (docs/V4-WORKORDER.md "Rounds and winners").

A *match* is best-of-3 rounds.  Both fighters start a round at 100 HP; damage per landed move = power (1/2/3) * 12,
the ultimate does 40; a round ends at 0 HP or after ROUND_CAP_S (higher HP wins, a tie is drawn from the seed).
Who attacks each exchange is drawn from the plan's seed.  In `decided` mode the draw is weighted by each side's
health score = (100 - ctx%) + (20 if not at its limit) + (10 if working); unknown context counts as 50%.  In `random`
mode both sides are even.  The whole match is one deterministic timeline built from the plan, so the two fighter
processes (or the arena) agree on every contact, every HP value and the winner without talking.

Timeline entries are (t, anim, opts) like every other bout; entries whose "anim" starts with '@' are directives:
  @hp      {'hp': {slot: hp}, 'round': n, 'wins': {slot: n}}        publish HP (both sides)
  @fx      {'fx': name, 'anchor': optional}                           spawn an effect on this fighter
  @banner  {'banner': round1|round2|round3|fight|ko|winner, 'until': t, 'over': slot|None}   (left side only)
  @record  {'winner': slot, 'loser': slot, 'score': {slot: n}}        write record.json (left side only)
  @shake   {'frames': n, 'amp': px}                                   the move's own screen shake on its hit frame (V5)
  @flash   {'alpha': a, 'ms': n}                                      white flash (an ultimate landing) (V5; V6 >= 100 ms)
  @impact  {'ms': n, 'on': slot}                                      V6 impact frames on a heavy hit / ultimate / KO (fx `impact` on the
                                                                      struck fighter, a strong flash when that art is missing; nothing
                                                                      at all when control.json `flashes` is off)
  @whiff   {'react_to': move}                                         the attack missed: logged like a reaction, nothing plays (V5)
  @armor   {'hp': {slot: hp}, 'damage': n}                            V7: this fighter took a poke through its armour (HP drops,
                                                                      a short flash, no flinch)
Move entries may carry 'to' + 'slide_ms' (the fighter slides to that x while the move plays: dash-ins, backdashes,
knockback; V6: the slide pauses during hitstop), 'hitstop' (ms both fighters freeze from the contact instant),
'slow' [t0, t1, k] (V6 slow motion: the animation clock runs at k between t0 and t1) and 'hold' (a one-shot keeps its
last frame instead of returning to idle: a brace, a slump).  V7: 'slide_at' (the slide starts at this time instead of
the entry's: a dash-through slides only during its burst, a thrown fighter only once it leaves the ground, a pulled one
on the yank), 'path' [[t, ms, x], ...] (further slide legs after the first: a thrown fighter is hoisted in, then slammed
out) and 'stop_at' (the hitstop starts here: a throw's defender row starts on the grab, its freeze on the slam).

V5 choreography (choreo.py): a seeded no-repeat picker weighted by category and situation; openers (dash-in jab, jump-in
kick, sweep), defender answers (block, crouch block vs highs, parry -> counter, backdash whiff, getting hit), combos with
hitstop, pressure vs spacing resets, specials at range (projectiles), a super when the hit meter fills, the ultimate once
per match at a dramatic moment (round point / low HP) with flash + shake, knockdown -> getup on big hits, a taunt after a
whiffed ultimate, and one air-to-air exchange per round.

W/L per character go to %LOCALAPPDATA%\\minis\\record.json, written atomically; only character ids, never names of
anything else.
"""
from __future__ import annotations
import json, random, time
from pathlib import Path

from . import choreo, config as cfgmod, framedata as F, setpieces
from .choreo import air_window
from .bus import write_json_atomic
from .effects import EffectPlayer

HP_MAX = 100
DMG_PER_POWER = 12
DMG_ULTIMATE = 40
ROUND_CAP_S = 25.0
ROUNDS_TO_WIN = 2
MODES = ('decided', 'random')
BANNER_S = {'round': 1.2, 'fight': 0.7, 'ko': 1.5, 'winner': 2.6, 'time': 1.2}
NEEDS = ('block', 'block_hit', 'hit', 'hit_heavy', 'knockdown', 'ko', 'getup', 'taunt', 'victory', 'idle')
STRIKES = ('jab', 'cross', 'uppercut', 'low_kick', 'roundhouse')


# ---------------------------------------------------------------- health score
def health_score(state, ctx_pct) -> float:
    """(100 - ctx%) + 20 if not at the limit + 10 if working.  Unknown context counts as 50%."""
    ctx = 50.0 if ctx_pct is None else max(0.0, min(100.0, float(ctx_pct)))
    return (100.0 - ctx) + (0.0 if state == 'limit' else 20.0) + (10.0 if state == 'working' else 0.0)


def score_of_snapshot(snap) -> float:
    return health_score(getattr(snap, 'state', None), getattr(snap, 'ctx_pct', None)) if snap is not None else health_score(None, None)


def score_of_bus(payload) -> float:
    p = payload or {}
    return health_score(p.get('state'), p.get('ctx'))


def p_left(mode, scores, left, right) -> float:
    """Probability that the left fighter attacks a given exchange."""
    if mode != 'decided':
        return 0.5
    a, b = float(scores.get(left, 0.0)), float(scores.get(right, 0.0))
    if a + b <= 0 or abs(a - b) < 1e-9:
        return 0.5
    return a / (a + b)


def damage_of(atlas, move) -> int:
    if move == atlas.ultimate() and move not in STRIKES:
        return DMG_ULTIMATE
    return int(atlas.power(move, 1)) * DMG_PER_POWER


# ---------------------------------------------------------------- the match timeline
def strike_pool(atlas):
    return choreo.strike_pool(atlas)


def possible(atlases_by_slot) -> bool:
    for a in atlases_by_slot.values():
        if any(n not in a.anim for n in NEEDS) or not strike_pool(a):
            return False
    return True


def _contact_s(atlas, move):
    a = atlas.anim[move]
    if 'hit_frame' in a:
        return atlas.contact_ms(move) / 1000.0
    return atlas.total_ms(move) * 0.6 / 1000.0            # a charge-then-release super / ultimate without hit_frame metadata


# ---------------------------------------------------------------- shared bout machinery (V5: choreo.py drives both the match and spar / clash)
CLOSE_EXTRA, FAR_EXTRA = 14, 40       # hip distance beyond gap_px that counts as "far"; where a spacing reset puts them
KNOCK_SLIDE_MS = 180
KNOCK_SLIDE_MS_BIG = 300              # V6: a heavy hit / knockdown slides further, so it takes longer (skid + dust)
SPAN_PX = 110                         # a bout never drifts further than this from its centre (the zone is not in the plan)
MIN_APART = 22                        # V6: hips closer than this overlap the bodies (idle sprites are ~24 px wide; was 12)
BODY_FRONT = 9                        # V6: px from a defender's hip to the front of its body: a strike stands at reach + this
LUNGE_FRAC = 0.85                     # a lunge slides in over this share of the move's wind-up
IMPACT_MS = 130                       # V6 impact frames (heavy hits, ultimates, KOs): 100-160 ms
FLASH_MS = 120                        # V6 white flash on an ultimate landing (was 60 ms: shorter than one redraw)
KO_HITSTOP_MS = 280                   # the match-deciding blow freezes longer...
SLOW_S, SLOW_K = 0.55, 0.35           # ...then plays the fall in slow motion: SLOW_S wall seconds at SLOW_K speed
POST_KO_S = 3.4                       # final KO contact -> end of the match (finisher beat: freeze, fall, dust, pose, slump up)
POST_KO_MAX_S = 3.5
GETUP_SLOW_K = 0.6                    # the beaten fighter's get-up after the final KO plays at this speed (a slump, not a kip-up)
SLUMP = ('facepalm', 'shrug', 'dizzy')    # a fighter that lost on time slumps instead of falling over
BRACE_MIN_S = 0.45                    # a wind-up at least this long gets a guard / worried pose from the defender
WORRIED_HP = 30
STAND_OVERLAP = 8                     # two idle silhouettes (weapons included) may overlap by this much, never more
HIT_FX = {'slash': 'hit_slash', 'blunt': 'hit_blunt', 'pierce': 'hit_pierce'}   # V7 contact sparks by the move's `hit`
POWER_SHAKE = {2: {'frames': 2, 'amp': 1.0}, 3: {'frames': 3, 'amp': 2.0}}         # V7: landed hits shake by power
CLASH_SKID = 14                       # px each fighter skids back when a weapon lock breaks
CLASH_GAP = 12                        # extra room between the hips while two weapons are locked
LONG_FREEZE_MS = 250                  # V7: above this the defender freezes on its hit pose, after the flash frame
LYING = ('knockdown', 'spiked', 'thrown')         # V7: reactions that end on the floor (a get-up follows, or the KO)
AIRBORNE = ('launched', 'air_hit')                # V7: juggle reactions that hang in the air until the next hit
V7_SPECIAL = ('juggle', 'throw', 'through', 'pull')     # beats a KO must not turn into the signature strike
FLINCH = ('hit', 'hit_heavy', 'hit_high', 'hit_low', 'hit_back')      # V9: reactions whose length the hitstun sets
TUMBLE_FROM = FLINCH + ('knockdown',)            # V9: a hit that tumbles plays the knockdown row along a real arc
HITSTUN_CAP_S = 0.9                              # V9: the taskbar's bouts keep moving: a stun never holds longer than this
TUMBLE_AIR_MS = (50, 210)                        # V9: the knockdown row's airborne frames (after the flash, before it lands)
MISSED_TECH_S = 0.45                             # V9: a fighter that misses its tech lies this long before getting up


def body_front(atlas):
    """px (RES 1) from the hip to the front edge of the idle silhouette, weapon included: how much room a fighter takes up
    toward its opponent.  Read from the art, so a redrawn or new character spaces itself."""
    key = '_v6_front'
    v = getattr(atlas, key, None)
    if v is None:
        try:
            bb = atlas.frame_image('idle', 0, 1).getbbox()
            v = max(8.0, (bb[2] - atlas.anchor(1)) / float(max(1, atlas.res))) if bb else 14.0
        except Exception:
            v = 14.0
        try:
            setattr(atlas, key, v)
        except Exception:
            pass
    return v


class _Emitter:
    """Per-slot timeline entries with a LAZY return to idle: a chained move (combo, counter) starting before the previous
    move's return cancels that return, so the sorted timeline never idles a fighter mid-combo."""

    def __init__(self, slots, t0):
        self.tl = {s: [] for s in slots}
        self.pending = {s: None for s in slots}
        self.free = {s: t0 for s in slots}

    def play(self, slot, t, anim, opts, dur, then='idle'):
        p = self.pending[slot]
        if p is not None and p[0] < t - 1e-6:                   # a return that would start with the next move is dropped
            self.tl[slot].append((p[0], p[1], {}))
        self.pending[slot] = (t + dur, then) if then else None
        self.tl[slot].append((t, anim, opts))
        self.free[slot] = t + dur

    def directive(self, slot, t, name, opts):
        self.tl[slot].append((t, name, opts))

    def mark(self):
        return {s: len(v) for s, v in self.tl.items()}, dict(self.pending), dict(self.free)

    def rollback(self, m):
        lens, pend, free = m
        for s in self.tl:
            del self.tl[s][lens[s]:]
        self.pending, self.free = dict(pend), dict(free)

    def finish(self):
        for s, p in self.pending.items():
            if p is not None:
                self.tl[s].append((p[0], p[1], {}))
            self.pending[s] = None


class Bout:
    """Plays choreo beats into an _Emitter with positions, HP, hit meters, projectiles and effects.  `friendly` (spar /
    clash) has no HP, no supers / ultimates / knockdowns.  Deterministic in (plan, atlases, fx)."""

    def __init__(self, plan, atlases, fx=None, friendly=False):
        self.left, self.right = plan['left'], plan['right']
        chars = plan.get('chars') or {}
        self.A = {s: atlases[chars.get(s, s)] for s in (self.left, self.right)}
        self.rng = random.Random(plan['seed'])
        self.fx = fx
        self.friendly = friendly
        self.pos = {s: float(plan['pos'][s]) for s in (self.left, self.right)}
        self.mid = (self.pos[self.left] + self.pos[self.right]) / 2.0
        # V6: the pair's own room: idle silhouettes (weapons included) overlap by at most STAND_OVERLAP
        self.apart = max(MIN_APART, body_front(self.A[self.left]) + body_front(self.A[self.right]) - STAND_OVERLAP)
        self.gap = max(self.apart, abs(self.pos[self.right] - self.pos[self.left])) or 24.0
        self.span = float(plan.get('span', SPAN_PX))
        self.facing = {self.left: 1, self.right: -1}
        self.pick = {s: choreo.Picker(self.rng, self.A[s]) for s in (self.left, self.right)}
        self.em = _Emitter((self.left, self.right), plan['t0'])
        self.hp = {self.left: HP_MAX, self.right: HP_MAX}
        self.meter = {self.left: 0.0, self.right: 0.0}
        self.used_ult = {self.left: False, self.right: False}
        self.ult_used = False                               # V6: one ultimate per MATCH between both fighters
        self.boost = [s for s in (plan.get('boost') or []) if s in (self.left, self.right)]     # finished a task: super first
        self.final = False                                  # set by make_match: a KO in this exchange ends the match
        self.ko_info = None                                 # (tc, hitstop s, slow window) of the last KO hit
        self.down_until = {}                                # slot -> when its get-up ends (no hits on a fighter on the floor)
        self.pct = {self.left: 0.0, self.right: 0.0}        # V9: accumulated damage this round (later hits launch further)
        self.fd_rng = random.Random((int(plan['seed']) * 7919 + 101) & 0xFFFFFFFF)   # V9: DI / tech draws, its own stream
        self.fd_log = []                                    # V9: every landed hit's frame data (tests, the QA log)
        self.wins = {self.left: 0, self.right: 0}
        self.projs = []
        self.beats = {self.left: [], self.right: []}        # every beat played, by the fighter that played it (tests, previews)
        self.n_air = 0
        self.last_att = None
        self.last_hit = False

    # ---- helpers
    def other(self, s):
        return self.right if s == self.left else self.left

    def tot(self, s, n):
        return self.A[s].total_ms(n) / 1000.0 if n in self.A[s].anim else 0.0

    def dist(self):
        return abs(self.pos[self.right] - self.pos[self.left])

    def range(self):
        return 'far' if self.dist() > self.gap + CLOSE_EXTRA else 'close'

    def face(self, s):
        """+1 when the opponent stands to the right.  V7: a dash-through swaps sides, so facing follows the positions."""
        o = self.other(s)
        if abs(self.pos[o] - self.pos[s]) < 1e-6:
            return self.facing[s]
        return 1 if self.pos[o] > self.pos[s] else -1

    def clamp(self, s, x, order=True, near=None):
        """Inside the bout's span and (order=True) never closer than `apart` (or `near`) on the fighter's own side of the
        opponent."""
        lo, hi = self.mid - self.span, self.mid + self.span
        x = max(lo, min(hi, x))
        if not order:
            return x
        o = self.other(s)
        gap = self.apart if near is None else near
        if self.face(s) > 0:
            x = min(x, self.pos[o] - gap)
        else:
            x = max(x, self.pos[o] + gap)
        # V7.1: the span wins (it is the zone the brains really move in): a fighter knocked toward the edge stops there,
        # a little closer than `apart`, instead of being planned outside the zone and clamped there by the brain alone
        return max(lo, min(hi, x))

    def travel(self, s, anim, t, x, dur):
        """Slide options for a locomotion row that moves the fighter to x.  V7.1: a row with an `air` curve (a jump) only
        travels while it is in the air, at a constant speed (a body in flight), so it takes off from where it crouched
        and comes down on its planned landing spot; everything else slides over the whole row, easing out."""
        up, down = air_window(self.A[s].anim.get(anim))
        if up is not None and down is not None and down > up:
            return {'to': x, 'slide_ms': int(down - up), 'slide_at': round(t + up / 1000.0, 4), 'ease': 'lin'}
        return {'to': x, 'slide_ms': int(dur * 1000)}

    def apex_s(self, s, anim, default):
        """Seconds from the start of an airborne row to its highest point (the hang), from its `air` curve."""
        keys = (self.A[s].anim.get(anim) or {}).get('air')
        if not keys:
            return default
        top = max(float(k[1]) for k in keys)
        at = [float(k[0]) for k in keys if float(k[1]) >= top - 1e-6]
        return (at[0] + at[-1]) / 2000.0

    def fx_reach(self, name):
        if self.fx is None:
            return 0.0
        return EffectPlayer(self.fx, res=self.A[self.left].res).reach(name)

    def fx_lead(self, name):
        return _fx_hit_s(self.fx.get(name)) if self.fx is not None else 0.0

    def frame_data(self, who, tgt, b, move, kind, outcome, dmg, react, ko, last_hit):
        """V9 platform-fighter frame data for one contact (framedata.py): -> dict(hitlag ms (both fighters), knock px,
        stun s, react, tumble arc or None, tech) or None when nothing landed.  The target's percentage grows by the hit
        first, so the hit counts itself, and later hits in a round launch further."""
        if outcome not in ('hit', 'guard_break', 'block', 'crouch_block', 'parry'):
            return None
        Aw, At = self.A[who], self.A[tgt]
        a = Aw.anim.get(move) or {}
        d = dmg * F.PCT_PER_HP
        if outcome in ('block', 'crouch_block', 'parry'):
            d = choreo.damage_of(Aw, move, kind) * F.PCT_PER_HP if not d else d
            lag = max(int(b.get('hitstop') or 0), int(F.hitlag_ms(d * F.HITLAG_DMG_K * F.BLOCK_LAG_K)))
            push = 0.0 if outcome == 'parry' else F.shield_push_px(d)
            return dict(hitlag=lag, knock=push, stun=F.ms(F.shieldstun_frames(d)) / 1000.0, react=react, arc=None,
                        kb=0.0, block=True)
        if not self.friendly:
            self.pct[tgt] += d
        pct = self.pct[tgt] if not self.friendly else d
        s, base, ang = F.move_kb(Aw.power(move, 1), a.get('height'), kind)
        if a.get('type') == 'spike' or b.get('spike'):
            ang = F.SPIKE_ANGLE
        ang = F.di(ang, self.fd_rng)
        kb = F.knockback(pct, d, F.weight_of(At.meta.get('family') or (At.anim.get('riposte') or {}).get('family')), s, base)
        lag = int(F.hitlag_ms(d * 2.0 * F.HITLAG_DMG_K))
        lag = max(choreo.HITSTOP_FLOOR_MS, lag, int(b.get('hitstop') or 0) if kind in ('super', 'ultimate') else 0)
        out = dict(hitlag=lag, kb=round(kb, 2), angle=round(ang, 1), pct=round(pct, 2), react=react, arc=None,
                   knock=F.taskbar_knock_px(kb), stun=min(HITSTUN_CAP_S, F.hitstun_ms(kb) / 1000.0), block=False)
        if (F.tumbles(kb) and not ko and not self.friendly and last_hit and react in TUMBLE_FROM and ang > 5
                and not any(b.get(f) for f in ('juggle', 'throw', 'pull', 'through', 'launch')) and 'knockdown' in At.anim):
            keys, airtime, px = F.tumble_arc(kb, ang)
            out.update(react='knockdown', arc=dict(keys=keys, airtime=airtime), knock=px, tech=self.fd_rng.random() < F.TECH_P)
        self.fd_log.append(dict(who=who, tgt=tgt, move=move, kind=kind, dmg=dmg, pct=out['pct'], kb=out['kb'], hitlag=lag,
                                stun=round(out['stun'], 3), knock=round(out['knock'], 1), tumble=out['arc'] is not None))
        return out

    def contact_fx(self, name, fallback):
        """V7: a contact spark by name when the effects sheet has its art, else the older generic one."""
        return name if (name and self.fx is not None and self.fx.has_art(name)) else fallback

    def main_fx(self, s, move):
        """The move's own effect (named after it) from its `fx` list, else its last listed effect."""
        sched = self.A[s].move_fx(move)
        for off, name, until in sched:
            if name == move:
                return name
        return sched[-1][1] if sched else None

    # ---- one exchange
    def exchange(self, att, t, k, dramatic=False, air=False, comeback=False, boost=False, ult_sure=False, piece=None):
        """Plays one exchange starting at `t`.  -> (t_next, ko_loser, played) ; `played` False when nothing fits.
        V7: `piece` (a setpieces name) plays that hand-authored set piece instead of a procedural exchange."""
        dfn = self.other(att)
        A, D = self.A[att], self.A[dfn]
        ult = A.ultimate()
        reach = self.fx_reach(self.main_fx(att, ult)) if ult else 0.0
        edge = 0.0 if self.friendly else choreo.edge_for(self.hp[att], self.hp[dfn], self.wins[att], self.wins[dfn])
        sit = dict(range=self.range(), meter=self.meter[att], ult_ok=(not self.friendly and not self.ult_used), dramatic=dramatic,
                   friendly=self.friendly, air=air and not boost, k=k, ult_reaches=reach >= self.dist() - 10, edge=edge,
                   comeback=comeback and not self.friendly, boost=boost, ult_sure=ult_sure)
        air = sit['air']
        if piece:
            ex = setpieces.resolve(piece, self.pick[att], self.pick[dfn], friendly=self.friendly)
            sit['air'] = False
        else:
            ex = choreo.plan_exchange(self.rng, self.pick[att], self.pick[dfn], sit)
        if air:
            self.n_air += 1
        em, tot = self.em, self.tot
        t = max(t, em.free[att], em.free[dfn])
        ko = None
        if air and 'jump' in D.anim:                          # air-to-air: the defender is up there too
            em.play(dfn, t, 'jump', {}, tot(dfn, 'jump'))
        beats = ex['beats']
        for bi, b in enumerate(beats):
            who = att if b['who'] == 'att' else dfn
            tgt = self.other(who)
            if b['kind'] == 'move':
                t = max(t, em.free[who])
                dur = tot(who, b['anim'])
                nb = beats[bi + 1] if bi + 1 < len(beats) else None
                near = None
                if b['dx'] > 0 and nb is not None and nb.get('who') == b['who'] and nb.get('kind') in ('strike', 'counter'):
                    # V7.1: a dash / jump-in lands where the strike that follows it reaches (an air exchange never steps in
                    # again, so a jump-in that landed at the bout gap kicked at nothing)
                    near = min(self.apart, max(MIN_APART, choreo.reach_of(self.A[who], nb['anim']) + BODY_FRONT))
                    x = self.pos[tgt] - self.face(who) * near
                elif b['dx'] > 0:
                    x = self.pos[tgt] - self.face(who) * self.gap
                elif b['dx'] == 0:                             # a juggle jump: straight up after the launched defender
                    x = self.pos[who]
                else:
                    x = self.pos[who] - self.face(who) * (FAR_EXTRA if b['anim'] == 'backdash' else FAR_EXTRA * 0.75)
                x = self.clamp(who, x, near=near)
                em.play(who, t, b['anim'], self.travel(who, b['anim'], t, x, dur), dur)
                self.pos[who] = x
                if b['anim'] in ('dash', 'backdash') and self.fx is not None:
                    em.directive(who, t, '@fx', {'fx': 'dust', 'anchor': 'ground'})
                if b['anim'] == 'jump':                        # a jump-in strike leaves the apex and lands on the way down
                    t = t + self.apex_s(who, 'jump', dur * 0.45) + 0.03
                else:
                    t = t + dur + 0.03
                self.beats[who].append(b)
                continue
            if b['kind'] == 'emote':
                t = max(t, em.free[who]) + 0.1
                em.play(who, t, b['anim'], {}, tot(who, b['anim']))
                self.beats[who].append(b)
                continue
            # ---- an attack beat (strike / special / super / ultimate / counter)
            kind, move = b['kind'], b['anim']
            t = max(t, em.free[who])
            if b.get('pause'):                                 # V7 set piece: a stand-off before this beat
                t = max(t, em.free[tgt]) + float(b['pause'])
            if self.down_until.get(tgt, 0.0) > t:
                t = self.down_until[tgt]                       # never hit a fighter who is still on the floor / getting up
            if kind == 'special' and not choreo.has_projectile(self.A[who], move):
                continue
            # finish KOs with a signature move: a plain strike that would empty the bar becomes the signature strike
            sig_strike = self.A[who].signature()['strike']
            if (b['outcome'] == 'hit' and not self.friendly and kind in ('strike', 'counter') and self.hp[tgt] - b['dmg'] <= 0
                    and sig_strike and move != sig_strike and not any(b.get(f) for f in V7_SPECIAL)
                    and self.pick[who].used[sig_strike] < choreo.MAX_PER_ROUND):
                move = sig_strike
                b = dict(b, anim=move, dmg=max(b['dmg'], choreo.damage_of(self.A[who], move, 'strike')),
                         hitstop=choreo.hitstop_ms(self.A[who], move, 'strike'), finisher=True)
                self.pick[who].note(move)
            lunge = bool(b.get('lunge')) and kind == 'strike' and not air
            if (not lunge and self.dist() > self.gap + CLOSE_EXTRA and kind in ('strike', 'counter', 'super')
                    and 'dash' in self.A[who].anim and not air and not any(b.get(f) for f in ('juggle', 'through', 'pull'))):
                dur = tot(who, 'dash')                         # never swing at the air: close in first
                x = self.clamp(who, self.pos[tgt] - self.face(who) * self.gap)
                em.play(who, t, 'dash', {'to': x, 'slide_ms': int(dur * 1000)}, dur)
                self.pos[who] = x
                t += dur + 0.03
            cont = _contact_s(self.A[who], move)
            tc = t + cont
            step = None                                        # V6: stand at the move's own reach (no overlap, no air swings)
            Aw = self.A[who]
            behind = self.pos[tgt] + self.face(who) * self.apart
            through = bool(b.get('through')) and abs(self.clamp(who, behind, order=False) - behind) < 0.5
            if through:                                        # V7 dash-through: slide THROUGH the defender during the burst
                sm = (Aw.anim[move].get('smear_frames') or [0])[0]
                t_sl = t + Aw.start_ms(move, sm) / 1000.0
                step = {'to': behind, 'slide_ms': int(max(60.0, (tc - t_sl) * 1000)), 'slide_at': round(t_sl, 4), 'through': True}
                self.pos[who] = behind
            elif kind in ('strike', 'counter') and not air and not b.get('pull'):
                # V7.1: a strike lands from inside its own measured reach (+ the defender's body front), even when that is
                # closer than the two idle silhouettes (weapons held out) would stand; never closer than MIN_APART (bodies)
                want = max(MIN_APART, choreo.reach_of(Aw, move) + BODY_FRONT)
                near = min(self.apart, want)
                if b.get('throw'):
                    want = near = self.apart + 2               # a throw needs the opponent within arm's reach
                elif b.get('outcome') == 'clash':
                    want = near = self.apart + CLASH_GAP       # a weapon lock: blades meet between two bodies that do not touch
                if lunge or abs(self.dist() - want) > 3:
                    x = self.clamp(who, self.pos[tgt] - self.face(who) * want, near=near)
                    if abs(x - self.pos[who]) > 1:
                        # (V7.1 fix: this was int(max(60, seconds) * 1000) - a 60 000 ms slide, so step-ins barely moved)
                        step = {'to': x, 'slide_ms': int(max(60.0, cont * (LUNGE_FRAC if lunge else 0.6) * 1000))}
                        self.pos[who] = x
            proj = None
            if kind == 'special':
                a = self.A[who].anim[move]
                spawn = t + self.A[who].start_ms(move, a['proj_frame']) / 1000.0
                speed = float(self.A[who].meta['projectile']['speed'])
                arrive = spawn + max(0.0, self.dist() - 12) / speed
                back = None
                if b.get('boomerang') and 'catch_frame' in a:  # V7: out to the defender and back to the thrower's catch frame
                    back = t + self.A[who].start_ms(move, a['catch_frame']) / 1000.0
                    arrive = spawn + (back - spawn) / 2.0
                    speed = max(30.0, max(0.0, self.dist() - 12) / max(0.05, arrive - spawn))
                tc = max(tc, arrive)
                proj = dict(owner=who, spawn=spawn, arrive=arrive, dir=self.face(who), x0=self.pos[who], speed=speed, move=move)
                if back is not None:
                    proj.update(ret=True, back=round(back, 4))
            elif kind == 'ultimate' and self.fx is not None:
                name = self.main_fx(who, move)
                if name:
                    e = self.fx.get(name)
                    k_px = self.A[who].res / float(e.res)
                    spawn = max(t, t + [off for off, n, u in self.A[who].move_fx(move) if n == name][0] - self.fx_lead(name))
                    if e.grow:
                        tc = max(tc, spawn + e.grow['ms'] / 1000.0 * min(1.0, self.dist() / max(1.0, e.grow['to_w'] * k_px)))
                    elif e.travel:
                        tc = max(tc, spawn + max(0.0, self.dist() - 16) / (e.travel['speed'] * k_px))
            dmg = b['dmg']
            outcome = b['outcome']
            arm = b.get('armor')
            if arm and not self.friendly and self.hp[who] > arm['dmg'] and arm['anim'] in self.A[tgt].anim:
                # V7 armour: the defender's poke lands mid wind-up; the attacker takes it without flinching and keeps swinging
                cj = self.A[tgt].contact_ms(arm['anim']) / 1000.0
                tj = t + cont * 0.45 - cj
                if tj >= em.free[tgt] + 0.02:
                    self.hp[who] = max(0, self.hp[who] - arm['dmg'])
                    em.play(tgt, tj, arm['anim'], {'contact': tj + cj, 'kind': 'counter', 'damage': arm['dmg'], 'hitstop': 0,
                                                   'outcome': 'armor'}, tot(tgt, arm['anim']))
                    em.directive(who, tj + cj, '@armor', {'hp': dict(self.hp), 'damage': arm['dmg']})
                    em.directive(who, tj + cj, '@fx', {'fx': 'block_spark'})
            if outcome in ('hit', 'guard_break') and not self.friendly:
                self.hp[tgt] = max(0, self.hp[tgt] - dmg)
                self.meter[who] += dmg
                self.meter[tgt] += dmg / 2.0
            if kind == 'super':
                self.meter[who] = 0.0
            if kind == 'ultimate':
                self.used_ult[who] = True
                self.ult_used = True
            react = b['react']
            if outcome in ('hit', 'guard_break') and not self.friendly and self.hp[tgt] <= 0:
                react, ko = (react if react in ('thrown', 'spiked') else 'knockdown'), tgt     # V7: a juggle / throw KO keeps its fall
            hitstop = b['hitstop']
            last_hit = not any(nb.get('who') == b['who'] and nb.get('kind') not in ('move', 'emote') for nb in beats[bi + 1:])
            fd = self.frame_data(who, tgt, b, move, kind, outcome, dmg, react, ko, last_hit)
            if fd is not None:
                hitstop = fd['hitlag']                          # V9: both fighters freeze for the same hitlag
                react = fd['react']
            slow = None
            final_ko = ko is not None and self.final and self.wins[who] + 1 >= ROUNDS_TO_WIN
            if final_ko:                                       # the finisher: a long freeze, then the fall in slow motion
                hitstop = max(hitstop, KO_HITSTOP_MS)
                ts = tc + hitstop / 1000.0
                slow = [round(ts, 4), round(ts + SLOW_S, 4), SLOW_K]
            elif b.get('slow'):                                # V7 set piece: this contact plays out in slow motion
                ts = tc + hitstop / 1000.0
                slow = [round(ts, 4), round(ts + float(b['slow'][0]), 4), float(b['slow'][1])]
            hs = hitstop / 1000.0
            slow_extra = ((slow[1] - slow[0]) * (1.0 - slow[2])) if slow else 0.0
            opts = {'contact': tc, 'kind': kind, 'damage': dmg, 'hitstop': hitstop, 'outcome': outcome}
            if step:
                opts.update(step)
            if slow:
                opts['slow'] = slow
            em.play(who, t, move, opts, tot(who, move) + hs + slow_extra)
            t_move = t
            if lunge and self.fx is not None:
                em.directive(who, t, '@fx', {'fx': 'dust', 'anchor': 'ground'})
            if kind in ('ultimate', 'super') or (kind == 'special' and self.fx is not None):
                for off, fx_name, until in self.A[who].move_fx(move):
                    if kind == 'special' and fx_name == move:
                        continue                              # the projectile sprite is the special's own effect on the taskbar
                    lead = self.fx_lead(fx_name) if fx_name == move else 0.0
                    em.directive(who, max(t, t + off - lead), '@fx', {'fx': fx_name, 'kind': kind, 'move': move, 'until': (t + until) if until else None})
            if proj is not None:
                self.projs.append(proj)
            # the defender: a long wind-up (super, ultimate, charged special) gets a guard pose, or a worried one on low HP
            charged = kind in ('super', 'ultimate', 'special') and cont >= BRACE_MIN_S
            if charged and b.get('pre') != 'block':
                low = (not self.friendly) and self.hp[tgt] + (dmg if outcome == 'hit' else 0) < WORRIED_HP
                brace = 'crouch_block' if low and 'crouch_block' in self.A[tgt].anim else ('block' if 'block' in self.A[tgt].anim else None)
                tb = max(em.free[tgt], t + 0.12)
                t_brace_end = tc - (0.15 if b.get('pre') == 'backdash' else 0.0)
                if brace and t_brace_end - tb > 0.1:
                    em.play(tgt, tb, brace, {'hold': True, 'brace': True}, t_brace_end - tb, then=None)
            if b.get('pre'):
                if b['pre'] == 'backdash':                     # whiff: gone before the hit frame
                    x = self.clamp(tgt, self.pos[tgt] - self.face(tgt) * FAR_EXTRA)
                    dur = tot(tgt, 'backdash')
                    em.play(tgt, max(em.free[tgt], tc - 0.15), 'backdash', {'to': x, 'slide_ms': int(dur * 1000)}, dur)
                    self.pos[tgt] = x
                else:
                    tp = min(max(em.free[tgt], tc - 0.25), tc) if not charged else min(max(em.free[tgt], t + 0.12), tc)
                    em.play(tgt, tp, b['pre'], {'hold': True}, max(0.0, tc - tp), then=None)
            sh = choreo.move_shake(self.A[who], move)
            if react is None:
                em.directive(tgt, tc, '@whiff', {'react_to': move})
            else:
                At = self.A[tgt]
                ropts = {'react_to': move, 'damage': dmg, 'hitstop': hitstop, 'outcome': outcome}
                if slow:
                    ropts['slow'] = slow
                if not self.friendly:
                    ropts['hp'] = dict(self.hp)
                    ropts['pct'] = {s: round(v, 1) for s, v in self.pct.items()}     # V9: the damage % on the plates
                knock = b['knock']
                if fd is not None and react not in AIRBORNE and react not in ('pulled', 'thrown', 'spiked'):
                    knock = fd['knock']                        # V9: knockback from the damage, the percentage and the weight
                if react in LYING and ko:
                    knock = max(knock, choreo.KNOCK_PX['knockdown'])
                t_r = tc                                       # when the reaction row starts
                if react == 'thrown' and 'grab_frame' in At.anim.get('thrown', {}) and 'grab_frame' in Aw.anim[move]:
                    # V7 throw: the defender's row starts so its grab frame meets the attacker's grab frame; the slam frames
                    # share one clock (art THROW_MS), so the flat landing falls on the attacker's hit frame
                    t_grab = t + Aw.start_ms(move, Aw.anim[move]['grab_frame']) / 1000.0
                    t_r = t_grab - At.start_ms('thrown', At.anim['thrown']['grab_frame']) / 1000.0
                    ropts.update(stop_at=round(tc, 4), sync='grab')
                    lift = t_r + At.start_ms('thrown', 1) / 1000.0
                    flip = t_r + At.start_ms('thrown', 3) / 1000.0
                    x_in = self.clamp(tgt, self.pos[who] + self.face(who) * self.apart)       # hoisted in close...
                    x = self.clamp(tgt, x_in + self.face(who) * knock)                          # ...slammed down in front
                    ropts.update(to=x_in, slide_ms=int(max(60.0, (flip - lift) * 1000)), slide_at=round(lift, 4),
                                 path=[[round(flip, 4), int(max(60.0, (tc - flip) * 1000) + 120), round(x, 2)]])
                    self.pos[tgt] = x
                elif react == 'pulled':                        # V7 chain pull: yanked in to arm's length on the pull frame
                    pf = Aw.anim[move].get('pull_frame', Aw.anim[move].get('hit_frame', 0))
                    t_pull = t + Aw.start_ms(move, pf) / 1000.0
                    x = self.clamp(tgt, self.pos[who] + self.face(who) * (self.apart + 6))
                    ropts.update(to=x, slide_ms=260, slide_at=round(max(tc, t_pull), 4))
                    self.pos[tgt] = x
                elif knock:
                    x = self.clamp(tgt, self.pos[tgt] + self.face(who) * knock)
                    big = react in ('hit_heavy', 'guard_crush') or react in LYING
                    ropts.update(to=x, slide_ms=KNOCK_SLIDE_MS_BIG if big else KNOCK_SLIDE_MS)    # clock time: waits out hitstop, slows in slow-mo
                    self.pos[tgt] = x
                arc = fd.get('arc') if fd is not None and not ko and not slow else None
                if arc is not None:
                    # V9 tumble: the knockdown row's airborne frames are stretched over the launch's real airtime (a slow
                    # window on this row only) while the sprite rides the arc; it lands on the row's flat frame, bounces once
                    a0, a1 = TUMBLE_AIR_MS
                    air_s = max((a1 - a0) / 1000.0, arc['airtime'] / 1000.0)
                    k_air = (a1 - a0) / 1000.0 / air_s
                    t_air = tc + hs + a0 / 1000.0
                    ropts['slow'] = [round(t_air, 4), round(t_air + air_s, 4), round(k_air, 4)]
                    span = a1 - a0
                    ks = arc['keys']
                    land = float(ks[2][0]) or 1.0
                    ropts['air'] = [[a0, 0], [int(a0 + span * float(ks[1][0]) / land), ks[1][1], 'o'], [a1, 0, 'i']]
                    if len(ks) > 3:
                        ropts['air'] += [[a1 + 30, ks[3][1], 'o'], [a1 + 60, 0, 'i']]
                    if 'to' in ropts:
                        ropts['slide_ms'] = int(span + 60)                # row clock: the flight, then a short skid
                    slow_extra = (air_s - (a1 - a0) / 1000.0)
                fr0 = (At.anim.get(react) or {}).get('frames') or []
                if hitstop > LONG_FREEZE_MS and 'stop_at' not in ropts and fr0:
                    # a long freeze holds the hit POSE, not the one-frame white flash: the flash plays, then the clock stops
                    ropts['stop_at'] = round(t_r + fr0[0]['ms'] / 1000.0, 4)
                    if 'to' in ropts and 'slide_at' not in ropts:
                        ropts['slide_at'] = ropts['stop_at']       # V9: the knockback waits out the freeze, not just its flash
                airborne = react in AIRBORNE and not ko
                if airborne:
                    ropts['hold'] = True                       # hangs in the air on its last frame until the next hit
                rdur = tot(tgt, react) + hs + slow_extra + (tc - t_r)
                if fd is not None and (react in FLINCH or fd.get('block')) and react not in LYING:
                    stun = fd['stun'] + hs + (tc - t_r)        # V9: the defender cannot act until its hitstun / shieldstun ends
                    if stun > rdur:
                        ropts['hold'] = True                   # held on its last frame (no idle in between)
                        rdur = stun
                # a knockdown that is not a KO stays on the floor (no return to idle) until the get-up starts
                then = (('ko' if ko else None) if react in LYING else (None if airborne else 'idle'))
                em.play(tgt, t_r, react, ropts, rdur, then=then)
                if outcome == 'clash':                         # V7 weapon lock: both play the clash row, sparks, both skid apart
                    Lc = At.anim.get('clash') or {}
                    lock = Aw.start_ms('clash', Lc.get('lock_frame', 0)) / 1000.0 if 'clash' in Aw.anim else 0.0
                    push = tc + (Aw.start_ms('clash', 4) / 1000.0 if 'clash' in Aw.anim and len(Aw.anim['clash']['frames']) > 4 else 0.4)
                    xa = self.clamp(who, self.pos[who] - self.face(who) * CLASH_SKID, order=False)
                    em.play(who, tc - lock, 'clash', {'to': xa, 'slide_ms': 200, 'slide_at': round(push, 4), 'contact': tc,
                                                       'hitstop': hitstop, 'outcome': 'clash', 'kind': kind},
                            tot(who, 'clash') + hs)
                    self.pos[who] = xa
                    em.directive(who, tc, '@fx', {'fx': self.contact_fx('clash_sparks', 'block_spark')})
                    for s in (who, tgt):
                        em.directive(s, tc, '@shake', {'frames': 3, 'amp': 1.0})
                    if 'slide_at' not in ropts and 'to' in ropts:
                        ropts['slide_at'] = round(push, 4)
                elif outcome in ('block', 'crouch_block', 'parry'):
                    em.directive(tgt, tc, '@fx', {'fx': self.contact_fx('block_deflect', 'block_spark')})
                elif outcome == 'guard_break':                 # V7: the guard shatters: spark, a short shake, the stagger
                    em.directive(tgt, tc, '@fx', {'fx': 'block_spark'})
                    em.directive(tgt, tc, '@fx', {'fx': 'hit_heavy'})
                    for s in (who, tgt):
                        em.directive(s, tc, '@shake', {'frames': 3, 'amp': 1.0})
                elif outcome == 'hit':
                    heavy = react in ('hit_heavy', 'launched', 'hit_back') or react in LYING
                    base = 'hit_heavy' if heavy else 'hit_light'
                    typed = HIT_FX.get((Aw.anim.get(move) or {}).get('hit'))
                    em.directive(tgt, tc, '@fx', {'fx': self.contact_fx(typed, base) if typed else base})   # V7: slash / blunt / pierce
                    if typed and heavy and self.fx is not None and self.fx.has_art(typed):
                        em.directive(tgt, tc, '@fx', {'fx': base})          # a heavy hit also bursts
                    if sh is None and not self.friendly:                     # V7: every landed hit shakes, scaled by power
                        sh = POWER_SHAKE.get(min(3, int(Aw.power(move, 1)))) if kind in ('strike', 'counter') else None
                        if fd is not None and fd['kb'] >= 40:          # V9: ... and by the knockback (a late hit shakes harder)
                            sh = {'frames': 2 + int(fd['kb'] // 60), 'amp': round(min(2.5, fd['kb'] / 50.0), 2)}
                    if react == 'hit_heavy':
                        em.directive(tgt, tc + 0.05, '@fx', {'fx': 'dust', 'anchor': 'ground'})       # the skid
                    if kind == 'ultimate':
                        name = self.main_fx(who, move)
                        imp = f'{move}_impact' if self.fx is not None and self.fx.has_art(f'{move}_impact') else 'explosion'
                        em.directive(tgt, tc, '@fx', {'fx': imp, 'kind': kind, 'impact': True})
                        for s in (who, tgt):
                            em.directive(s, tc, '@flash', {'alpha': 0.7, 'ms': FLASH_MS})
                    if kind in ('ultimate', 'super') or ko is not None or dmg >= 3 * choreo.DMG_PER_POWER:
                        for s in (who, tgt):                   # impact frames: heavy hits, ultimates and KOs only, never every hit
                            em.directive(s, tc, '@impact', {'ms': IMPACT_MS, 'on': tgt})
                if sh and outcome == 'hit':
                    for s in (who, tgt):
                        em.directive(s, tc, '@shake', dict(sh))
                if react in LYING:
                    t_floor = t_r + (At.start_ms(react, At.anim[react]['hit_frame']) / 1000.0 if 'hit_frame' in At.anim.get(react, {})
                                     else 0.15)
                    em.directive(tgt, tc + 0.15 if react == 'knockdown' else max(tc, t_floor), '@fx', {'fx': 'dust', 'anchor': 'ground'})
                    if ko:
                        t_stars = t_r + rdur
                        em.directive(tgt, t_stars, '@fx', {'fx': 'ko_stars', 'until': t_stars + (1.8 if final_ko else 2.4)})
                        em.directive(tgt, t_stars - 0.05, '@fx', {'fx': 'dust', 'anchor': 'ground'})       # lands
                        self.ko_info = dict(tc=tc, hs=hs, slow=slow, down=t_r + rdur)
                    elif 'getup' in At.anim:
                        lie = MISSED_TECH_S if (arc is not None and not fd.get('tech')) else 0.0   # V9: a tech is up at once
                        em.play(tgt, t_r + rdur + lie, 'getup', {}, tot(tgt, 'getup'))      # springs up the moment the fall ends
                        self.down_until[tgt] = t_r + rdur + lie + tot(tgt, 'getup')
            self.beats[who].append(dict(b, react=react))
            t = tc + hs + 0.12 if kind != 'counter' else em.free[who]
            nb = beats[bi + 1] if bi + 1 < len(beats) else None
            cf = Aw.anim.get(move, {}).get('cancel_frame')
            if b.get('string') and cf is not None and nb is not None and nb.get('string') and outcome == 'hit' and not ko:
                t_cancel = t_move + Aw.start_ms(move, cf) / 1000.0 + hs   # V7 string: the next hit cancels this move's recovery
                em.free[who] = min(em.free[who], t_cancel)
                t = t_cancel
            if ko:
                break
            if b['kind'] == 'counter':
                t = max(em.free[who], em.free[tgt])
        if ko is None and self.face(self.left) < 0 and 'jump' in self.A[att].anim:
            # V7: after a dash-through the attacker stands behind the defender; it vaults back over to its own side so
            # every exchange (and the walk home) starts from the usual order
            o = self.other(att)
            x = self.pos[o] + (-self.apart if att == self.left else self.apart)
            x = self.clamp(att, x, order=False)
            tj = max(em.free[att], em.free[o]) + 0.15
            dur = tot(att, 'jump')
            up, down = air_window(self.A[att].anim.get('jump'))
            if up is not None and down is not None:
                tj = max(tj, max(em.free[att], em.free[o]) + 0.15)
            side = -1 if att == self.left else 1               # where the attacker belongs relative to the defender
            if abs(x - self.pos[o]) < self.apart - 0.5 or (x - self.pos[o]) * side < 0:
                # the bout's edge leaves no room there: the defender gives ground so the two still stand `apart`
                xo = self.clamp(o, x - side * self.apart, order=False)
                x = xo + side * self.apart
                back = 'walk_back' if 'walk_back' in self.A[o].anim else None
                if back and abs(xo - self.pos[o]) > 1:
                    em.play(o, tj - 0.02, back, {'to': xo, 'slide_ms': int(dur * 900)}, dur)
                self.pos[o] = xo
            em.play(att, tj, 'jump', dict(self.travel(att, 'jump', tj, x, dur * 0.9), vault=True), dur)
            self.pos[att] = x
        t_next = max(em.free[att], em.free[dfn]) + (0.25 if ex['range_after'] == 'close' else 0.5)
        self.last_att = att
        self.last_hit = any(b.get('outcome') == 'hit' and b['who'] == 'att' for b in ex['beats'])
        return t_next, ko, ex


def _fx_player_res(atlas):
    return atlas.res


def make_match(plan, atlases, fx=None):
    """-> (timeline {slot: [(t, anim, opts)]}, t_end, summary).  Deterministic in `plan` (+ the atlases / fx on disk).
    summary carries winner, loser, wins, rounds, mode, p_left, projs (projectiles for the brain), beats (per slot).
    V6 story: the trailing fighter's odds tilt up (choreo.edge_for), whoever lost a round gets one comeback exchange
    in the next, a slot in plan['boost'] (its agent just finished a task) opens with its signature super, and the
    match-deciding KO plays a finisher beat (freeze + impact, slow-motion fall, dust, the winner's pose under the name
    banner, the loser slumping up) inside POST_KO_S.  A round that runs out of time shows TIME and the loser slumps."""
    bout = Bout(plan, atlases, fx, friendly=False)
    bout.final = True
    left, right = bout.left, bout.right
    A, rng, em, tot = bout.A, bout.rng, bout.em, bout.tot
    mode = plan.get('mode') if plan.get('mode') in MODES else 'decided'
    pl = p_left(mode, plan.get('scores') or {}, left, right)
    other = bout.other
    tl = em.tl

    def banner(t, kind, over=None, until=None, **kw):
        dur = BANNER_S.get(kind, BANNER_S['round'])
        em.directive(left, t, '@banner', dict({'banner': kind, 'until': until if until is not None else t + dur, 'over': over}, **kw))

    def slump_of(s):
        return next((n for n in SLUMP if n in A[s].anim), None)

    wins = bout.wins
    rounds = []
    t = plan['t0']
    n_round = 0
    ko_loser = None
    comeback_for = None
    story = dict(comebacks=0, boosts=0, pieces=[])
    ult_rolled = False
    n_pieces = 0
    while max(wins.values()) < ROUNDS_TO_WIN:
        n_round += 1
        bout.hp = hp = {left: HP_MAX, right: HP_MAX}
        bout.pct = {left: 0.0, right: 0.0}                         # V9: every round starts at 0 %
        for p in bout.pick.values():
            p.new_round()
        if ko_loser is not None:                                   # the fallen fighter gets up before the next round
            em.play(ko_loser, t - tot(ko_loser, 'getup') - 0.1, 'getup', {}, tot(ko_loser, 'getup'))
        for w in (left, right):
            em.directive(w, t, '@hp', {'hp': dict(hp), 'round': n_round, 'wins': dict(wins), 'pct': dict(bout.pct)})
            em.play(w, t, 'idle', {}, 0.0, then=None)
        banner(t, f'round{min(3, n_round)}')
        banner(t + BANNER_S['round'], 'fight')
        t_round = t + BANNER_S['round'] + BANNER_S['fight'] + 0.1
        t = t_round
        k = 0
        ko_loser = None
        bout.ko_info = None
        air_done = False
        comeback_due = comeback_for
        while True:
            boost = comeback = False
            if bout.boost and k < 2:
                att, boost = bout.boost[0], True                   # its agent just finished a task: the signature super opens
            elif comeback_due is not None and k == 1:
                att, comeback = comeback_due, True                 # lost the last round: one exchange where everything lands
            elif bout.last_att is not None and bout.last_hit and rng.random() < 0.45:
                att = bout.last_att                                # pressure: the winner of the last exchange keeps coming
            else:
                att = left if rng.random() < pl else right
            dfn = other(att)
            air = (not air_done and k >= 1 and rng.random() < 0.3) or (not air_done and k >= 4)
            air = air and not (boost or comeback)
            drama = choreo.dramatic(wins[att], hp[att], hp[dfn], k) and not bout.ult_used and not ult_rolled and not (boost or comeback)
            if drama:                                              # ONE roll per match, the first time anyone qualifies (~0.35 / match)
                ult_rolled = True
                drama = rng.random() < choreo.ULT_CHANCE
            piece = None                                           # V7: 1-3 hand-authored set pieces per match, at dramatic moments
            if n_pieces < setpieces.MAX_PER_MATCH and not (boost or drama or air):
                if comeback and rng.random() < 0.6:
                    piece = setpieces.choose(rng, A[att], A[dfn], 'comeback')
                    if piece and setpieces.PIECES[piece].get('lander', 'att') == 'dfn':
                        att, dfn = dfn, att                        # the comeback fighter must be the one who lands it
                        piece = piece if setpieces.eligible(piece, A[att], A[dfn]) else None
                elif not comeback:
                    match_pt = wins[att] + 1 >= ROUNDS_TO_WIN and hp[dfn] <= 3 * DMG_PER_POWER
                    when = ('finisher' if match_pt and rng.random() < 0.5 else
                            'opener' if k == 1 and rng.random() < setpieces.P_OPENER else
                            'mid' if k >= 3 and rng.random() < setpieces.P_MID else None)
                    piece = setpieces.choose(rng, A[att], A[dfn], when) if when else None
            mark = em.mark()
            saved = (dict(bout.pos), dict(bout.meter), dict(bout.used_ult), dict(hp), list(bout.projs), {s: list(v) for s, v in bout.beats.items()},
                     bout.n_air, bout.ult_used, dict((s, (p.last, dict(p.used), dict(p.counts))) for s, p in bout.pick.items()),
                     dict(bout.pct), bout.fd_rng.getstate(), len(bout.fd_log))
            t_next, ko, ex = bout.exchange(att, t, k, dramatic=drama, air=air, comeback=comeback, boost=boost, ult_sure=drama,
                                           piece=piece)
            if t_next - t_round > ROUND_CAP_S and k > 0:
                em.rollback(mark)                                  # time: the round is called on HP
                bout.pos, bout.meter, bout.used_ult, hp, bout.projs, bout.beats, bout.n_air, bout.ult_used = saved[:8]
                for s, (last, used, counts) in saved[8].items():
                    p = bout.pick[s]
                    p.last, p.used, p.counts = last, choreo.Counter(used), choreo.Counter(counts)
                bout.pct = saved[9]
                bout.fd_rng.setstate(saved[10])
                del bout.fd_log[saved[11]:]
                bout.hp = hp
                break
            if piece:
                n_pieces += 1
                story['pieces'].append(piece)
            if boost:
                bout.boost.pop(0)
                story['boosts'] += 1
            if comeback:
                comeback_due = None
                story['comebacks'] += 1
            if air:
                air_done = True
            t = t_next
            k += 1
            if ko is not None:
                ko_loser = ko
                break
        # ---- round result
        if ko_loser is not None:
            winner = other(ko_loser)
            ki = bout.ko_info
            banner(ki['tc'], 'ko')
            if wins[winner] + 1 >= ROUNDS_TO_WIN:
                t_end_round = ki['tc']                             # the finisher beat below takes over
            else:
                tn = choreo._taunt(rng, A[winner])                  # V7: the character's own taunt half the time
                em.play(winner, max(em.free[winner], ki['down'] + 0.1), tn, {}, tot(winner, tn))
                t_end_round = em.free[winner]
        else:
            if hp[left] == hp[right]:
                winner = left if rng.random() < 0.5 else right
            else:
                winner = left if hp[left] > hp[right] else right
            tw = max(em.free[left], em.free[right])
            banner(tw, 'time')                                     # called on time: say so, and nobody falls over unprovoked
            loser_r = other(winner)
            sl = slump_of(loser_r)
            if sl:
                em.play(loser_r, tw + 0.3, sl, {'hold': True}, tot(loser_r, sl), then=None)
            if wins[winner] + 1 >= ROUNDS_TO_WIN:
                t_end_round = tw + 0.3
            else:
                em.play(winner, tw + 0.3, 'taunt', {}, tot(winner, 'taunt'))
                t_end_round = max(em.free[winner], em.free[loser_r])
        wins[winner] += 1
        rounds.append(dict(n=n_round, winner=winner, hp=dict(hp), ko=ko_loser is not None, t0=t_round, t1=t_end_round, exchanges=k))
        for w in (left, right):
            em.directive(w, t_end_round, '@hp', {'hp': dict(hp), 'round': n_round, 'wins': dict(wins)})
        comeback_for = other(winner)
        t = t_end_round + 1.4
    # ---- match result
    champ = left if wins[left] > wins[right] else right
    loser = other(champ)
    vic = 'victory2' if wins[loser] == 0 and 'victory2' in A[champ].anim else 'victory'
    name = getattr(A[champ], 'display', None) or A[champ].character
    if ko_loser is not None and bout.ko_info:
        ki = bout.ko_info
        tc = ki['tc']
        t_end = tc + POST_KO_S
        tv = max(em.free[champ], tc + ki['hs'] + 0.45)             # the winner turns to its pose while the loser still falls
        em.play(champ, tv, vic, {'hold': True}, tot(champ, vic), then=None)
        tt = tv + tot(champ, vic) + 0.05
        if 'taunt' in A[champ].anim and tt + tot(champ, 'taunt') <= t_end - 0.1:
            em.play(champ, tt, 'taunt', {}, tot(champ, 'taunt'))
        banner(max(tv, tc + 1.0), 'winner', over=champ, until=t_end, name=name)
        if 'getup' in A[loser].anim:                              # stays down, then slumps up (a slowed, heavy get-up)
            gu = tot(loser, 'getup') / GETUP_SLOW_K
            tg = max(ki['down'] + 0.6, t_end - 0.1 - gu)
            em.play(loser, tg, 'getup', {'slow': [round(tg, 4), round(tg + gu, 4), GETUP_SLOW_K]}, gu)
            t_end = min(tc + POST_KO_MAX_S, max(t_end, tg + gu + 0.1))
    else:
        t_fin = max(em.free[left], em.free[right], t - 1.4)
        banner(t_fin, 'winner', over=champ, name=name)
        em.play(champ, t_fin, vic, {'hold': True}, tot(champ, vic), then=None)
        t_end = t_fin + max(2.4, tot(champ, vic) + 0.5)
    em.finish()
    em.directive(left, t_end - 0.2, '@record', {'winner': champ, 'loser': loser, 'score': dict(wins), 'chars': {s: A[s].character for s in (left, right)}})
    for w in tl:
        tl[w].sort(key=lambda s: s[0])
    summary = dict(winner=champ, loser=loser, wins=dict(wins), rounds=rounds, mode=mode, p_left=pl, projs=bout.projs, beats=bout.beats, air=bout.n_air,
                   story=story, final_ko=bout.ko_info if ko_loser is not None else None)
    return tl, t_end, summary


def make_friendly(plan, atlases, fx=None, exchanges=4):
    """Spar / clash exchanges (no HP, no finishers) through the same choreography: -> (timeline, t_end, summary).
    The caller (brain.make_timeline) wraps them in bows and the closing fist bump."""
    bout = Bout(plan, atlases, fx, friendly=True)
    left, right = bout.left, bout.right
    rng, em = bout.rng, bout.em
    t = plan['t0']
    for p in bout.pick.values():
        p.new_round()
    for k in range(exchanges):
        boost = bool(bout.boost)
        if boost:
            att = bout.boost.pop(0)                                # its agent just finished a task: the signature super opens
        elif bout.last_att is not None and bout.last_hit and rng.random() < 0.4:
            att = bout.last_att
        else:
            att = (left, right)[k % 2] if k < 2 else (left if rng.random() < 0.5 else right)
        air = k == exchanges - 1 and rng.random() < 0.35 and not boost
        t, ko, ex = bout.exchange(att, t, k, dramatic=False, air=air, boost=boost)
    em.finish()
    t_end = max(em.free.values()) + 0.2
    for w in em.tl:
        em.tl[w].sort(key=lambda s: s[0])
    return em.tl, t_end, dict(projs=bout.projs, beats=bout.beats, air=bout.n_air, pos=dict(bout.pos))


def _fx_hit_s(effect):
    if effect is None or effect.hit_frame is None:
        return 0.0
    return sum(ms for _, ms in effect.frames[:effect.hit_frame]) / 1000.0


def hp_trace(tl):
    """[(t, {slot: hp})] from a timeline (tests, previews): every HP value in time order."""
    out = []
    for w, steps in tl.items():
        for t, name, opts in steps:
            if 'hp' in opts and isinstance(opts['hp'], dict):
                out.append((t, dict(opts['hp'])))
    out.sort(key=lambda s: s[0])
    return out


# ---------------------------------------------------------------- record.json
def record_path() -> Path:
    return cfgmod.data_dir() / 'record.json'


def read_record(path=None) -> dict:
    p = Path(path) if path else record_path()
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record_for(rec, character) -> tuple:
    """-> (wins, losses) of a character in a record dict."""
    v = (rec or {}).get('characters', {}).get(character) or {}
    try:
        return int(v.get('w', 0)), int(v.get('l', 0))
    except (TypeError, ValueError):
        return 0, 0


def record_result(winner_char, loser_char, path=None, now=None, where='taskbar') -> bool:
    """W/L per character, written atomically (temp file + replace).  Returns False instead of raising on disk trouble."""
    p = Path(path) if path else record_path()
    rec = read_record(p)
    if not isinstance(rec.get('characters'), dict):
        rec['characters'] = {}
    chars = rec['characters']
    for c, key in ((winner_char, 'w'), (loser_char, 'l')):
        e = chars.setdefault(str(c), {'w': 0, 'l': 0})
        e[key] = int(e.get(key, 0)) + 1
    rec['matches'] = int(rec.get('matches', 0) or 0) + 1
    rec['last'] = dict(winner=str(winner_char), loser=str(loser_char), ts=time.time() if now is None else now, where=where)
    return write_json_atomic(p, rec)
