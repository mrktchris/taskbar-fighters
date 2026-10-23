"""The planner: one Brain per fighter slot.  Pure logic with an injected clock, so it is testable and the preview
simulator can run two brains against each other without any window.

Slots, not names: slot `a` lives in the left half of the zone, slot `b` in the right half.  Which character a slot shows
(claude, codex, gemini, ...) is decided by the director; the brain only knows its Atlas and reads its signature moves
(`strike`, `special`, `super`) from the atlas metadata.

Coordination between the two *separate* processes is only a tiny event slot in each one's bus file:
  invite {seq, run, mt, kind, plan}  ->  the other replies  accept {seq, run, mt, for, bout}   (or ignores it)
  cancel {bout}                          either side aborts a bout (drag, own limit, pause, partner gone)
Both sides derive the SAME timeline from the plan (positions, start time t0, seeded choices, both characters), so a
punch's contact frame and the other fighter's hit reaction line up without any shared process.

Times passed in are monotonic seconds (system-wide on Windows, so both processes agree); wall-clock time is only used
for bus staleness, outside this module.
"""
from __future__ import annotations
import math, random
from collections import deque

from . import choreo, config as cfgmod, learning, rounds
from .choreo import air_lift, air_window  # noqa: F401  (V7.1: the `air` curve; re-exported for art/qa tools)
from .effects import EffectPlayer

LEFT, RIGHT = 'a', 'b'
SLOTS = (LEFT, RIGHT)
AWAKE = ('working', 'idle', 'done', 'waiting')      # states that can take part in a bout (not sleeping, not limit)
STRIKES = ('jab', 'cross', 'uppercut', 'low_kick', 'roundhouse')
NEEDS = {
    'spar': ('bow', 'block', 'block_hit', 'hit', 'hit_heavy', 'fistbump', 'highfive'),
    'clash': ('block', 'block_hit', 'hit', 'hit_heavy', 'fistbump'),
    'ranged': ('block', 'block_hit', 'taunt'),
    'handoff': ('handoff_give', 'handoff_take', 'review', 'thumbs_up', 'fistbump', 'wait'),
    'console': ('console', 'wave'),
    'match': rounds.NEEDS,
}
BOUT_KINDS = ('spar', 'clash', 'ranged', 'match')
MIN_HOLD_MS = 50          # V6: a smear / hit frame shorter than this can fall between two taskbar redraws (30 fps = 33 ms)
BOOST_WINDOW_S = 20.0     # V6: an agent that finished a task lands its signature super if a bout starts within this
ARENA_BOOST_S = 20.0      # V9: ... and the bus carries a marker this long, so a running arena opens with that super too
IMPACT_PHASES = 4         # V9: impact frames on the struck sprite (render.impact_frame phases)
PULSE_S, PULSE_ON_S, PULSE_ALPHA = 1.0, 0.15, 0.35     # V6: near the context limit / low HP: a short white pulse every second
LOW_HP = 25


GRAVITY = 640.0           # RES 1 px/s^2: a body cut off mid-jump (a jump-in strike) keeps falling at this rate
TURN_FROM = ('idle', 'walk', 'walk_back', 'rage')        # a facing change from one of these plays the short `turn` pivot


def clock_between(stop, slow, since, now):
    """Animation seconds between `since` and `now` given a hitstop window `stop` (t0, t1) that stands still and a slow
    motion window `slow` (t0, t1, k).  The Brain and the Track share it, so a replayed row runs on the same clock."""
    el = now - since
    if stop is not None:
        el -= max(0.0, min(now, stop[1]) - max(stop[0], since))
    if slow is not None:
        s0, s1 = max(slow[0], since), min(now, slow[1])
        part = max(0.0, s1 - s0)
        if stop is not None and part > 0:                  # V9: a slow window overlapping the freeze: the frozen part is
            part -= max(0.0, min(s1, stop[1]) - max(s0, stop[0]))   # already stood still; it must not be taken away twice
        el -= max(0.0, part) * (1.0 - slow[2])            # (the clock ran BACKWARDS there: a fall jumped to its flash frame)
    return max(0.0, el)


def lift_of(atlas, anim, t_anim, carry, clock, now, air=None):
    """Height of a fighter (RES 1 px) playing `anim` since `t_anim`: the row's `air` curve, else what is left of a fall
    that started when an airborne row was cut off (`carry` = (t, h)), else 0.  V9: `air` (a timeline entry's own curve,
    a tumble's launch arc) replaces the row's."""
    a = atlas.anim.get(anim) if atlas is not None else None
    if air:
        return air_lift({'air': air}, clock(t_anim, now) * 1000.0)
    if a and a.get('air'):
        return air_lift(a, clock(t_anim, now) * 1000.0)
    if carry:
        el = clock(carry[0], now)
        return max(0.0, carry[1] - 0.5 * GRAVITY * el * el)
    return 0.0


class Track:
    """One slot's row of a shared bout timeline, replayed: where that fighter stands (x), what it plays and since when,
    its hitstop / slow-motion windows, and how high it is (the `air` lift).

    Why (V7.1 lock-on): both processes derive the same timeline, so a Brain can replay its OPPONENT's row as exactly as
    the opponent plays it and know where it stands at every redraw.  Before, facing followed the partner's bus copy,
    which is read every 0.2 s and written at most every 0.25 s: after every crossover (dash-through, the vault back,
    a throw) a fighter kept facing the old side for up to half a second and its next attack - a bow shot, say - went off
    into empty space.  The Brain plays its own row through a Track too, so both copies move by the same rule: every
    entry is applied at its own time (a slide starts from where the previous one had got to at that instant, whatever
    the redraw times were), and the zone clamp is the same."""

    def __init__(self, tl, x0, zone, atlas):
        self.tl, self.i = list(tl or ()), -1
        self.zone, self.atlas = zone, atlas
        self.x = self._clamp(float(x0))
        self.stop = self.slow = self.slide = None
        self.legs = []
        self.anim, self.t_anim, self.opts, self.carry = 'idle', None, {}, None

    def _clamp(self, x):
        z0, z1 = self.zone
        return max(z0, min(z1, x))

    def clock(self, since, now):
        return clock_between(self.stop, self.slow, since, now)

    def lift(self, now):
        if self.t_anim is None:
            return 0.0
        return lift_of(self.atlas, self.anim, self.t_anim, self.carry, self.clock, now, (self.opts or {}).get('air'))

    def frame(self, now):
        """-> (frame index, done) of the row being played (no MIN_HOLD_MS adjustment: used for whitelists, not drawing)."""
        if self.t_anim is None or self.anim not in self.atlas.anim:
            return 0, True
        return self.atlas.locate(self.anim, self.clock(self.t_anim, now) * 1000.0, self.atlas.anim[self.anim]['loop'])

    def settle(self, t):
        """Evaluate the running slide (and its further `path` legs) at time t.  Pure in t: settling twice gives the same x."""
        while self.slide is not None:
            t0, dur, x0, x1, ease = self.slide
            el = self.clock(t0, t) if t > t0 else 0.0
            if el >= dur:
                self.x = x1
                if self.legs:                                     # V7 `path`: the next leg [t_start, ms, x] (a throw: in, then out)
                    t1, ms1, xn = self.legs.pop(0)
                    self.slide = (max(t1, t0 + dur), max(0.05, ms1 / 1000.0), self.x, self._clamp(xn), 'out')
                    continue
                self.slide = None
            elif el > 0:
                k = el / dur
                self.x = x0 + (x1 - x0) * (k if ease == 'lin' else 1 - (1 - k) ** 2)    # 'lin': a jump's flight; else ease-out
            break

    def start(self, t_abs, name, opts):
        """A move entry becomes due: its row, hitstop, slow motion and slide (rounds.py documents the options)."""
        h = self.lift(t_abs)
        a = self.atlas.anim.get(name)
        if a is None:
            name, a = 'idle', self.atlas.anim.get('idle')
        self.carry = (t_abs, h) if h > 0.5 and not (a and a.get('air')) and not opts.get('air') else None
        self.anim, self.t_anim, self.opts = name, t_abs, opts
        hs = opts.get('hitstop')
        if hs:
            t_stop = float(opts.get('stop_at', opts.get('contact', t_abs)))     # V7: a throw's freeze waits for the slam
            self.stop = (t_stop, t_stop + float(hs) / 1000.0)
        sl = opts.get('slow')
        if isinstance(sl, (list, tuple)) and len(sl) == 3:
            self.slow = (float(sl[0]), float(sl[1]), max(0.05, float(sl[2])))
        if 'to' in opts:                                          # slide while the move plays (dash-in, backdash, knockback)
            x1 = self._clamp(float(opts['to']))
            ms = float(opts.get('slide_ms') or (self.atlas.total_ms(name) if name in self.atlas.anim else 300))
            t_sl = float(opts.get('slide_at', t_abs))             # V7: the slide may start later than the move
            self.slide = (t_sl, max(0.05, ms / 1000.0), self.x, x1, opts.get('ease') or 'out')
            self.legs = [tuple(float(v) for v in leg) for leg in (opts.get('path') or ()) if len(leg) == 3]

    def advance(self, now, entry=None):
        """Apply every entry due by `now`, each at its own time, then settle at `now`.  `entry(t, name, opts)` is called
        for every entry (directives too) after the Track has applied it, with self.x at that instant."""
        tl = self.tl
        while self.i + 1 < len(tl) and tl[self.i + 1][0] <= now:
            self.i += 1
            t_abs, name, opts = tl[self.i]
            self.settle(t_abs)
            if not name.startswith('@'):
                self.start(t_abs, name, opts)
            if entry is not None:
                entry(t_abs, name, opts)
        self.settle(now)

    def passing(self, now):
        """True during this row's dash-through pass (until its cut lands): the fighter it passes keeps its facing, because
        it is struck from behind first (and then plays `hit_back`)."""
        if self.t_anim is None:
            return False
        a = self.atlas.anim.get(self.anim) or {}
        return a.get('type') == 'through' and back_turned(self.atlas, self.anim, self.frame(now)[0])

    def back_turned(self, now):
        """True while this row keeps its back to the opponent on purpose: a dash-through (`type` through) from the start of
        its pass until its cut has landed (hit_frame, its freeze included), and `hit_back` (struck from behind)."""
        return back_turned(self.atlas, self.anim, self.frame(now)[0]) if self.t_anim is not None else False


def back_turned(atlas, anim, idx):
    a = atlas.anim.get(anim) or {}
    if a.get('type') == 'through':
        return idx <= int(a.get('hit_frame', len(a.get('frames', ())) - 1))
    return anim == 'hit_back'


def proj_x(p, now):
    """Where a timeline projectile is at `now`.  V7: a returning one (`ret`, `back`) flies out to its arrival point and
    back to the thrower's hand, arriving on the catch frame."""
    if p.get('ret') and now > p['arrive']:
        far = p['x0'] + p['dir'] * p['speed'] * (p['arrive'] - p['spawn'])
        k = min(1.0, (now - p['arrive']) / max(0.05, p['back'] - p['arrive']))
        return far + (p['x0'] - far) * k
    return p['x0'] + p['dir'] * p['speed'] * (now - p['spawn'])


def other(slot):
    return RIGHT if slot == LEFT else LEFT


def strike_pool(atlas):
    return choreo.strike_pool(atlas)


def kind_possible(kind, atlases_by_slot, plan=None):
    """Every move the timeline will play exists for the fighter that plays it."""
    for slot, a in atlases_by_slot.items():
        if any(n not in a.anim for n in NEEDS[kind] if kind != 'console'):
            return False
        if kind in ('spar', 'clash', 'match') and len(strike_pool(a)) < 1:
            return False
        if kind == 'ranged':
            sp = a.signature()['special']
            if not sp or 'proj_frame' not in a.anim[sp] or a.proj is None:
                return False
    if kind == 'console' and plan is not None:
        v = atlases_by_slot[plan['visitor']]
        return all(n in v.anim for n in NEEDS['console'])
    if kind == 'handoff' and plan is not None:
        g, t = atlases_by_slot[plan['giver']], atlases_by_slot[plan['taker']]
        return 'release_frame' in g.anim['handoff_give'] and 'grab_frame' in t.anim['handoff_take']
    return True


# ---------------------------------------------------------------- timelines (pure, deterministic)
def make_timeline(kind, plan, atlases, fx=None):
    """-> ({slot: [(t_abs, anim, opts)]}, t_end, projectiles[list of dict]).  Same inputs -> same output on both sides.
    `atlases` maps character -> Atlas; plan['chars'] maps slot -> character (absent: the slot ids are the characters).
    Entries whose anim starts with '@' are directives (rounds.py): @hp, @fx, @banner, @record, @shake, @flash, @whiff.
    V5: spar / clash exchanges and the whole match come from choreo.py through rounds.py (seeded no-repeat picks, openers,
    defender answers, combos, resets, specials at range); this function only adds the bows and the closing fist bump."""
    if kind == 'match':
        tl, t_end, summary = rounds.make_match(plan, atlases, fx)
        make_timeline.last_summary = summary
        return tl, t_end, list(summary.get('projs') or [])
    t0 = plan['t0']
    rng = random.Random(plan['seed'])
    chars = plan.get('chars') or {}
    A = lambda s: atlases[chars.get(s, s)]
    left, right = plan['left'], plan['right']
    tl = {left: [], right: []}
    projs = []
    tot = lambda w, n: A(w).total_ms(n) / 1000.0
    cont = lambda w, n: A(w).contact_ms(n) / 1000.0

    if kind in ('spar', 'clash'):
        bows = kind == 'spar'
        t = t0
        if bows:
            for w in (left, right):
                tl[w].append((t0, 'bow', {}))
            t = t0 + max(tot(left, 'bow'), tot(right, 'bow')) + 0.45
        ftl, tf, summary = rounds.make_friendly(dict(plan, t0=t), atlases, fx, exchanges=4 if bows else 2)
        for w in (left, right):
            tl[w].extend(ftl.get(w, []))
        projs.extend(summary.get('projs') or [])
        make_timeline.last_summary = summary
        pos = summary.get('pos') or plan['pos']
        back = {w: plan['pos'][w] for w in (left, right)}     # walk back to the bout spots for the hand shake
        tw = tf
        for w in (left, right):
            d = abs(float(pos[w]) - float(back[w]))
            if d > 2 and 'walk' in A(w).anim:
                dur = d / 60.0
                tl[w].append((tf, 'walk', {'to': back[w], 'slide_ms': int(dur * 1000)}))
                tl[w].append((tf + dur, 'idle', {}))
                tw = max(tw, tf + dur + 0.15)
        tf = tw
        end_move = rng.choice(['fistbump', 'highfive']) if bows else 'fistbump'
        for w in (left, right):
            tl[w].append((tf, end_move, {'contact': tf + cont(w, end_move)}))
            if bows:
                tl[w].append((tf + tot(w, end_move) + 0.1, 'bow', {}))
            else:
                tl[w].append((tf + tot(w, end_move) + 0.1, 'idle', {}))
        t_end = tf + tot(left, end_move) + 0.1 + (max(tot(left, 'bow'), tot(right, 'bow')) if bows else 0.0) + 0.3

    elif kind == 'handoff':
        giver, taker = plan['giver'], plan['taker']
        rel = A(giver).start_ms('handoff_give', A(giver).anim['handoff_give']['release_frame']) / 1000.0
        grab = A(taker).start_ms('handoff_take', A(taker).anim['handoff_take']['grab_frame']) / 1000.0
        ts = t0 + max(0.0, rel - grab)
        tg = t0 + max(0.0, grab - rel)
        tl[giver].append((tg, 'handoff_give', {}))
        tl[giver].append((tg + tot(giver, 'handoff_give'), 'wait', {}))
        tl[taker].append((ts, 'handoff_take', {}))
        t_rev = ts + tot(taker, 'handoff_take')
        tl[taker].append((t_rev, 'review', {}))
        tl[taker].append((t_rev + 6.0, 'thumbs_up', {}))           # the reviewer approves
        t_f = t_rev + 6.0 + tot(taker, 'thumbs_up') + 0.2
        for w in (giver, taker):
            tl[w].append((t_f, 'fistbump', {'contact': t_f + cont(w, 'fistbump')}))
            tl[w].append((t_f + tot(w, 'fistbump') + 0.05, 'idle', {}))
        t_end = t_f + tot(giver, 'fistbump') + 0.4

    elif kind == 'console':
        visitor = plan['visitor']
        t = t0
        for _ in range(2):
            tl[visitor].append((t, 'console', {}))
            t += tot(visitor, 'console')
        tl[visitor].append((t, 'wave', {}))
        t += tot(visitor, 'wave') + 0.3
        t_end = t

    elif kind == 'ranged':
        # V6: the first shot is blocked; the answer either lands (a hit, the shooter taunts) or is parried (the parrier
        # taunts).  V5 always ended block, block, both taunt.
        t = t0 + 0.4
        spec = {w: A(w).signature()['special'] for w in (left, right)}
        ending = rng.choice(['hit', 'parry'])
        winner = None
        for n, att in enumerate((left, right)):
            dfn = right if att == left else left
            mv = spec[att]
            spawn = t + A(att).start_ms(mv, A(att).anim[mv]['proj_frame']) / 1000.0
            speed = A(att).meta['projectile']['speed']
            dist = abs(plan['pos'][dfn] - plan['pos'][att]) - 12
            arrive = spawn + dist / speed
            direction = 1 if att == left else -1
            tl[att].append((t, mv, {}))
            tl[att].append((t + tot(att, mv), 'idle', {}))
            projs.append(dict(owner=att, spawn=spawn, arrive=arrive, dir=direction, x0=plan['pos'][att], speed=speed, move=mv))
            last = n == 1
            if last and ending == 'hit' and 'hit' in A(dfn).anim:
                tl[dfn].append((arrive, 'hit', {'react_to': mv, 'outcome': 'hit'}))
                tl[dfn].append((arrive + tot(dfn, 'hit'), 'idle', {}))
                winner = att
            elif last and ending == 'parry' and 'parry' in A(dfn).anim:
                tp = max(t0, arrive - cont(dfn, 'parry'))         # the swat's own hit frame meets the projectile
                tl[dfn].append((tp, 'parry', {'react_to': mv, 'outcome': 'parry'}))
                tl[dfn].append((tp + tot(dfn, 'parry'), 'idle', {}))
                winner = dfn
            else:
                tl[dfn].append((max(t0, arrive - 0.6), 'block', {}))
                tl[dfn].append((arrive, 'block_hit', {'react_to': mv}))
                tl[dfn].append((arrive + tot(dfn, 'block_hit'), 'idle', {}))
            t = arrive + 0.9
        for w in ((winner,) if winner else (left, right)):
            tl[w].append((t, 'taunt', {}))
        loser = None if winner is None else (right if winner == left else left)
        if loser and 'shrug' in A(loser).anim:
            tl[loser].append((t + 0.1, 'shrug', {}))
        t_end = t + max(tot(w, 'taunt') for w in (left, right)) + 0.3
    else:
        raise ValueError(kind)
    for w in tl:
        tl[w].sort(key=lambda s: s[0])
    return tl, t_end, projs


# ---------------------------------------------------------------- the brain
class Brain:
    def __init__(self, slot, atlas, atlases, cfg, rng, now, zone=None, run=None, fx=None, record=None):
        self.slot = self.who = slot
        self.atlases = learning.wrap_library(atlases)         # learning: every atlas served carries the learned rows
        self.atlas, self.cfg, self.rng = self.atlases.wrap(atlas), cfg, rng
        self.learner = learning.Learner(self)                 # learning hooks: plan, prepare, after_bout, practice, home, banner
        self.character = atlas.character
        self.sig = atlas.signature()
        if fx is None:
            from . import fx as fxmod
            fx = fxmod.default()
        self.fx = fx
        self.fxp = EffectPlayer(fx, res=atlas.res)
        self.record = record or rounds.record_result          # (winner_char, loser_char) -> record.json
        self.winners = 'decided'                              # control.json `winners`, set by the owner each tick
        self.hp = None                                        # HP while a match plays, else None
        self.round = None                                     # {'n', 'wins': {slot: n}} while a match plays
        self.banner = None                                    # {'kind', 'until', 'x'} (the left side draws the texts)
        self.last_match = None                                # summary of the last match this side played
        self.eye = (0, 0)                                     # pupil offset toward the cursor while idle (set by the owner)
        self.impact = None                                    # V9: (t0, seconds) impact frames on this fighter's own sprite
        self.run = run or '%08x' % rng.getrandbits(32)         # a restarted process gets a new run id
        z0, z1 = zone or cfgmod.fight_zone(cfg)              # the roam zone minus the fixed HUD plate strip
        self.zone = (z0, z1)
        self.track = None            # V7.1: this slot's row of the running bout (Track), and the opponent's (the lock-on ghost)
        self.ghost = None
        self.carry = None            # (t, h): an airborne row was cut off at height h at time t (outside a bout: the throw)
        mid = (z0 + z1) / 2.0
        gap = cfg['gap_px']
        self.home = (z0 + 12, mid - gap) if slot == LEFT else (mid + gap, z1 - 12)
        self.x = (self.home[0] + self.home[1]) / 2.0
        self.home_x = self.x
        self.facing = 1 if slot == LEFT else -1
        self.mode = 'home'
        self.anim, self.anim_t0, self.anim_loop = 'idle', now, True
        self.prev_state = None
        self.snap = None
        self.partner = None
        self.seq = 0
        self.seen_key = None
        self.event = None
        self.pending = None
        self.walk_target = self.x
        self.walk_then = None
        self.script = None          # dict(kind, plan, tl, t_end, projs)
        self.script_i = -1
        self.bout = None            # id of the bout being walked to / played / negotiated
        self.paused = False
        self.next_bout = now + rng.uniform(cfg['bout_min_s'], cfg['bout_max_s'])
        self.next_clash = now + rng.uniform(cfg.get('clash_min_s', 20), cfg.get('clash_max_s', 40))
        self.next_flourish = now + rng.uniform(6, 10)
        self.next_wander = now + rng.uniform(10, 20)
        self.work_variant, self.work_switch = 'work', now + 10
        self.next_shrug = now + rng.uniform(10, 16)
        self.next_shadow = now + rng.uniform(cfg.get('shadowbox_min_s', 8), cfg.get('shadowbox_max_s', 14))
        self.next_console = now + rng.uniform(cfg.get('console_min_s', 40), cfg.get('console_max_s', 80))
        self.next_match = now + rng.uniform(cfg.get('match_min_s', 180), cfg.get('match_max_s', 360))
        self.rival = True            # control.json `rival` (set by the owner each tick): a sleeping partner still fights (V5.1)
        self.next_rival = self.next_rival_spar = now
        self._schedule_rival(now)
        self.hold_until = 0.0        # a sleeper plays `wake` before it walks to a bout
        self.demo = None            # {'kind', 'until'}: a bout asked for by the user, sent as soon as both are free
        self.ko_until = 0.0
        self.stop = None             # (t_start, t_end): hitstop freeze of the animation clock (V5)
        self.slow = None             # (t_start, t_end, k): slow motion of the animation clock (V6 finisher)
        self.slide = None            # (t0, dur, x0, x1): the fighter slides while a move plays (dash-in, knockback) (V5;
                                     # V6: on the frozen / slowed clock, so a knockback waits out the hitstop)
        self.hold = False            # V6: the current one-shot keeps its last frame (brace, slump) instead of returning to idle
        self.flashes = None          # V6: control.json `flashes` (the owner may set it; None = read it here, throttled)
        self._flash_cache, self._flash_read = True, -1e9
        self.finish_due = {}         # V6: slot -> deadline (monotonic) or 'after' (finished during a bout): boost super
        self.pct = None              # V9: damage % this round while a match plays (frame data), else None
        self.boost_mark = None       # V9: (id, deadline monotonic) of this slot's last task finish, published on the bus
        self.sfx = None              # V9: an sfx.Player when this process plays the fight's sounds (slot a only), else None
        self.shadow_pick = None      # V6: a no-repeat picker for shadowboxing
        self.stun_until = 0.0        # dizzy after a fast drag / a throw landing
        self.throw_state = None      # a Shift-drag throw in flight
        self.last_now = now
        self.hit_log = deque(maxlen=64)           # (time, kind) for tests and the preview; bounded for a long-running process
        self.contact_log = deque(maxlen=64)
        self.bout_log = deque(maxlen=64)          # (what, bout id, t, move); bout_log_n counts every note ever made
        self.bout_log_n = 0

    @property
    def band(self):
        """V7.1: the band the fight may draw into (RES 1 px): the zone plus a whole sprite each side, i.e. up to the plates
        and the scoreboard (config.fight_zone keeps exactly that clearance).  render.compose clips every frame to it.
        Derived from `zone` on every read: a caller that moves the zone later (the 128 px doc render) must not keep a
        stale band, or the clip slices the fighter instead of trimming effects."""
        z0, z1 = self.zone
        return (z0 - cfgmod.SPRITE_REACH, z1 + cfgmod.SPRITE_REACH)

    def _schedule_rival(self, now):
        c = self.cfg
        self.next_rival = now + self.rng.uniform(float(c.get('rival_min', 8)), float(c.get('rival_max', 15))) * 60.0
        self.next_rival_spar = now + self.rng.uniform(float(c.get('rival_spar_min', 3)), float(c.get('rival_spar_max', 6))) * 60.0

    # -------------------------------------------------------------- animation plumbing
    def play(self, name, now, loop=None, hold=False):
        if name not in self.atlas.anim:
            name, loop = 'idle', None
        if name == self.anim and self.anim_loop and (loop is None or loop):
            return
        h = lift_of(self.atlas, self.anim, self.anim_t0, self.carry, self.clock, now)
        self.carry = (now, h) if h > 0.5 and not self.atlas.anim[name].get('air') else None
        self.anim, self.anim_t0 = name, now
        self.anim_loop = self.atlas.anim[name]['loop'] if loop is None else loop
        self.hold = bool(hold)

    def clock(self, since, now):
        """Seconds of animation time between `since` and `now`: the hitstop window stands still, the slow-motion window
        runs at its k (V6).  Frames and slides both run on this clock, so a knockback slide waits out the freeze."""
        return clock_between(self.stop, self.slow, since, now)

    def lift(self, now):
        """How high this fighter is (RES 1 px above the floor): inside a bout the row of the shared timeline (Track), so
        both processes agree; outside one, its own row (the Shift-drag throw's jump)."""
        if self.mode == 'script' and self.track is not None and self.anim != 'turn':
            return self.track.lift(now)
        return lift_of(self.atlas, self.anim, self.anim_t0, self.carry, self.clock, now)

    def opp_x(self, now):
        """Where the opponent stands: from the replayed timeline while a bout plays (exact, no lag), else the bus copy."""
        if self.mode == 'script' and self.ghost is not None:
            return self.ghost.x
        if self.partner and isinstance(self.partner.get('x'), (int, float)):
            return float(self.partner['x'])
        return None

    def frozen(self, now):
        st, sl = self.stop, self.slow
        return bool((st and st[0] <= now < st[1]) or (sl and sl[0] <= now < sl[1]))

    def held_ms(self, name):
        """Frame durations of a one-shot with every smear / hit frame lasting at least MIN_HOLD_MS, the extra taken from
        the frame before it, so the contact time and the total stay exactly as authored (the timeline relies on them).
        None when nothing needs changing."""
        cache = self.__dict__.setdefault('_held', {})
        key = (id(self.atlas), name)
        if key not in cache:
            a = self.atlas.anim.get(name) or {}
            ms = [f['ms'] for f in a.get('frames', [])]
            keep = set(a.get('smear_frames') or []) | ({a['hit_frame']} if 'hit_frame' in a else set())
            changed = False
            for i in sorted(keep):
                if 0 < i < len(ms) and ms[i] < MIN_HOLD_MS and (i - 1) not in keep:
                    need = MIN_HOLD_MS - ms[i]
                    if ms[i - 1] - need >= 30:
                        ms[i - 1] -= need
                        ms[i] += need
                        changed = True
            cache[key] = ms if changed else None
        return cache[key]

    def frame(self, now):
        el = self.clock(self.anim_t0, now) * 1000.0
        held = None if self.anim_loop else self.held_ms(self.anim)
        if held is None:
            return self.atlas.locate(self.anim, el, self.anim_loop)
        acc = 0.0
        for i, m in enumerate(held):
            acc += m
            if el < acc:
                return i, False
        return len(held) - 1, True

    def _work_anims(self):
        ctx = (self.snap.ctx_pct or 0) if self.snap else 0
        return ['powerup'] if ctx >= 70 else ['work', 'type']        # past 70% context it is visibly charging up

    def base_anim(self):
        s = self.state()
        if s == 'limit':
            return 'dizzy'
        if s == 'working':
            return self.work_variant
        if s == 'waiting':
            return 'wait'
        if s == 'sleeping':
            return 'sleep'
        return 'rage' if (self.snap and (self.snap.ctx_pct or 0) >= 85) else 'idle'

    def state(self):
        return self.snap.state if self.snap else 'idle'

    # -------------------------------------------------------------- public API
    def tick(self, now, snap, partner):
        dt = max(0.0, now - self.last_now)
        self.last_now = now
        self.snap, self.partner = snap, partner
        if self.paused:
            return
        for ev in snap.events:
            self._own_event(ev, now)
        self._partner_events(now)
        if self.bout and self.partner is None:                    # partner vanished mid-bout: abort, do not wait
            self.abort(now, emit=False)
        if self.state() == 'limit' and self.mode == 'walk' and self.walk_then != 'home' and not self._demo_bout():
            self.abort(now)                                       # knocked out on the way to a bout: stop where it stands
            self.mode, self.walk_then = 'home', None              # (walking home is fine; _tick_home sends it there)
        if self.demo:
            self._try_demo(now)
        if self.pending and now > self.pending['deadline']:
            self.pending, self.bout = None, None
            self._goto(self.home_x, now, then='home')
            self.next_bout = now + 20
        if self.mode != 'home':
            self._alert(now, False)
        if self.mode == 'script':
            self._tick_script(now)
        elif self.mode == 'walk':
            self._tick_walk(now, dt)
        else:
            self._tick_home(now, dt)
        idx, done = self.frame(now)
        if done and not self.anim_loop and not (self.hold and self.mode == 'script'):
            self.play(self.base_anim() if self.mode == 'home' else 'idle', now)
        if self.mode in ('script', 'home'):
            self.lock_on(now)                                     # last, so the frame that gets drawn already faces right

    # -------------------------------------------------------------- lock-on (V7.1)
    def turned_away_ok(self, now):
        """The explicit moments a fighter does NOT face its opponent: its own dash-through pass until the cut lands, being
        struck from behind (`hit_back`), standing still while the opponent dashes through it (it is cut from behind
        first), walking home (it faces the way it walks) and the Shift-drag throw."""
        if self.mode == 'walk' and self.walk_then == 'home':
            return True
        if self.throw_state is not None:
            return True
        if back_turned(self.atlas, self.anim, self.frame(now)[0]):
            return True
        return bool(self.mode == 'script' and self.ghost is not None and self.ghost.passing(now))

    def lock_on(self, now):
        """Face the opponent, always (outside turned_away_ok), and turn back the instant such a moment ends.  On the
        ground from a neutral row the turn is the short `turn` pivot; in the air or in the middle of a move it is
        immediate (a cross-up flips on the spot, as in any fighting game).  Inside a bout the opponent's position comes
        from the replayed timeline (opp_x), so a crossover is seen on the frame it happens."""
        ox = self.opp_x(now)
        if ox is None or self.paused:
            return
        d = ox - self.x
        if abs(d) < 0.5:
            return
        want = 1 if d > 0 else -1
        if want == self.facing or self.turned_away_ok(now):
            return
        self.facing = want
        neutral = self.anim in TURN_FROM and (self.mode == 'home' or self.anim == 'idle')
        if neutral and 'turn' in self.atlas.anim and self.lift(now) <= 0.5:
            self.play('turn', now, loop=False)

    def publish(self):
        return dict(state=self.state(), mode=self.mode, x=round(self.x, 1), facing=self.facing, anim=self.anim,
                    ctx=(self.snap.ctx_pct if self.snap else None), event=self.event, character=self.character,
                    run=self.run, paused=self.paused, bout=self.bout, hp=self.hp,
                    round=(self.round or {}).get('n'), wins=(self.round or {}).get('wins'), boost=self.boost_marker(),
                    who=(self.snap.who if self.snap else None))          # the program id (learning keys its memory by it)

    def boost_marker(self, now=None):
        """V9: {'id', 'left'} while this slot's agent finished a task less than ARENA_BOOST_S ago, else None.  `left` is
        seconds, relative to the bus payload's own wall-clock `ts`, so another process (the arena) can tell how long it
        still holds without sharing this process's monotonic clock.  A number and an opaque id: no content."""
        if self.boost_mark is None:
            return None
        now = self.last_now if now is None else now
        left = self.boost_mark[1] - now
        if left <= 0:
            self.boost_mark = None
            return None
        return {'id': self.boost_mark[0], 'left': round(left, 2)}

    def view(self, now):
        dim = self.snap is not None and self.snap.state == 'sleeping' and self.mode == 'home'   # a rival on its way to a bout is lit
        if self.paused:                                           # one static frame: nothing to animate, nothing to redraw
            return dict(anim='idle', frame=0, x=self.x, facing=self.facing, dim=dim, proj=None, fx=[], banner=None, shake=(0, 0), busy=False,
                        lift=0.0, headroom=cfgmod.JUMP_HEADROOM, clip=self.band)
        idx, _ = self.frame(now)
        self.fxp.tick(now)
        if self.banner and now >= self.banner['until']:
            self.banner = None
        banner = None
        if self.banner:
            try:
                if self.banner['kind'] == 'learned':          # learning: 'LEARNED: <MOVE>'
                    im = self.learner.banner_image(self.fx, self.banner)
                else:
                    im = self.fx.banner(self.banner['kind'], name=self.banner.get('name'))
                k = self.atlas.res / float(self.fx.res)
                if k != 1.0:
                    from PIL import Image
                    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.NEAREST)
                banner = (im, self.banner['x'])
            except (ValueError, OSError):
                banner = None
        fxp = self.fxp.placements(now)
        flashes = self.flashes_enabled(now)
        flash = self.fxp.flash(now) if flashes else 0.0
        if flashes and self.pulse(now):                         # near the context limit / low HP: a short white pulse
            flash = max(flash, PULSE_ALPHA)
        shake = self.fxp.shake(now)
        impact = None
        if self.impact is not None and flashes:
            t0, dur = self.impact
            if t0 <= now < t0 + dur:
                impact = min(IMPACT_PHASES - 1, int((now - t0) / dur * IMPACT_PHASES))
            elif now >= t0 + dur:
                self.impact = None
        lift = self.lift(now)                                     # V7.1: the jump / juggle trajectory (RES 1 px)
        v = dict(anim=self.anim, frame=idx, x=self.x, facing=self.facing, dim=dim, proj=None, fx=fxp, banner=banner,
                 shake=shake, busy=bool(fxp or banner or flash or impact is not None or self.slide or shake != (0, 0) or self.frozen(now) or lift > 0.0),
                 flash=flash, impact=impact, eye=(self.eye if self.anim == 'idle' and self.mode == 'home' else (0, 0)),
                 lift=lift, headroom=cfgmod.JUMP_HEADROOM, clip=self.band)
        if self.script and self.script['projs']:
            for p in self.script['projs']:
                end = p.get('back', p['arrive']) if p.get('ret') else p['arrive']
                if p['owner'] == self.slot and p['spawn'] <= now <= end:
                    v['proj'] = dict(x=proj_x(p, now), dir=p['dir'], frame=int((now - p['spawn']) * 8), kind=p['move'],
                                     dy=-self.proj_lift(p, now))
        return v

    def proj_lift(self, p, now):
        """V7.1 aim: a projectile leaves at the shooter's height and homes onto the opponent's height (the replayed
        timeline's lift), so a shot at an airborne opponent climbs to it instead of flying under it.  A returning one
        comes back to the shooter's height.  RES 1 px above the floor."""
        mine = self.lift(now)
        theirs = self.ghost.lift(now) if (self.mode == 'script' and self.ghost is not None) else 0.0
        if p.get('ret') and now > p['arrive']:
            k = min(1.0, (now - p['arrive']) / max(0.05, p['back'] - p['arrive']))
            return theirs + (mine - theirs) * k
        k = min(1.0, max(0.0, (now - p['spawn']) / max(0.05, p['arrive'] - p['spawn'])))
        return mine + (theirs - mine) * k

    def flashes_enabled(self, now):
        """control.json `flashes` (impact frames and white flashes); default on.  Read at most every 2 s."""
        if self.flashes is not None:
            return bool(self.flashes)
        if now - self._flash_read >= 2.0 or now < self._flash_read:
            self._flash_read = now
            try:
                from . import control
                self._flash_cache = bool(control.flashes_on(default=self.cfg.get('flashes', True)))
            except Exception:
                self._flash_cache = True
        return self._flash_cache

    def pulse(self, now):
        """True during the short white pulse of a fighter near its context limit (rage) or low on HP in a match."""
        ctx = (self.snap.ctx_pct or 0) if self.snap else 0
        near = self.state() != 'limit' and ctx >= 85 and not self.paused
        low = self.hp is not None and self.hp <= LOW_HP and self.mode == 'script'
        return (near or low) and (now % PULSE_S) < PULSE_ON_S

    def drag_to(self, x, now):
        """Mouse drag: place the fighter inside its own half (the two never overlap and never cover the plates),
        cancel any bout (telling the partner), give it a breather."""
        self.x = max(self.home[0], min(self.home[1], x))
        self.home_x = self.x
        if self.mode != 'home' or self.bout:
            self.abort(now)
            self.mode, self.walk_then = 'home', None
            self.play('idle', now)
        self.next_bout = max(self.next_bout, now + 10)

    def set_paused(self, paused, now):
        if paused == self.paused:
            return
        if paused:
            self.abort(now)
            self.mode, self.walk_then = 'home', None              # freeze where it stands; home_x is kept, so on
        else:                                                     # resume a fighter caught mid-bout walks back home
            self.prev_state = None                                # re-pick the state animation on resume
            self.anim, self.anim_t0, self.anim_loop = 'idle', now, True
            self.next_bout = now + self.rng.uniform(self.cfg['bout_min_s'], self.cfg['bout_max_s'])
            self.next_clash = now + self.rng.uniform(self.cfg.get('clash_min_s', 20), self.cfg.get('clash_max_s', 40))
            self._schedule_rival(now)
        self.paused = paused

    def set_atlas(self, atlas, now):
        """The director gave this slot a different character: drop any bout and start fresh in the new skin."""
        self.abort(now)
        self.mode, self.walk_then = 'home', None
        atlas = self.atlases.wrap(atlas)                      # learning: the new skin's learned rows come along
        self.atlas, self.character, self.sig = atlas, atlas.character, atlas.signature()
        self.anim, self.anim_t0, self.anim_loop = 'idle', now, True
        self.prev_state = None

    def abort(self, now, emit=True):
        """Leave the current bout (scripted, negotiated or being walked to) and head home."""
        if self.bout is None and self.script is None and self.pending is None:
            return
        if emit and self.bout:
            self._emit('cancel', now, bout=self.bout)
        self.script, self.pending, self.bout = None, None, None
        self._end_match_visuals()
        self._goto(self.home_x, now, then='home')
        self.next_bout = max(self.next_bout, now + 20)

    def _end_match_visuals(self):
        self.hp = self.round = self.banner = None
        self.pct = None                                         # V9: no damage % outside a match
        self.stop = self.slide = self.slow = None
        if self.track is not None:                              # an airborne fighter whose bout ends mid-air keeps falling
            h = self.track.lift(self.last_now)
            self.carry = (self.last_now, h) if h > 0.5 else None
        self.track = self.ghost = None
        self.slide_next = []
        self.hold = False
        for s, d in list(self.finish_due.items()):              # finished during that bout: the boost window opens now
            if d == 'after':
                self.finish_due[s] = self.last_now + BOOST_WINDOW_S
        self.fxp.clear()

    # -------------------------------------------------------------- on-demand bout (minis.py demo / menu)
    def request_demo(self, kind, now, wait_s=12.0):
        """Start a bout as soon as both fighters are home and free, whatever their states.  Only the choreography is
        forced; the snapshot (and so the plate) is untouched."""
        self.demo = dict(kind=kind if kind in BOUT_KINDS else 'spar', until=now + wait_s)

    def _demo_bout(self):
        plan = (self.script or {}).get('plan') or (self.pending or {}).get('plan') or {}
        return bool(plan.get('demo'))

    def _free_any(self):
        return not (self.paused or self.mode != 'home' or self.script or self.pending or self.bout)

    def _try_demo(self, now):
        if now > self.demo['until']:
            self.demo = None
            return
        if self._free_any() and self.partner and self._partner_home():
            kind = self.demo['kind']
            if self._send_invite(kind, now, demo=True) or (kind != 'spar' and self._send_invite('spar', now, demo=True)):
                self.demo = None

    # -------------------------------------------------------------- events
    def _emit(self, typ, now, **kw):
        self.seq += 1
        self.event = dict(seq=self.seq, type=typ, run=self.run, mt=round(now, 3), **kw)

    def note_finish(self, slot, now):
        """The agent behind `slot` finished a task (working -> done): its fighter opens the next bout with its signature
        super if that bout starts within BOOST_WINDOW_S.  A bout already running is a shared, pre-computed timeline, so
        the window then starts when that bout ends."""
        self.finish_due[slot] = 'after' if (self.script is not None or self.bout) else now + BOOST_WINDOW_S

    def boost_slots(self, now):
        return sorted(s for s, d in self.finish_due.items() if isinstance(d, float) and now <= d)

    def _own_event(self, ev, now):
        if ev == 'finished':
            self.note_finish(self.slot, now)
            self._emit('finished', now)
            self.boost_mark = ('%s:%d' % (self.run, self.seq), now + ARENA_BOOST_S)   # V9: the arena reads it off the bus
        elif ev == 'limit':
            cancels = self.bout
            if self.mode != 'home' or self.bout:
                self.abort(now, emit=False)                        # one event slot: the limit event carries the cancel
                self.mode, self.walk_then = 'home', None           # KO'd where it stands
            self._emit('limit', now, cancels=cancels)
            self.ko_until = now + 6.0

    def _partner_home(self):
        p = self.partner
        return bool(p) and p.get('mode') == 'home' and not p.get('paused')

    def free_for(self, kind):
        """Actually free: at home, not in or negotiating a bout, awake, not at its limit, and in a state the bout allows."""
        if self.paused or self.mode != 'home' or self.script or self.pending or self.bout:
            return False
        st = self.state()
        if st in ('sleeping', 'limit'):
            return False
        if kind in ('clash', 'match'):
            return st in ('working', 'waiting', 'idle', 'done')
        if kind in ('handoff', 'console'):
            return st in ('idle', 'done', 'waiting', 'working')
        return st in ('idle', 'done', 'waiting')

    def _partner_events(self, now):
        p = self.partner
        if not p or not isinstance(p.get('event'), dict):
            return
        ev = p['event']
        key = (ev.get('run'), ev.get('seq'))
        if key == self.seen_key:
            return
        self.seen_key = key
        mt = ev.get('mt')
        if not isinstance(mt, (int, float)) or now - mt > self.cfg.get('event_max_age_s', 3.0) or mt - now > 2.0:
            return                                                # replayed after a restart, or simply too old
        t = ev.get('type')
        if t == 'finished':
            self.note_finish(other(self.slot), now)
            if self.free_for('handoff') and self._partner_home():
                self._send_invite('handoff', now, giver=other(self.slot), taker=self.slot)
        elif t == 'limit':
            if self.bout and ev.get('cancels') == self.bout:
                self.abort(now, emit=False)
            elif self.free_for('console') and self._partner_home():
                self._send_invite('console', now, visitor=self.slot)
        elif t == 'invite':
            plan = ev.get('plan') or {}
            kind = plan.get('kind')
            if kind == 'console' or kind not in NEEDS:            # the fighter on the floor just keeps being KO'd
                return
            if self.slot not in (plan.get('left'), plan.get('right')) or now > plan.get('deadline', 0):
                return
            if (plan.get('chars') or {}).get(self.slot, self.character) != self.character:
                return                                            # planned for a skin this slot no longer wears
            rival_ok = plan.get('rival') and self.rival and self.state() == 'sleeping' and self._free_any()
            if self.free_for(kind) or ((plan.get('demo') or rival_ok) and self._free_any()):
                self._accept(ev, now)
        elif t == 'accept':
            if self.pending and ev.get('for') == self.pending['seq'] and ev.get('bout', self.pending['plan']['id']) == self.pending['plan']['id']:
                plan = self.pending['plan']
                self.pending = None
                self._commit(plan['kind'], plan, now)
        elif t == 'cancel':
            if self.bout and ev.get('bout') == self.bout:
                self.abort(now, emit=False)

    # -------------------------------------------------------------- bout negotiation
    def _plan(self, kind, now, **kw):
        me, you = self.slot, other(self.slot)
        pos = {me: self.x, you: float(self.partner['x'])}
        left = LEFT if pos[LEFT] <= pos[RIGHT] else RIGHT
        right = other(left)
        gap = {'spar': self.cfg['gap_px'], 'clash': self.cfg['gap_px'], 'match': self.cfg['gap_px'], 'handoff': 24, 'console': 22, 'ranged': 150}[kind]
        if kind in ('spar', 'clash', 'match'):        # V6: never closer than the two silhouettes allow (weapons included)
            try:
                pc = self.partner.get('character') or self.character
                gap = max(gap, rounds.idle_room(self.atlas, self.atlases[pc]),      # V9: the two idle bodies never overlap
                          rounds.body_front(self.atlas) + rounds.body_front(self.atlases[pc]) - rounds.STAND_OVERLAP)
            except Exception:
                pass
        z0, z1 = self.zone
        mid = (z0 + z1) / 2.0                         # bouts happen in the middle of the fighting zone, never near the plates
        gap = min(gap, max(8.0, z1 - z0 - 2.0))       # (a ranged duel in a narrow zone)
        target = {left: mid - gap / 2.0, right: mid + gap / 2.0}
        if kind == 'console':
            vis = kw['visitor']
            target = {vis: pos[other(vis)] + (-gap if pos[vis] < pos[other(vis)] else gap), other(vis): pos[other(vis)]}
        walk = max(abs(target[w] - pos[w]) for w in SLOTS) / float(self.cfg['walk_px_s'])
        chars = {me: self.character, you: self.partner.get('character') or self.character}
        wake = 0.0
        if self.partner.get('state') == 'sleeping' and kind != 'console':       # a sleeper stretches and yawns before it walks
            wake = self.wake_s(chars[you])
            kw = dict(kw, wake=you)
        plan = dict(kind=kind, left=left, right=right, pos=target, t0=now + walk + 1.0 + wake, seed=self.seq + 1 + int(now) % 997,
                    chars=chars, id=f'{self.run}:{self.seq + 1}', deadline=now + self.cfg.get('invite_window_s', 3.0), **kw)
        if kind in ('spar', 'clash', 'match'):
            # V7.1: the timeline keeps every slide inside THIS zone (the bout's span = half its width, centred on it).  A
            # wider span let the plan put a fighter where the brain then clamped it, so the two processes' fighters were
            # no longer where the shared plan said: hits from the wrong distance, crossovers, facing the wrong way.
            plan['span'] = round(max(8.0, min(rounds.SPAN_PX, (z1 - z0) / 2.0 - abs((target[left] + target[right]) / 2.0 - mid))), 3)
        boost = self.boost_slots(now) if kind in ('match', 'clash', 'spar') else []
        if boost:
            plan['boost'] = boost
        if kind == 'match':                                     # both sides derive HP, attackers and the winner from these
            plan['mode'] = self.winners if self.winners in rounds.MODES else 'decided'
            plan['scores'] = {me: round(rounds.score_of_snapshot(self.snap), 1), you: round(rounds.score_of_bus(self.partner), 1)}
        if kind in ('spar', 'clash', 'match'):
            self.learner.plan(plan)                             # learning: both sides' learned kits travel inside the plan
        return plan

    def _possible(self, kind, plan):
        try:
            by_slot = {s: self.atlases[c] for s, c in plan['chars'].items()}
            return kind_possible(kind, by_slot, plan) and self.learner.possible(plan)   # learning: every learned row loads here
        except Exception:
            return False

    def _send_invite(self, kind, now, **kw):
        if not self.partner:
            return False
        plan = self._plan(kind, now, **kw)
        if not self._possible(kind, plan):
            return False
        self._emit('invite', now, kind=kind, plan=plan)
        self.bout = plan['id']
        if kind == 'console':                    # one-sided: no handshake needed
            self._commit(kind, plan, now)
            return True
        self.pending = dict(seq=self.seq, deadline=plan['deadline'], plan=plan)
        self._goto(plan['pos'][self.slot], now, then='wait')
        return True

    def _accept(self, ev, now):
        plan = ev['plan']
        if not self._possible(plan['kind'], plan):
            return
        self._emit('accept', now, **{'for': ev['seq']}, kind=plan['kind'], bout=plan.get('id'))
        self._commit(plan['kind'], plan, now)

    def _bout_note(self, what, t, name):
        """Content-free bout record (for the slot log and the two-process test): what, bout id, monotonic time, move."""
        self.bout_log.append((what, self.bout, round(t, 3), name))
        self.bout_log_n += 1

    def wake_s(self, character):
        """How long `wake` plays for a character (0 when the atlas has none)."""
        try:
            a = self.atlases[character]
            return a.total_ms('wake') / 1000.0 if 'wake' in a.anim else 0.0
        except Exception:
            return 0.0

    def _commit(self, kind, plan, now):
        for s in plan.get('boost') or ():
            self.finish_due.pop(s, None)                           # consumed by this bout (both sides drop it)
        tl, t_end, projs = make_timeline(kind, plan, self.atlases, self.fx)
        self.script = dict(kind=kind, plan=plan, tl=tl.get(self.slot, []), t_end=t_end, projs=projs,
                           summary=getattr(make_timeline, 'last_summary', None) if kind in learning.BOUT_KINDS else None)
        you = other(self.slot)
        try:                                                       # V7.1: the opponent's row, replayed for the lock-on
            opp_atlas = self.atlases[(plan.get('chars') or {}).get(you) or (self.partner or {}).get('character') or self.character]
        except Exception:
            opp_atlas = self.atlas
        self.track = Track(self.script['tl'], plan['pos'].get(self.slot, self.x), self.zone, self.atlas)
        self.ghost = Track(tl.get(you, []), plan['pos'].get(you, (self.partner or {}).get('x', self.x)), self.zone, opp_atlas)
        if kind == 'match':
            self.last_match = getattr(make_timeline, 'last_summary', None)
        self.script_i = -1
        self.bout = plan.get('id') or self.bout or 'local'
        self._bout_note('bout', plan['t0'], kind + ('-demo' if plan.get('demo') else '-rival' if plan.get('rival') else ''))
        if plan.get('wake') == self.slot and self.state() == 'sleeping' and 'wake' in self.atlas.anim:
            self.play('wake', now, loop=False)                     # stretch and yawn first; the plan's t0 leaves time for it
            self.hold_until = now + self.wake_s(self.character)
        self._goto(plan['pos'][self.slot], now, then='script')
        if kind == 'console':
            self.next_console = now + self.rng.uniform(self.cfg.get('console_min_s', 40), self.cfg.get('console_max_s', 80))

    # -------------------------------------------------------------- movement
    def _goto(self, x, now, then):
        z0, z1 = self.zone
        self.walk_target = max(z0, min(z1, x))
        self.walk_then = then
        self.mode = 'walk'

    def _face_partner(self):
        if self.partner and abs(float(self.partner['x']) - self.x) > 4:
            self.facing = 1 if float(self.partner['x']) > self.x else -1

    def _tick_walk(self, now, dt):
        if now < self.hold_until:                                     # still waking up: stand and play it out
            return
        d = self.walk_target - self.x
        if abs(d) <= 0.8 or self.walk_then in ('wait', 'script') and abs(d) <= 1.5:
            self.x = self.walk_target
            then = self.walk_then
            if then == 'script' and self.script:
                self.mode = 'script'
                self.play('idle', now)
            elif then == 'wait':
                self.play('idle', now)
                self._face_partner()
            else:
                self.mode = 'home'
                self.play(self.base_anim(), now)
            return
        step = min(abs(d), self.cfg['walk_px_s'] * dt)
        self.x += math.copysign(step, d)
        mv = 1 if d > 0 else -1
        if self.walk_then == 'home':                              # V6: turn and walk home (no moonwalk); _tick_home turns back
            self.facing = mv
            self.play('walk', now)
        else:
            if self.partner:
                self._face_partner()
            else:
                self.facing = mv
            self.play('walk' if mv == self.facing else 'walk_back', now)

    # -------------------------------------------------------------- script playback
    def _tick_script(self, now):
        sc = self.script
        if sc is None:
            self._goto(self.home_x, now, then='home')
            return
        tr = self.track
        if tr is None:                                            # (a script set up by hand, e.g. in a test)
            tr = self.track = Track(sc['tl'], self.x, self.zone, self.atlas)
        tr.advance(now, lambda t_abs, name, opts: self._entry(t_abs, name, opts, now))
        self.x = tr.x
        self.stop, self.slow, self.slide = tr.stop, tr.slow, tr.slide
        self.script_i = tr.i
        if self.ghost is not None:
            self.ghost.advance(now, (lambda t_abs, name, opts: self._sound(t_abs, name, opts, now)) if self.sfx else None)
        if now >= sc['t_end']:
            self.learner.after_bout(sc, now)                  # learning: this side's experience from the bout that just ended
            self.script, self.bout = None, None
            self._end_match_visuals()
            self._goto(self.home_x, now, then='home')
            self.next_bout = now + self.rng.uniform(self.cfg['bout_min_s'], self.cfg['bout_max_s'])
            self.next_clash = now + self.rng.uniform(self.cfg.get('clash_min_s', 20), self.cfg.get('clash_max_s', 40))
            self._schedule_rival(now)

    def _entry(self, t_abs, name, opts, now):
        """One timeline entry of this slot's row, after the Track applied its position / freeze / slide."""
        tr = self.track
        self.x = tr.x
        self.stop, self.slow = tr.stop, tr.slow
        if self.sfx is not None:
            self._sound(t_abs, name, opts, now)
        if name.startswith('@'):
            self._directive(name, t_abs, opts, now)
            return
        self.play(name, t_abs, loop=None, hold=bool(opts.get('hold')))
        if 'hp' in opts and isinstance(opts['hp'], dict):
            self.hp = opts['hp'].get(self.slot)
        if isinstance(opts.get('pct'), dict):
            self.pct = opts['pct'].get(self.slot)                # V9: this fighter's damage %, for its plate
        if 'contact' in opts:
            self.contact_log.append((opts['contact'], name))
            self._bout_note('contact', opts['contact'], name)
        if 'react_to' in opts:
            self.hit_log.append((t_abs, name))
            self._bout_note('hit', t_abs, name)

    def _sound(self, t_abs, name, opts, now):
        """V9 sound effects: one entry of either row of the shared timeline (this slot's own, or the opponent's replayed
        ghost) -> at most one sound.  Reactions sit on the struck fighter's row, a swing starts on the striker's, round /
        KO banners are directives; so the one playing process (slot a) hears the whole fight exactly once."""
        from . import sfx
        snd = None
        if name == '@banner':
            snd = sfx.sound_for_banner(opts.get('banner'))
        elif not name.startswith('@'):
            if 'react_to' in opts or name in ('ko', 'clash'):
                snd = sfx.ROW_SOUNDS.get(name)
            elif 'contact' in opts:
                snd = 'whoosh'
        if snd:
            self.sfx.play(snd, t_abs, now)

    def _directive(self, name, t_abs, opts, now):
        """Timeline directives (rounds.py): HP, effects, banner texts, the record.  Every side runs @hp / @fx; only the
        left side of the plan carries @banner and @record, so texts are drawn once and the record is written once."""
        if name == '@hp':
            self.hp = (opts.get('hp') or {}).get(self.slot)
            if isinstance(opts.get('pct'), dict):
                self.pct = opts['pct'].get(self.slot)
            self.round = dict(n=opts.get('round'), wins=opts.get('wins') or {})
        elif name == '@fx':
            if now - t_abs <= 0.5:                               # a stale directive (after a hiccup) is skipped, not replayed late
                until = opts.get('until')
                try:
                    anchor = opts.get('anchor') or self.fx.get(opts['fx']).anchor
                except Exception:
                    anchor = opts.get('anchor')
                gy = self.atlas.ground_y                         # V7.1: on an airborne fighter the spark sits on its body
                if anchor != 'ground':
                    gy -= int(round(self.lift(t_abs) * self.atlas.res))
                self.fxp.spawn(opts['fx'], t_abs, self.x, gy, self.facing, owner=self.slot, anchor=opts.get('anchor'),
                               hand=self.atlas.hand(opts.get('move') or opts['fx']),
                               fade_ms=(max(1.0, (until - t_abs) * 1000.0) if until else None))
        elif name == '@shake':
            if now - t_abs <= 0.5:
                self.fxp.add_shake(t_abs, opts.get('frames', 0), float(opts.get('amp', 0)))
        elif name == '@flash':
            if now - t_abs <= 0.5 and self.flashes_enabled(now):
                self.fxp.flash_at(t_abs, float(opts.get('alpha', 0.6)), max(0.1, float(opts.get('ms', 120)) / 1000.0))
        elif name == '@impact':
            # Impact frames on the struck fighter for 100-160 ms (dark silhouette, inverse, broken outline, white).  V9: made
            # from the sprite it is really showing (render.impact_frame); the V6 fx art was one canned standing pose, which
            # on a fighter going down read as a flat white blob on the floor.  Off with control.json `flashes` off.
            if now - t_abs <= 0.5 and self.flashes_enabled(now) and opts.get('on', self.slot) == self.slot:
                ms = max(100.0, min(160.0, float(opts.get('ms', 130))))
                self.impact = (t_abs, ms / 1000.0)
        elif name == '@armor':                                   # V7: a poke through the armour: HP drops, a short flash, no flinch
            self.hp = (opts.get('hp') or {}).get(self.slot, self.hp)
            self.hit_log.append((t_abs, 'armor'))
            if now - t_abs <= 0.5 and self.flashes_enabled(now):
                self.fxp.flash_at(t_abs, 0.35, 0.1)
        elif name == '@whiff':
            self.hit_log.append((t_abs, 'whiff'))
            self._bout_note('hit', t_abs, 'whiff')
        elif name == '@banner':
            plan = (self.script or {}).get('plan') or {}
            over = opts.get('over')
            if over is None and self.partner and isinstance(self.partner.get('x'), (int, float)):
                x = (self.x + float(self.partner['x'])) / 2.0      # between where the two really stand now
            elif over is None:
                x = (float(plan['pos'][LEFT]) + float(plan['pos'][RIGHT])) / 2.0
            elif over == self.slot:
                x = self.x
            elif self.partner and isinstance(self.partner.get('x'), (int, float)):
                x = float(self.partner['x'])                     # centred over where the winner really stands now
            else:
                x = float(plan['pos'].get(over, self.x))
            self.banner = dict(kind=opts['banner'], until=opts['until'], x=x, name=opts.get('name'))
        elif name == '@record':
            chars = opts.get('chars') or {}
            try:
                self.record(chars.get(opts['winner'], opts['winner']), chars.get(opts['loser'], opts['loser']))
            except Exception:
                pass
            self._bout_note('result', t_abs, f"{chars.get(opts['winner'], '?')}>{chars.get(opts['loser'], '?')}")

    # -------------------------------------------------------------- home behaviour
    def stun(self, now, seconds=1.4):
        """A fast drag leaves the fighter dizzy for a moment (micro-interaction; nothing else changes)."""
        if self.paused:
            return
        self.abort(now)
        self.mode, self.walk_then = 'home', None
        self.play('dizzy', now, loop=True)
        self.stun_until = now + seconds

    def throw(self, vx, now):
        """Shift-drag release: a short arc in the drag direction (inside its own half), then a dizzy landing."""
        if self.paused:
            return
        self.abort(now)
        self.mode, self.walk_then = 'home', None
        lo, hi = self.home
        self.throw_state = dict(vx=float(vx), t0=now, dur=0.55, x0=self.x, target=max(lo, min(hi, self.x + vx * 0.4)))
        self.play('jump', now, loop=False)

    def _tick_throw(self, now, dt):
        th = self.throw_state
        k = min(1.0, (now - th['t0']) / th['dur'])
        self.x = th['x0'] + (th['target'] - th['x0']) * (1 - (1 - k) ** 2)
        self.facing = 1 if th['vx'] > 0 else -1
        if k >= 1.0:
            self.throw_state = None
            self.home_x = self.x
            self.play('dizzy', now, loop=True)
            self.stun_until = now + 1.0

    def _alert(self, now, want):
        have = any(i.tag == 'alert' for i in self.fxp.active)
        if want and not have:
            self.fxp.spawn('alert', now, self.x, self.atlas.ground_y, self.facing, owner=self.slot, tag='alert')
        elif have and not want:
            self.fxp.clear(tag='alert')

    def _tick_home(self, now, dt):
        st = self.state()
        self._alert(now, st == 'waiting' and self.mode == 'home')
        if self.throw_state is not None:
            self._tick_throw(now, dt)
            return
        if now < self.stun_until:
            if self.anim != 'dizzy':
                self.play('dizzy', now, loop=True)
            return
        if self.anim == 'dizzy' and st != 'limit' and self.prev_state == st:
            self.play(self.base_anim(), now)
        if st != self.prev_state:
            was_asleep = self.prev_state == 'sleeping'
            self.prev_state = st
            if was_asleep and st != 'sleeping':
                self.play('wake', now, loop=False)             # stretch and yawn, then whatever comes next
            elif st == 'done':
                self.play('victory', now, loop=False)
            elif st == 'limit':
                self.ko_until = now + 6.0
                self.play('ko', now)
            elif st == 'working':
                self.work_variant, self.work_switch = self._work_anims()[0], now + self.rng.uniform(8, 14)
                self.play(self.work_variant, now)
            else:
                self.play(self.base_anim(), now)
        if st == 'limit' and self.anim == 'ko' and now >= self.ko_until:
            self.play('getup', now, loop=False)
        if st == 'working' and now >= self.work_switch:
            opts = self._work_anims()
            self.work_variant = opts[(opts.index(self.work_variant) + 1) % len(opts)] if self.work_variant in opts else opts[0]
            self.work_switch = now + self.rng.uniform(8, 14)
            self.play(self.work_variant, now)
        if st == 'waiting' and self.anim == 'wait' and now >= self.next_shrug:
            self.next_shrug = now + self.rng.uniform(10, 16)
            self.play('shrug', now, loop=False)
        if st == 'working' and self.anim == self.work_variant and now >= self.next_shadow:
            self.next_shadow = now + self.rng.uniform(self.cfg.get('shadowbox_min_s', 8), self.cfg.get('shadowbox_max_s', 14))
            if self.shadow_pick is None or self.shadow_pick.atlas is not self.atlas:
                self.shadow_pick = choreo.Picker(self.rng, self.atlas)
            if self.shadow_pick.used and sum(self.shadow_pick.used.values()) >= 2 * len(strike_pool(self.atlas)):
                self.shadow_pick.new_round()
            mv = self.shadow_pick.pick(self.shadow_pick.strikes())   # shadowboxing: never the same strike twice in a row
            mv = self.learner.practice(mv, now)                # learning: a rep counts as practice; it may try a new variant
            if mv:
                self.play(mv, now, loop=False)
        self.learner.home(now)                                # learning: the LEARNED moment (the new move once, under a banner)
        lo, hi = self.home                                        # (facing: lock_on at the end of tick, in every state)
        if not (lo - 2 <= self.x <= hi + 2) and not (st == 'limit' and self.anim in ('ko', 'getup')):
            # outside its own half (knocked out mid-bout, an old drag, a resize): walk back, so the two never overlap
            self.home_x = max(lo, min(hi, self.home_x))
            self._goto(self.home_x, now, then='home')
            return
        p = self.partner
        pst = p.get('state') if p else None
        # usage-driven bouts.  Only slot `a` starts timed bouts, so the two never invite each other at the same moment.
        if self.slot == LEFT and p and self._partner_home() and st in AWAKE and pst in AWAKE:
            if now >= self.next_match and self.free_for('match'):   # now and then a full best-of-3 match, whatever the states
                self.next_match = now + self.rng.uniform(self.cfg.get('match_min_s', 180), self.cfg.get('match_max_s', 360))
                if self._send_invite('match', now):
                    return
            if 'working' in (st, pst):                            # anyone working: short clashes
                if now >= self.next_clash and self.free_for('clash'):
                    self.next_clash = now + self.rng.uniform(self.cfg.get('clash_min_s', 20), self.cfg.get('clash_max_s', 40))
                    if self._send_invite('clash', now):
                        return
            elif now >= self.next_bout and self.free_for('spar'):  # nobody working: spar or a ranged duel
                kind = self.rng.choice(self.cfg.get('bout_kinds', ['spar', 'spar', 'ranged']))
                self.next_bout = now + 30
                if self._send_invite(kind, now) or (kind != 'spar' and self._send_invite('spar', now)):
                    return
        # rival mode (V5.1): the awake fighter (either slot) wakes a sleeping partner for a match now and then; while it is
        # working, a short exchange instead.  The sleeper never starts anything, so the two cannot invite each other at once.
        if self.rival and p and self._partner_home() and st in AWAKE and pst == 'sleeping':
            if st == 'working':
                if now >= self.next_rival_spar and self.free_for('clash'):
                    self._schedule_rival(now)
                    if self._send_invite('clash', now, rival=True):
                        return
            elif now >= self.next_rival and self.free_for('match'):
                self._schedule_rival(now)
                if self._send_invite('match', now, rival=True):
                    return
        # a knocked-out partner gets a visit now and then (the first one comes from its limit event)
        if p and pst == 'limit' and now >= self.next_console and self.free_for('console') and self._partner_home():
            self.next_console = now + self.rng.uniform(self.cfg.get('console_min_s', 40), self.cfg.get('console_max_s', 80))
            if self._send_invite('console', now, visitor=self.slot):
                return
        if st == 'idle' and self.anim in ('idle', 'rage'):
            ctx = (self.snap.ctx_pct or 0) if self.snap else 0
            want = 'rage' if ctx >= 85 else 'idle'
            if self.anim != want:
                self.play(want, now)
            if now >= self.next_flourish and self.anim == 'idle':
                self.play('idle_flourish', now, loop=False)       # V6: never the super (it belongs to fights only)
                self.next_flourish = now + self.rng.uniform(6, 10)
            elif now >= self.next_wander:
                self.next_wander = now + self.rng.uniform(12, 25)
                self._goto(self.rng.uniform(*self.home), now, then='home')
