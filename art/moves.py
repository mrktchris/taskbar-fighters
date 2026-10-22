"""Move library: every move is a list of (Pose, ms) keyframes + metadata.

Names are API: the planner and the HUD refer to them.  Categories mirror a fighting-game move list:
locomotion / strikes / specials / defense / reactions / emotes / supers / pair.

V5 (fluid pass, docs/ANIMATION-NOTES.md): every strike is keyed anticipation (opposite direction, 60-100 ms) ->
smear (one frame, 40 ms, the limb drawn as its arc) -> contact hold (`hit_frame`, carries `hitstop_ms`) -> overshoot
(60-80 ms) -> settle.  No two consecutive frames share a duration.  Landings and crouches squash (`sq` < 1), launches
stretch (`sq` > 1), the chest breathes (`chest`), the head leads a hit and the arms follow a frame later.
"""
from __future__ import annotations
import math
from dataclasses import replace
from rig import Pose

S0 = Pose()
HITSTOP = {1: 150, 2: 180, 3: 220}       # ms by power: light / medium / heavy (SF-style 9 / 11 / 13 frames at 60 fps)


def p(**kw):
    return replace(S0, **kw)


def M(frames, loop=False, cat='', desc='', **meta):
    """A move.  Derives `smear_frames` from the poses and a default `hitstop_ms` from `power` when it has a hit_frame."""
    sm = [i for i, (ps, _) in enumerate(frames) if ps.smear_f or ps.smear_b or ps.smear_ff or ps.smear_fb]
    if sm:
        meta.setdefault('smear_frames', sm)
    if 'hit_frame' in meta and 'hitstop_ms' not in meta:
        meta['hitstop_ms'] = HITSTOP.get(meta.get('power', 1), 150)
    return dict(frames=frames, loop=loop, cat=cat, desc=desc, **meta)


# ---------------------------------------------------------------------- V8: the air contract
# The engine draws an airborne row's TRAJECTORY: it lifts the whole sprite by anim.json `air` (RES 1 px above the floor,
# eased per segment) every redraw.  So an airborne key carries only the POSE (squash, stretch, tuck, reach) with the
# hips near standing height (dy -1..0), and the move carries `air_spec`: (frame, fraction into that frame, h[, ease]).
# Fractions (not ms) so `heavier` can stretch a row's frames and the keys stretch with them; resolve_air turns them into
# `air` = [[t_ms, h], [t_ms, h, ease], ...] on the row's own clock once the frame timings are final.
# Ease of the segment ending at a key: 'o' rise (fast, slowing), 'i' fall (slow, faster), 'h' hang (in-out).
def _ease(e, u):
    if e == 'o':
        return 1.0 - (1.0 - u) * (1.0 - u)
    if e == 'i':
        return u * u
    if e == 'h':
        return u * u * (3.0 - 2.0 * u)
    return u


def air_at(keys, t):
    """Height of an `air` curve at t ms (the same function as the engine's air_lift)."""
    if not keys:
        return 0.0
    if t <= keys[0][0]:
        return float(keys[0][1])
    for k0, k1 in zip(keys, keys[1:]):
        if t < k1[0]:
            u = (t - k0[0]) / max(1e-6, float(k1[0] - k0[0]))
            return k0[1] + (k1[1] - k0[1]) * _ease(k1[2] if len(k1) > 2 else 'l', u)
    return float(keys[-1][1])


def _angdiff(a, b):
    """a - b wrapped to (-180, 180]."""
    return (a - b + 180.0) % 360.0 - 180.0


def trail_weapons(body, frames, lag=0.35):
    """The weapon follows the arc instead of snapping: a key that leaves the weapon to the rig (wa / wb None) gets the
    angle the forearm gives it, dragged `lag` of the way back toward where the weapon was on the previous key (one frame
    of overlap).  Explicit keys (the strike frames) are left as authored.  fit_weapons then keeps every angle exactly."""
    out, prev = [], {}
    for ps, ms in frames:
        sk = rig.skeleton(body, ps)
        kw = {}
        for side, field_, spec in (('f', 'wa', body.weapon), ('b', 'wb', body.weapon_b)):
            w = sk['w' + side]
            if w is None or spec is None:
                continue
            want = getattr(ps, field_)
            if want is None:
                hand, el = sk['h' + side], sk['el_' + side]
                nat = math.degrees(math.atan2(hand[1] - el[1], hand[0] - el[0])) + spec.rel
                if side in prev:                       # drag behind the forearm, and never swing more than 55 deg a key
                    d = _angdiff(nat, prev[side]) * (1.0 - lag)
                    want = prev[side] + max(-55.0, min(55.0, d))
                else:
                    want = nat
                kw[field_] = round(want, 1)
            prev[side] = want
        out.append((replace(ps, **kw) if kw else ps, ms))
    return out


def _nearest_fit(body, ps, prev=None, nxt=None):
    """A key fit_weapons could not fit (a long two-handed blade held up at the top of the cell): instead of letting the
    rig turn it toward the side it leans (often 70+ degrees), aim it at the NEAREST angle that fits, either way.
    V9: `prev` = {side: the previous key's drawn angle}; when both ways fit, the cost adds how far each one is from the
    previous key, so a greatsword at full extension does not tip up on the contact and then down on the follow-through
    (a 100-degree flip between two held keys)."""
    if not _turned(body, ps):
        return ps
    sk = rig.skeleton(body, ps)
    kw = {}
    for side, field_, spec in (('f', 'wa', body.weapon), ('b', 'wb', body.weapon_b)):
        want = getattr(ps, field_)
        if spec is None or want is None or sk['w' + side] is None:
            continue
        hand = sk['h' + side]
        best = []
        for sgn in (1, -1):
            for k in range(1, 31):
                a = want + sgn * 3 * k
                b_, t_ = rig._wends(spec, hand, a, spec.grip)
                if rig._wfits(b_, t_):
                    best.append(a)
                    break
        if not best:
            continue
        pa, na = (prev or {}).get(side), (nxt or {}).get(side)

        def cost(a):
            c = abs(_angdiff(a, want))
            c += 0.75 * abs(_angdiff(a, pa)) if pa is not None else 0.0
            return c + (0.4 * abs(_angdiff(a, na)) if na is not None else 0.0)
        kw[field_] = min(best, key=cost)           # min keeps the first (+) on a tie, as before
    return replace(ps, **kw) if kw else ps


def _drawn(body, ps):
    sk = rig.skeleton(body, ps)
    return {s_: sk['w' + s_]['a'] for s_ in ('f', 'b') if sk['w' + s_] is not None}


def _fit_chain(body, frames):
    """_nearest_fit over a row in order, each key aware of the angle the key before it was drawn at."""
    out, prev = [], {}
    for i, (ps, m) in enumerate(frames):
        nx = frames[i + 1][0] if i + 1 < len(frames) else None
        nxt = {} if nx is None else {k: v for k, v in (('f', nx.wa), ('b', nx.wb)) if v is not None}
        ps = _nearest_fit(body, ps, prev, nxt)
        prev = _drawn(body, ps)
        out.append((ps, m))
    return out


def resolve_air(body, mv):
    """air_spec -> `air` (ms keys) on the final frame timings, plus each pose's `vy` (the world vertical motion since the
    previous frame, so the hanging bits trail the trajectory the engine draws).  Weapons trail and are fitted first."""
    mv['frames'] = trail_weapons(body, mv['frames'])
    fit_weapons(body, mv)
    mv['frames'] = _fit_chain(body, mv['frames'])
    ms = [m for _, m in mv['frames']]
    st = [sum(ms[:i]) for i in range(len(ms))]
    keys = []
    for k in mv.pop('air_spec'):
        f, fr, h = k[0], k[1], k[2]
        t = int(round(st[f] + fr * ms[f]))
        keys.append([t, h] if len(k) < 4 or k[3] is None else [t, h, k[3]])
    mv['air'] = keys
    mids = [air_at(keys, st[i] + ms[i] / 2.0) for i in range(len(ms))]
    fr = []
    for i, (ps, m) in enumerate(mv['frames']):
        vy = 0.0 if i == 0 else max(-6.0, min(6.0, -(mids[i] - mids[i - 1])))
        fr.append((replace(ps, vy=round(vy, 2)), m))
    mv['frames'] = fr
    return mv


def push_dust():
    return (('dust', 'ff', 3, 1), ('dust', 'fb', -4, 1))


def land_dust():
    return (('dust', 'ff', 5, 1), ('dust', 'fb', -6, 1))


# ---------------------------------------------------------------------- signature templates
# A character's strike / special / super are built from these, so any roster entry can reuse them with its own
# name, description and effect (the planner reads the names from `signature`, never from the character's name).
# V6 keying (docs/ANIMATION-NOTES.md section 6): a long, held wind-up (two keys, the second a tension hold), ONE smear
# frame where the weapon sweeps its crescent, the contact hold, then a held follow-through on the heavy ones.  `wa` puts
# the weapon where the swing needs it (back over the shoulder on the wind-up, through the target on contact).
def sig_spin(desc, **_):
    """Spinning kick: turn the back to the target, the kick is one smear, the blade trails round with it, a long hold."""
    return M([
        (p(dy=3, lean=12, sq=0.94, hf=(5, 3), wa=-120, turn=0.85), 140),
        (p(dy=2, lean=0, turn=0.6, face='back', hf=(3, -2), hb=(-3, -2), ff=(3, 0), fb=(-3, 0), wa=-150), 80),
        (p(dy=0, lean=-10, turn=0.35, face='back', hf=(-6, -4), hb=(-8, -4), ff=(2, 2), fb=(-2, 0), wa=-170), 50),
        (p(dy=-1, lean=-18, turn=0.5, face='n', sq=1.04, hf=(-6, -6), hb=(-8, -3), ff=(14, 14), fb=(-1, 0), ang_f=-10, dx=4, wa=-160,
           smear_ff=(2, 2)), 40),
        (p(dy=-1, lean=-18, turn=0.8, face='n', hf=(-6, -6), hb=(-8, -3), ff=(15, 14), fb=(-1, 0), ang_f=-10, wa=-155,
           fx=(('spark', 'ff', 4, -1),)), 160),
        (p(dy=-1, lean=-20, turn=0.9, face='n', hf=(-7, -6), hb=(-8, -3), ff=(16, 13), fb=(-1, 0), ang_f=-12, wa=-150), 260),
        (p(dy=0, lean=-8, turn=0.8, ff=(10, 8), fb=(-3, 0)), 100),
        (p(dy=2, lean=6, ff=(8, 1)), 90)],
        cat='strike', desc=desc, hit_frame=4, power=3)


def sig_pound(desc, **_):
    """Leaping slam: load with the weapon back over the shoulder, push off, hang at the top with it raised, bring it down
    in one smear as the body drops, the landing IS the hit (shock + dust), hold it, recover.  V8: the leap is `air`."""
    return M([
        (p(dy=3, lean=12, sq=0.93, hf=(5, 3), wa=-118), 110),
        (p(dy=6, lean=17, sq=0.87, head=(2, 1), hf=(3, 5), wa=-128, face='g'), 120),
        (p(dy=-1, lean=2, sq=1.10, hf=(6, -6), eb_f='up', wa=-140, ff=(5, 0), fb=(-5, 1), ang_f=22, ang_b=22, fx=push_dust()), 60),
        (p(dy=-1, lean=-6, sq=1.02, chest=1.04, hf=(5, -10), eb_f='up', wa=-152, ff=(5, 7), fb=(-4, 6), face='o'), 200),
        (p(dy=3, lean=40, sq=0.98, head=(2, 2), hf=(9, 7), wa=55, fist_f=4, ff=(8, 3), fb=(-6, 2), dx=4, smear_f=(5, -10)), 40),
        (p(dy=10, lean=45, sq=0.88, head=(2, 2), hf=(9, 7), wa=62, fist_f=4, ff=(9, 0), fb=(-6, 0),
           fx=(('shock', 'abs', 38, 56), ('dust', 'ff', 4, -1), ('dust', 'fb', -5, -1))), 160),
        (p(dy=9, lean=42, sq=0.92, head=(2, 2), hf=(9, 7), wa=64, fist_f=4, ff=(9, 0), fb=(-6, 0),
           fx=(('dust', 'ff', 6, -2), ('dust', 'fb', -7, -2))), 280),
        (p(dy=4, lean=18, hf=(7, 5)), 120)],
        cat='strike', desc=desc, hit_frame=5, power=3, shake=dict(frames=4, amp=2),
        air_spec=[(3, 0, 0), (3, 0.6, 16, 'o'), (3, 0.825, 15.5, 'h'), (5, 0, 0, 'i')])


def sig_throw(desc, **_):
    """Slash wave: coil with the weapon back over the shoulder, one smear forward, the wave leaves on proj_frame."""
    return M([
        (p(dy=2, lean=-4, hf=(-1, -6), eb_f='up', wa=-150, fx=(('charge', 'hf', 2, -1),)), 140),
        (p(dy=4, lean=-10, sq=0.95, chest=1.04, hf=(-3, -8), eb_f='up', wa=-165, fx=(('charge', 'hf', 0, -2), ('charge', 'hb', -1, -3))), 110),
        (p(dy=3, lean=20, hf=(12, 1), ff=(11, 0), fb=(-9, 0), wa=22, dx=4, smear_f=(-3, -8)), 40),
        (p(dy=3, lean=24, hf=(12, 2), ff=(12, 0), fb=(-9, 0), wa=28, fx=(('spark', 'hf', 4, 0),)), 180),
        (p(dy=3, lean=26, hf=(12, 3), ff=(12, 0), fb=(-9, 0), wa=40), 230),
        (p(lean=12, hf=(9, 3)), 90), (S0, 110)],
        cat='special', desc=desc, proj_frame=3, power=2)


def sig_cast(desc, **_):
    """Thrust release: draw the weapon back level, hold, one smear thrust, the bolt leaves on proj_frame."""
    return M([
        (p(dy=2, lean=6, hf=(5, 1), wa=-20, fx=(('charge', 'hf', 4, -3),)), 120),
        (p(dy=3, lean=4, hf=(4, 0), wa=-15, fx=(('charge', 'hf', 3, -4), ('charge', 'hb', -2, -3))), 90),
        (p(dy=4, lean=-2, sq=0.96, hf=(0, 2), wa=-8), 150),
        (p(dy=3, lean=22, hf=(13, -1), ff=(12, 0), fb=(-9, 0), wa=-6, dx=4, smear_f=(0, 2)), 40),
        (p(dy=3, lean=24, hf=(13, -1), ff=(12, 0), fb=(-9, 0), wa=-5, fx=(('spark', 'hf', 4, -1),)), 180),
        (p(dy=2, lean=26, hf=(13, 0), ff=(12, 0), fb=(-9, 0), wa=4), 230), (p(lean=12, hf=(9, 2)), 90), (S0, 110)],
        cat='special', desc=desc, proj_frame=4, power=2)


def sig_rewind(desc, glyph='rewind', **_):
    """Super: snap back a second in time with an afterimage trail.  glyph: 'rewind' (<<) or 'bigglyph' (2x cap sigil)."""
    gfx = ('rewind', 'head', 7, -10) if glyph == 'rewind' else ('bigglyph', 'head', 8, -12)
    return M([
        (p(dy=3, lean=6, sq=0.95, hf=(4, 3), fx=(gfx,)), 160),
        (p(dy=2, lean=-6, flash=True), 50),
        (p(dx=-12, dy=-1, lean=-18, sq=1.06, ff=(8, 3), fb=(-8, 2), hf=(3, -2), ghost=(6, 12, 18), fx=(gfx,)), 60),
        (p(dx=-12, dy=-2, lean=-20, sq=1.04, ff=(9, 3), fb=(-9, 3), hf=(2, -3), ghost=(7, 14, 21)), 70),
        (p(dx=-10, dy=-1, lean=-14, ff=(8, 2), fb=(-8, 2), hf=(3, -2), ghost=(7, 14)), 60),
        (p(dx=-4, dy=3, lean=4, sq=0.92, fx=(('dust', 'ff', 4, 1),)), 100),
        (p(dy=1, face='g', hf=(9, 0), fx=(gfx,)), 260)],
        cat='super', desc=desc)


def sig_raise(desc, glyph='bigsigil', **_):
    """Super: raise the weapon and a giant sigil and power up."""
    gfx = ('bigsigil', 'head', 9, -11) if glyph == 'bigsigil' else ('bigglyph', 'head', 9, -12)
    return M([
        (p(dy=3, lean=6, sq=0.95, hf=(5, 4), fist_f=4), 140),
        (p(dy=4, lean=4, sq=0.93, chest=1.04, hf=(5, 5), aura=1, fx=(('charge', 'hf', 3, -3),)), 110),
        (p(dy=1, lean=0, sq=1.06, hf=(6, -8), eb_f='up', wa=-70, aura=2, face='g', fx=(gfx,)), 120),
        (p(dy=2, lean=0, sq=1.02, chest=1.08, hf=(6, -9), eb_f='up', wa=-72, aura=3, face='g', fx=(gfx, ('spark_s', 'hf', 0, -3))), 170),
        (p(dy=3, lean=8, chest=1.10, hf=(6, -7), eb_f='up', wa=-68, aura=4, face='g', fx=(gfx,)), 150),
        (p(dy=2, lean=4, aura=1), 90), (S0, 110)],
        cat='super', desc=desc)


TEMPLATES = {'spin': sig_spin, 'pound': sig_pound, 'throw': sig_throw, 'cast': sig_cast,
             'rewind': sig_rewind, 'raise': sig_raise}


# ---------------------------------------------------------------------- signature idles (V6)
# Every idle is a weight shift (breathing chest, head bob) in the character's own weapon stance, plus one personal tic
# with its weapon in the back half of the loop.  The loop closes on the stance pose.
def make_idle(stance, tic, desc):
    def k(**over):
        kw = dict(stance)
        kw.update(over)
        return kw
    hf, hb = stance.get('hf', (7, 3)), stance.get('hb', (3, 4))
    dy = stance.get('dy', 2)
    frames = [(k(), 170), (k(chest=1.03), 130),
              (k(dy=dy + 1, chest=1.06, head=(1, 1), hf=(hf[0], hf[1] + 1), hb=(hb[0], hb[1] + 1)), 150),
              (k(dy=dy + 1, chest=1.05, head=(1, 1), hf=(hf[0], hf[1] + 1), hb=(hb[0], hb[1] + 1)), 180)]
    frames += [(k(**over), ms) for over, ms in tic]
    frames.append((k(chest=0.98), 140))
    return M([(p(**kw), ms) for kw, ms in frames], loop=True, cat='locomotion', desc=desc)


IDLE_DATA = {
    'guard': (dict(dy=2, lean=10, hf=(7, 3), hb=(3, 4), ff=(8, 0), fb=(-7, 0)),
              [(dict(face='g'), 100), (dict(face='g', head=(2, 0)), 120), (dict(), 220)], 'Guard stance: breathing, weight shift.'),
    'ronin': (dict(dy=2, lean=8, hf=(7, 4), ff=(8, 0), fb=(-8, 0)),
              [(dict(wa=-20, head=(2, 0), face='g'), 100), (dict(wa=-96, face='g', tilt=-4), 80), (dict(face='g'), 240)],
              'Ronin stance: two hands on the katana, tip at the throat; flicks the blade up.'),
    'shadow': (dict(dy=4, lean=18, hf=(8, 2), hb=(1, 5), ff=(9, 0), fb=(-7, 0)),
               [(dict(wa=-30, face='g'), 70), (dict(wa=70, face='g'), 60), (dict(face='g', head=(2, 1)), 220)],
               'Ninja crouch: low, kunai reversed; spins the lead kunai.'),
    'dancer': (dict(dy=1, lean=4, hf=(8, 0), hb=(-4, 3), eb_b='back', ff=(6, 0), fb=(-7, 0)),
               [(dict(hf=(5, -3), hb=(6, -3), eb_b='down', wa=-62, wb=-118, face='g'), 90), (dict(hf=(5, -3), hb=(6, -3), eb_b='down', wa=-60,
                wb=-120, face='g', tilt=-5), 120), (dict(hf=(9, 0), hb=(-5, 2), face='g'), 200)],
               'Dancer stance: one blade forward, one back; crosses them and opens.'),
    'lancer': (dict(dy=3, lean=12, hf=(8, 3), wa=-28, ff=(9, 0), fb=(-7, 0)),
               [(dict(wa=-62, face='g'), 70), (dict(wa=-4, face='g', head=(3, 0), tilt=6), 80), (dict(face='g'), 230)],
               'Lancer stance: spear low and level; twirls the tip and snaps its head.'),
    'mountain': (dict(dy=2, lean=6, hf=(8, 3), wa=-92, ff=(8, 0), fb=(-8, 0)),
                 [(dict(hf=(8, 0), dy=1, sq=1.02), 110), (dict(hf=(8, 5), dy=3, sq=0.95, face='g', fx=(('dust', 'hip', 12, 6),)), 80),
                  (dict(face='g'), 250)], 'Mountain stance: staff planted upright; lifts it and thumps the ground.'),
    'samurai': (dict(dy=2, lean=10, hf=(5, 5), wa=150, ff=(8, 0), fb=(-8, 0)),
                [(dict(wa=166, face='g'), 90), (dict(wa=138, face='g', head=(2, 0)), 80), (dict(face='g'), 230)],
                'Samurai stance: energy blade low and back; the blade hums and flicks.'),
    'ranger': (dict(dy=1, lean=6, hf=(9, 4), wa=4, hb=(1, 6), wb=100, ff=(7, 0), fb=(-7, 0)),
               [(dict(hf=(10, 1), wa=-4, head=(2, 0), face='g'), 120), (dict(hf=(10, 1), wa=-4, head=(2, 0), face='g', tilt=4), 260), (dict(), 110)],
               'Ranger stance: bow forward, dagger low; raises the bow to sight.'),
    'fans': (dict(dy=4, lean=16, hf=(6, -6), eb_f='up', wa=-70, hb=(-4, 4), eb_b='back', ff=(9, 0), fb=(-8, 0)),
             [(dict(wa=-30, hf=(8, -4), face='g'), 90), (dict(wa=-100, hf=(6, -7), face='g', tilt=-4), 110), (dict(face='g'), 210)],
             'Kunoichi stance: one fan forward, one back; flicks the lead fan open.'),
    'knight': (dict(dy=2, lean=6, hf=(8, 5), wa=-64, ff=(8, 0), fb=(-8, 0)),
               [(dict(wa=-56, dy=3, sq=0.97), 110), (dict(wa=-74, head=(2, 0)), 90), (dict(), 240)],
               'Knight stance: greatsword held high in front, both hands low on the grip; shifts its weight.'),
    'berserk': (dict(dy=3, lean=14, hf=(8, -1), wa=-105, hb=(4, 3), fist_b=4, ff=(9, 0), fb=(-8, 0)),
                [(dict(face='o', chest=1.10, head=(2, -1)), 120), (dict(face='o', chest=1.12, head=(3, -1), wa=-90), 220), (dict(face='g'), 100)],
                'Berserker stance: axe raised, hunched; roars.'),
    'tonfa': (dict(dy=3, lean=10, hf=(7, 0), hb=(4, -1), ff=(8, 0), fb=(-7, 0)),
              [(dict(wa=-30, face='g'), 70), (dict(wa=80, face='g'), 60), (dict(face='g'), 230)],
              'Monk stance: tonfa along both forearms; spins the lead tonfa.'),
    'nomad': (dict(dy=2, lean=8, hf=(8, 1), hb=(-3, 4), eb_b='back', ff=(7, 0), fb=(-7, 0)),
              [(dict(wa=120), 70), (dict(wa=240), 80), (dict(face='g'), 230)],
              'Nomad stance: chakrams wide; spins the lead ring.'),
    'oni': (dict(dy=3, lean=16, hf=(9, 2), wa=35, ff=(9, 0), fb=(-9, 0)),
            [(dict(wa=10, hf=(9, 0), dy=2), 120), (dict(wa=48, hf=(9, 4), dy=4, sq=0.95, face='o'), 80), (dict(face='g'), 250)],
            'Oni stance: hunched, the kanabo dragged low; taps the ground.'),
}


def _idle_fn(name):
    st, tic, desc = IDLE_DATA[name]
    return lambda: make_idle(st, tic, desc)


IDLES = {name: _idle_fn(name) for name in IDLE_DATA}


# ---------------------------------------------------------------------- signature victories (V5.1)
def _vic(keys, desc):
    return M([(p(free_b=True, **kw), ms) for kw, ms in keys], cat='emote', desc=desc)


def vic_fistpump():
    m = _vic([
        (dict(dy=4, lean=10, sq=0.88, hf=(5, 3), hb=(3, 3), face='w'), 120),
        (dict(dy=-1, lean=0, sq=1.12, hf=(5, -12), hb=(3, 2), ff=(5, 0), fb=(-4, 1), ang_f=22, ang_b=22, face='w',
              fx=(('star', 'head', -8, -7),) + push_dust()), 60),
        (dict(dy=-1, lean=-4, sq=1.0, hf=(6, -13), hb=(2, 3), ff=(5, 5), fb=(-4, 4), face='w', fx=(('star', 'head', -9, -6), ('star', 'head', 8, -8))), 160),
        (dict(dy=-1, lean=-2, sq=1.05, hf=(6, -13), hb=(2, 3), ff=(5, 3), fb=(-4, 2), face='w'), 80),
        (dict(dy=4, lean=4, sq=0.88, hf=(5, -12), hb=(3, 2), face='w', fx=(('dust', 'ff', 5, 1), ('dust', 'fb', -6, 1))), 70),
        (dict(dy=0, lean=0, sq=1.03, hf=(5, -13), hb=(4, 3), face='w'), 80),
        (dict(dy=1, lean=0, hf=(5, -12), hb=(4, 3), face='w'), 300)], 'Fist pump. Played when a task finishes.')
    m['air_spec'] = [(1, 0.4, 0), (2, 0.35, 13, 'o'), (2, 0.8, 13.5, 'h'), (4, 0, 0, 'i')]     # V9: a real jump
    return m


def vic_monk():
    """Claude: palms together, a deep bow, then up with a two-finger peace sign and a star."""
    return _vic([
        (dict(dy=2, lean=8, hf=(5, -3), hb=(5, -3), fist_f=2, fist_b=2, ff=(5, 0), fb=(-5, 0), face='n'), 160),
        (dict(dy=3, lean=32, head=(3, 3), sq=0.97, hf=(4, 0), hb=(4, 0), fist_f=2, fist_b=2, ff=(5, 0), fb=(-5, 0), face='z'), 120),
        (dict(dy=3, lean=36, head=(3, 3), sq=0.97, hf=(4, 1), hb=(4, 1), fist_f=2, fist_b=2, ff=(5, 0), fb=(-5, 0), face='z'), 320),
        (dict(dy=0, lean=-4, sq=1.06, hf=(6, -12), hb=(2, 3), eb_f='up', open_f=True, ff=(5, 0), fb=(-5, 0), face='w'), 70),
        (dict(dy=1, lean=-6, sq=1.0, tilt=-6, hf=(7, -13), hb=(2, 3), eb_f='up', open_f=True, ff=(5, 0), fb=(-5, 0), face='w',
              fx=(('star', 'head', 9, -9),)), 150),
        (dict(dy=1, lean=-6, tilt=-6, hf=(7, -13), hb=(2, 3), eb_f='up', open_f=True, ff=(5, 0), fb=(-5, 0), face='w',
              fx=(('star', 'head', -8, -10), ('star', 'head', 10, -6))), 150),
        (dict(dy=1, lean=-4, tilt=-4, hf=(7, -13), hb=(2, 3), eb_f='up', open_f=True, ff=(5, 0), fb=(-5, 0), face='w'), 300)],
        'Prayer bow, then a two-finger peace sign.')


def vic_hacker():
    """Codex: throws the hood back a notch, crosses its arms, two slow nods under the visor."""
    return _vic([
        (dict(dy=2, lean=10, hf=(2, -8), hb=(4, 2), ff=(6, 0), fb=(-6, 0), face='g'), 150),
        (dict(dy=1, lean=4, chest=1.06, sq=1.03, hf=(-2, -4), hb=(6, -4), eb_f='down', eb_b='down', fist_f=3, fist_b=3, ff=(6, 0), fb=(-6, 0), face='g'), 90),
        (dict(dy=2, lean=2, chest=1.08, hf=(-2, -4), hb=(6, -4), fist_f=3, fist_b=3, ff=(6, 0), fb=(-6, 0), face='g'), 260),
        (dict(dy=2, lean=4, chest=1.08, head=(1, 2), hf=(-2, -4), hb=(6, -4), fist_f=3, fist_b=3, ff=(6, 0), fb=(-6, 0), face='g'), 140),
        (dict(dy=2, lean=2, chest=1.08, head=(0, 0), hf=(-2, -4), hb=(6, -4), fist_f=3, fist_b=3, ff=(6, 0), fb=(-6, 0), face='g'), 180),
        (dict(dy=2, lean=4, chest=1.08, head=(1, 2), hf=(-2, -4), hb=(6, -4), fist_f=3, fist_b=3, ff=(6, 0), fb=(-6, 0), face='w',
              fx=(('spark_s', 'head', 8, -6),)), 140),
        (dict(dy=2, lean=2, chest=1.06, head=(0, 0), hf=(-2, -4), hb=(6, -4), fist_f=3, fist_b=3, ff=(6, 0), fb=(-6, 0), face='w'), 300)],
        'Hood back, arms crossed, two slow nods.')


def vic_ronin():
    """Gemini: a full spin that whips both ponytails out, landing in a one-arm-up pose with sparkles."""
    return _vic([
        (dict(dy=3, lean=10, sq=0.94, hf=(4, 2), hb=(2, 2), ff=(6, 0), fb=(-6, 0), face='w'), 110),
        (dict(dy=1, lean=0, turn=0.6, face='back', dx=1, hf=(2, -2), hb=(-3, -2), ff=(3, 0), fb=(-3, 0)), 60),
        (dict(dy=0, lean=-6, turn=0.3, face='back', dx=1, sq=1.04, hf=(-4, -6), hb=(-6, -4), ff=(2, 1), fb=(-2, 0)), 50),
        (dict(dy=0, lean=-4, turn=0.7, dx=-1, sq=1.04, hf=(6, -10), hb=(-5, 0), ff=(4, 2), fb=(-4, 0), face='w'), 60),
        (dict(dy=1, lean=-6, turn=1.0, dx=-1, hf=(7, -13), hb=(-3, 4), eb_f='up', eb_b='back', ff=(6, 0), fb=(-6, 0), face='w',
              fx=(('star', 'head', 9, -10), ('star', 'head', -9, -4))), 160),
        (dict(dy=2, lean=-4, sq=0.97, hf=(7, -13), hb=(-3, 4), eb_f='up', eb_b='back', ff=(6, 0), fb=(-6, 0), face='w',
              fx=(('star', 'head', -10, -9), ('star', 'head', 10, -4), ('star', 'head', 1, -13))), 150),
        (dict(dy=1, lean=-4, hf=(7, -13), hb=(-3, 4), eb_f='up', eb_b='back', ff=(6, 0), fb=(-6, 0), face='w'), 300)],
        'A spin that whips the ponytails, one arm up, sparkles.')


def vic_pointer():
    """Cursor: a sharp point at the beaten opponent, a click (the hand snaps), then a cool head tilt."""
    return _vic([
        (dict(dy=3, lean=10, sq=0.96, hf=(4, -2), hb=(2, 2), ff=(7, 0), fb=(-6, 0), face='g'), 120),
        (dict(dy=2, lean=22, dx=2, hf=(13, -4), hb=(1, 2), open_f=True, ff=(10, 0), fb=(-7, 0), face='g', smear_f=(4, -2)), 50),
        (dict(dy=2, lean=24, hf=(14, -4), hb=(1, 2), open_f=True, ff=(10, 0), fb=(-7, 0), face='g'), 260),
        (dict(dy=2, lean=24, hf=(13, -3), hb=(1, 2), fist_f=3, ff=(10, 0), fb=(-7, 0), face='g', fx=(('spark_s', 'hf', 3, -1),)), 70),
        (dict(dy=2, lean=24, hf=(14, -4), hb=(1, 2), open_f=True, ff=(10, 0), fb=(-7, 0), face='g', fx=(('block', 'hf', 4, -2),)), 160),
        (dict(dy=2, lean=16, head=(2, 0), tilt=8, hf=(10, -2), hb=(1, 2), ff=(9, 0), fb=(-7, 0), face='w'), 140),
        (dict(dy=2, lean=14, head=(2, 0), tilt=8, hf=(9, -1), hb=(1, 2), ff=(9, 0), fb=(-7, 0), face='w'), 300)],
        'Points at the loser, clicks, head tilt.')


def vic_brawler():
    """Ollama: a ground-shaking stomp, a double-arm flex, then a jump with both fists in the air."""
    m = _vic([
        (dict(dy=-3, lean=6, sq=1.06, hf=(5, -3), hb=(3, -3), fist_f=4, fist_b=4, ff=(6, 6), fb=(-6, 0), face='g'), 110),
        (dict(dy=5, lean=10, sq=0.86, hf=(6, 2), hb=(3, 2), fist_f=4, fist_b=4, ff=(8, 0), fb=(-7, 0), face='g',
              fx=(('dust', 'ff', 5, 1), ('shock', 'abs', 38, 56))), 130),
        (dict(dy=2, lean=0, chest=1.10, hf=(6, -8), hb=(2, -8), eb_f='up', eb_b='up', fist_f=4, fist_b=4, ff=(7, 0), fb=(-7, 0), face='g'), 260),
        (dict(dy=4, lean=4, sq=0.90, chest=1.04, hf=(5, 3), hb=(2, 3), fist_f=4, fist_b=4, ff=(7, 0), fb=(-7, 0), face='w'), 90),
        (dict(dy=-1, lean=0, sq=1.08, hf=(6, -13), hb=(2, -13), eb_f='up', eb_b='up', fist_f=4, fist_b=4, ff=(5, 4), fb=(-4, 3), face='w',
              fx=(('star', 'head', -9, -8), ('star', 'head', 9, -8))), 220),
        (dict(dy=4, lean=6, sq=0.88, hf=(5, -8), hb=(2, -8), eb_f='up', eb_b='up', fist_f=4, fist_b=4, ff=(7, 0), fb=(-7, 0), face='w',
              fx=(('dust', 'ff', 5, 1), ('dust', 'fb', -6, 1))), 80),
        (dict(dy=1, lean=2, chest=1.06, hf=(6, -10), hb=(2, -10), eb_f='up', eb_b='up', fist_f=4, fist_b=4, ff=(7, 0), fb=(-7, 0), face='w'), 300)],
        'Stomp, flex, and a two-fist jump.')
    m['air_spec'] = [(4, 0, 0), (4, 0.4, 12, 'o'), (4, 0.6, 12.5, 'h'), (5, 0, 0, 'i')]          # V9: a real jump
    return m


def vic_agent():
    """Generic: snaps to attention, a crisp salute, holds it, then stands at ease with the hands behind the back."""
    return _vic([
        (dict(dy=2, lean=6, hf=(4, 2), hb=(1, 3), ff=(5, 0), fb=(-6, 0), face='n'), 120),
        (dict(dy=1, lean=0, chest=1.06, sq=1.03, hf=(3, -7), hb=(0, 6), ff=(2, 0), fb=(-3, 0), fist_f=3, face='n', smear_f=(4, 2)), 50),
        (dict(dy=1, lean=0, chest=1.08, hf=(3, -8), hb=(0, 6), ff=(2, 0), fb=(-3, 0), fist_f=3, face='n'), 300),
        (dict(dy=1, lean=0, chest=1.08, hf=(3, -8), hb=(0, 6), ff=(2, 0), fb=(-3, 0), fist_f=3, face='w', fx=(('star', 'head', 9, -8),)), 160),
        (dict(dy=1, lean=2, chest=1.04, hf=(4, -2), hb=(0, 6), ff=(2, 0), fb=(-3, 0), face='w'), 90),
        (dict(dy=1, lean=2, hf=(-3, 5), hb=(-3, 5), eb_f='back', eb_b='back', ff=(5, 0), fb=(-6, 0), face='w'), 140),
        (dict(dy=1, lean=2, chest=1.03, hf=(-3, 5), hb=(-3, 5), eb_f='back', eb_b='back', ff=(5, 0), fb=(-6, 0), face='w'), 300)],
        'Attention, salute, at ease.')


VICTORIES = {'fistpump': vic_fistpump, 'monk': vic_monk, 'hacker': vic_hacker, 'ronin': vic_ronin, 'pointer': vic_pointer,
             'brawler': vic_brawler, 'agent': vic_agent}


def build_moves(character):
    """character: a roster.Character or its name.  Shared move set + the character's three signature moves."""
    import roster
    ch = roster.get(character)
    body = ch.body
    mv = {}

    # ------------------------------------------------------------------ locomotion
    # idle: the character's signature stance (weight shift + personal tic); 'guard' is the shared default
    mv['idle'] = IDLES[ch.style.get('idle', 'guard')]()
    mv['idle_flourish'] = M([
        (p(dy=3, lean=16, sq=0.94, hf=(5, 3), hb=(2, 3), ff=(8, 0), fb=(-7, 0)), 100),
        (p(dy=-1, lean=4, sq=1.06, hf=(9, -5), hb=(6, -6), ff=(6, 2), fb=(-5, 1), face='g'), 80),
        (p(dy=-1, lean=6, hf=(10, -3), hb=(7, -4), face='g'), 100),
        (p(dy=3, lean=14, sq=0.94, hf=(5, -3), hb=(8, -1), face='g'), 110),
        (p(dy=1, lean=10, hf=(8, -3), hb=(5, -4), face='g'), 110),
        (S0, 120)], cat='locomotion', desc='Shoulder roll and hop; plays every 6-10 s while idle.',
        air_spec=[(1, 0, 0), (1, 0.5, 3, 'o'), (2, 0.4, 3, 'h'), (3, 0, 0, 'i')])          # V9: the hop is a real one
    # walk: contact / down / passing, twice.  Head lowest on the down frames, highest on passing; arms counter the legs.
    fa = [(6, 0), (2, 0), (-2, 0), (-6, 0), (0, 3), (4, 1)]
    wdy = [1, 2, 0, 1, 2, 0]
    wsq = [1.0, 0.97, 1.03, 1.0, 0.97, 1.03]
    whead = [0, 1, -1, 0, 1, -1]
    wlean = [12, 14, 11, 12, 14, 11]
    warm = [((8, 2), (2, 4)), ((7, 3), (3, 4)), ((6, 4), (4, 3)), ((5, 4), (5, 3)), ((6, 3), (4, 4)), ((7, 2), (3, 4))]
    walk = []
    for i in range(6):
        a, b = fa[i], fa[(i + 3) % 6]
        walk.append((p(dx=4, dy=wdy[i], sq=wsq[i], head=(1, whead[i]), lean=wlean[i], hf=warm[i][0], hb=warm[i][1], ff=a, fb=b, face='f', fk=1.0), 100))
    mv['walk'] = M(walk, loop=True, cat='locomotion', desc='Stride-locked walk: contact, down, passing; planted foot does not slide.', stride=24)
    mv['walk_back'] = M([(replace(f, dx=-4), 110) for f, _ in reversed(walk)], loop=True, cat='locomotion',
                        desc='Retreat while facing the opponent.', stride=24)
    mv['dash'] = M([
        (p(dy=3, lean=8, sq=0.90, hf=(4, 3), hb=(0, 2), ff=(6, 0), fb=(-4, 0)), 60),
        (p(dx=14, dy=-2, lean=30, sq=1.10, hf=(10, 2), wa=-10, ff=(9, 4), fb=(-6, 2), ghost=(6,)), 50),
        (p(dx=14, dy=-3, lean=28, sq=1.04, hf=(9, 2), wa=-10, ff=(8, 3), fb=(-7, 3), ghost=(7, 14), fx=(('dust', 'fb', -5, 3), ('speedlines', 'hip', -10, -6))), 60),
        (p(dx=8, dy=3, lean=18, sq=0.90, hf=(8, 2), ff=(11, 0), fb=(-2, 0), fx=(('dust', 'fb', -3, 1),)), 80),
        (p(dx=2, sq=1.02), 110)], cat='locomotion', desc='Low dash forward that covers real ground, with dust and speed lines.')
    mv['backdash'] = M([
        (p(dy=3, lean=4, sq=0.92, hf=(4, 2), hb=(1, 2)), 50),
        (p(dx=-12, dy=-2, lean=-16, sq=1.08, hf=(4, 0), ff=(8, 3), fb=(-8, 2), ghost=(7, 14, 21)), 60),
        (p(dx=-12, dy=-3, lean=-20, sq=1.03, hf=(3, -1), ff=(9, 3), fb=(-9, 3), ghost=(8, 16)), 50),
        (p(dx=-6, dy=3, lean=-8, sq=0.90, hf=(5, 2), ff=(10, 0), fb=(-4, 0), fx=(('dust', 'ff', 4, 1),)), 80),
        (p(dx=-1, sq=1.02), 110)], cat='defense', desc='Evasive hop back with an afterimage trail.')
    mv['turn'] = M([(p(lean=0, hf=(5, 2), hb=(5, 2), ff=(2, 0), fb=(-2, 0), turn=0.7, face='back'), 60), (S0, 60)],
                   cat='locomotion', desc='Pivot to face the other way.')
    mv['crouch'] = M([(p(dy=3, lean=14, sq=0.96, hf=(7, 1), hb=(3, 2), ff=(8, 0), fb=(-7, 0)), 60),
                      (p(dy=6, lean=18, sq=0.92, hf=(7, 2), hb=(3, 3), ff=(9, 0), fb=(-8, 0)), 120),
                      (p(dy=7, lean=18, sq=0.91, hf=(7, 2), hb=(3, 3), ff=(9, 0), fb=(-8, 0)), 120)],
                     loop=True, loop_range=(1, 2), cat='locomotion', desc='Low stance.')
    # V8 jump: the engine lifts the sprite along `air`; these keys are the pose only.  Two loading keys (arms swing back,
    # deepest squash held), a push-off stretch with the toes still on the floor (dust), the rise (arms lead up, legs
    # trail pointed), the apex tuck held longest, the fall (legs reach for the floor, arms lag up), the landing squash
    # (arms still coming down) and an overshoot back to the stance.
    wpn = body.weapon
    lh = 5 if (wpn is not None and wpn.length >= 18 and not wpn.slide) else 0   # a long blade cannot stand up at the cell top
    mv['jump'] = M([
        (p(dy=3, lean=13, sq=0.94, head=(1, 1), hf=(4, 4), hb=(0, 5), ff=(8, 0), fb=(-7, 0)), 80),
        (p(dy=6, lean=20, sq=0.86, head=(2, 1), hf=(-1, 6), hb=(-4, 5), free_b=True, ff=(8, 0), fb=(-7, 0), face='g'), 100),
        (p(dy=-1, lean=6, sq=1.10, head=(1, -1), hf=(8, -2 + lh), hb=(-3, 0), free_b=True, ff=(5, 0), fb=(-5, 1), ang_f=22, ang_b=22,
           fx=push_dust()), 60),
        (p(dy=-1, lean=3, sq=1.06, hf=(11, -6 + lh), hb=(-5, -6), eb_b='up', free_b=True, ff=(3, 3), fb=(-4, 2), ang_f=30, ang_b=30), 140),
        (p(dy=-1, lean=4, hf=(11, -2 + lh * 0.6), hb=(-6, -2), free_b=True, ff=(5, 8), fb=(-1, 7), face='w'), 170),
        (p(dy=0, lean=6, sq=1.04, hf=(10, -7 + lh), hb=(-6, -7), eb_b='up', free_b=True, ff=(7, 2), fb=(-5, 1), ang_f=-8), 160),
        (p(dy=6, lean=18, sq=0.86, head=(2, 2), hf=(9, 1), hb=(2, 3), free_b=True, ff=(8, 0), fb=(-7, 0), fx=land_dust()), 90),
        (p(dy=2, lean=11, sq=1.02, hf=(7, 3), hb=(3, 4)), 130)],
        cat='locomotion', desc='Neutral jump: load, push off, rise, tuck at the apex, reach for the floor, squash on landing.',
        air_spec=[(3, 0, 0), (4, 0.353, 19, 'o'), (5, 0, 18, 'h'), (6, 0, 0, 'i')])

    # ------------------------------------------------------------------ strikes (V6: weapon swings, section-6 timing)
    # wind-up held over two keys -> one smear (the crescent) -> contact hold (hitstop) -> held follow-through -> settle
    mv['jab'] = M([
        (p(dy=3, lean=2, sq=0.96, turn=0.9, hf=(2, 4), wa=-12, ff=(6, 0), fb=(-8, 0)), 110),
        (p(dy=4, lean=0, sq=0.95, turn=0.9, hf=(1, 4), wa=-10, ff=(6, 0), fb=(-8, 0)), 70),
        (p(dy=2, lean=24, hf=(8, 1), wa=-4, ff=(12, 0), fb=(-9, 0), fist_f=4, dx=5, smear_f=(1, 4)), 40),
        (p(dy=2, lean=26, hf=(8, 1), wa=-3, ff=(12, 0), fb=(-9, 0), fist_f=4, fx=(('spark', 'hf', 3, 0),)), 140),
        (p(dy=2, lean=28, hf=(8, 2), wa=6, ff=(12, 0), fb=(-9, 0), fist_f=4), 70),
        (p(dy=1, lean=14, hf=(9, 2), ff=(9, 0), fb=(-7, 0)), 120),
        (S0, 90)],
        cat='strike', desc='Fast lead-hand thrust. Light hit, small hit-stop.', hit_frame=3, power=1)
    mv['cross'] = M([
        (p(dy=2, lean=-6, chest=1.05, turn=0.85, hf=(-2, -8), eb_f='up', wa=-150, ff=(7, 0), fb=(-8, 0)), 130),
        (p(dy=3, lean=-10, sq=0.96, turn=0.85, hf=(-4, -9), eb_f='up', wa=-160, ff=(7, 0), fb=(-9, 0)), 90),
        (p(dy=3, lean=24, hf=(12, 3), wa=38, ff=(12, 0), fb=(-9, 0), fist_f=4, dx=5, smear_f=(-4, -9)), 40),
        (p(dy=3, lean=28, hf=(12, 4), wa=42, ff=(12, 0), fb=(-9, 0), fist_f=4, fx=(('spark', 'hf', 3, 0),)), 160),
        (p(dy=3, lean=30, hf=(11, 6), wa=58, ff=(12, 0), fb=(-9, 0), fist_f=4), 230),
        (p(dy=2, lean=14, hf=(8, 4), ff=(9, 0), fb=(-8, 0)), 100),
        (S0, 80)], cat='strike', desc='Big diagonal power slash. Medium hit, forces a block-stagger.', hit_frame=3, power=2)
    mv['uppercut'] = M([
        (p(dy=4, lean=14, hf=(3, 8), wa=130, ff=(8, 0), fb=(-7, 0)), 120),
        (p(dy=7, lean=18, sq=0.90, hf=(4, 9), wa=140, ff=(9, 0), fb=(-8, 0)), 80),
        (p(dy=-1, lean=0, sq=1.08, hf=(6, -12), wa=-92, ff=(8, 0), fb=(-6, 0), fist_f=4, dx=2, smear_f=(4, 9)), 40),
        (p(dy=-1, lean=0, sq=1.06, hf=(6, -13), wa=-94, ff=(7, 3), fb=(-5, 2), fist_f=4, fx=(('spark', 'hf', 0, -4),)), 150),
        (p(dy=-1, lean=-4, sq=1.03, hf=(5, -14), wa=-104, ff=(7, 2), fb=(-5, 1), fist_f=4), 220),
        (p(dy=3, lean=8, sq=0.94, hf=(7, -2), fx=land_dust()), 100),
        (S0, 90)], cat='strike', desc='Rising launcher slash. Pops the opponent up.', hit_frame=3, power=2,
        # V9: the rise is a real little hop off the floor (the engine's lift), not the hips jumping inside the cell
        air_spec=[(2, 0, 0), (3, 0, 4, 'o'), (4, 0.4, 4.5, 'h'), (5, 0, 0, 'i')])
    mv['low_kick'] = M([
        (p(dy=3, lean=6, hf=(2, 3), wa=-120), 110),
        (p(dy=7, lean=-6, sq=0.94, turn=0.7, hf=(-3, 4), wa=-140, ff=(3, 1), fb=(-9, 0)), 70),
        (p(dy=8, lean=-10, turn=0.6, hf=(-4, 5), wa=-150, ff=(15, 0), fb=(-8, 0), dx=4, smear_ff=(3, 1)), 40),
        (p(dy=8, lean=-10, turn=0.7, hf=(-4, 5), wa=-150, ff=(15, 0), fb=(-8, 0), fx=(('spark', 'ff', 4, -1),)), 140),
        (p(dy=8, lean=-12, turn=0.75, hf=(-5, 5), wa=-150, ff=(16, 0), fb=(-8, 0)), 180),
        (p(dy=4, lean=0, hf=(2, 4), ff=(10, 0), fb=(-8, 0)), 90),
        (S0, 100)], cat='strike', desc='Sweep along the ground with a hip turn. Trips guard-high opponents.', hit_frame=3, power=1)
    mv['roundhouse'] = M([
        (p(dy=1, lean=-2, turn=0.8, hf=(4, 2), wa=-110, ff=(6, 9), fb=(-4, 0)), 140),
        (p(dy=0, lean=-14, sq=0.96, turn=0.55, hf=(-3, -4), wa=-150, ff=(3, 12), fb=(-3, 0)), 90),
        (p(dy=0, lean=-18, sq=1.03, turn=0.7, hf=(-5, -5), wa=-160, ff=(16, 14), fb=(-3, 0), dx=4, ang_f=-15, smear_ff=(3, 12)), 40),
        (p(dy=0, lean=-18, turn=0.8, hf=(-5, -5), wa=-160, ff=(16, 14), fb=(-3, 0), ang_f=-15, fx=(('spark', 'ff', 4, -1),)), 160),
        (p(dy=0, lean=-20, turn=0.9, hf=(-6, -5), wa=-158, ff=(17, 13), fb=(-3, 0), ang_f=-18), 260),
        (p(dy=1, lean=-8, hf=(0, 0), ff=(11, 8), fb=(-4, 0)), 110),
        (p(dy=1, lean=4, ff=(8, 1)), 90),
        (S0, 120)], cat='strike', desc='High kick with a full hip turn. Heavy hit, big hit-stop, held follow-through.', hit_frame=3, power=3)
    for role in ('strike', 'special'):                 # same row order as before: strike, special after the shared strikes
        name = ch.signature[role]
        tpl, desc, opts = ch.sig_moves[name]
        mv[name] = TEMPLATES[tpl](desc, **opts)

    # ------------------------------------------------------------------ defense
    mv['block'] = M([(p(dy=2, lean=4, hf=(5, -2), hb=(3, -1), wa=-96, wb=-100), 60),
                     (p(dy=3, lean=2, chest=1.03, hf=(7, -3), hb=(5, -3), wa=-100, wb=-104, ff=(8, 0), fb=(-7, 0), fist_f=4), 120),
                     (p(dy=3, lean=1, chest=1.0, hf=(7, -4), hb=(5, -3), wa=-100, wb=-104, ff=(8, 0), fb=(-7, 0), fist_f=4), 110),
                     (p(dy=2, lean=6, hf=(6, -1), hb=(3, 1), wa=-80), 80)],
                    loop=True, loop_range=(1, 2), cat='defense', desc='High guard.')
    mv['block_hit'] = M([(p(dy=3, lean=-6, sq=0.96, hf=(6, -3), hb=(4, -3), wa=-108, wb=-110, fist_f=4, fx=(('block', 'hf', 4, -3),), dx=-3), 50),
                         (p(dy=3, lean=-3, sq=0.98, hf=(5, -3), hb=(3, -3), wa=-104, wb=-106, fist_f=4, dx=-1), 80),
                         (p(dy=3, lean=3, hf=(7, -3), hb=(5, -3), wa=-100, wb=-104, fist_f=4), 100)],
                        cat='defense', desc='Guard absorbs a hit with a flash.')
    mv['crouch_block'] = M([(p(dy=7, lean=14, sq=0.92, hf=(8, 1), hb=(6, 2), wa=-60, wb=-70, ff=(9, 0), fb=(-8, 0), fist_f=4), 80),
                            (p(dy=8, lean=14, sq=0.91, hf=(8, 1), hb=(6, 2), wa=-60, wb=-70, ff=(9, 0), fb=(-8, 0), fist_f=4), 120)],
                           loop=True, loop_range=(0, 1), cat='defense', desc='Low guard.')
    mv['parry'] = M([(p(dy=2, lean=4, hf=(4, -4), wa=-110), 70),
                     (p(dy=2, lean=12, hf=(12, 0), wa=10, face='g', smear_f=(4, -4), fx=(('block', 'hf', 3, -1),)), 90),
                     (p(dy=2, lean=14, hf=(13, 1), wa=18, face='g'), 160),
                     (p(dy=1, lean=10, hf=(9, 2), face='g'), 100)],
                    cat='defense', desc='Swat the strike aside with a flash. Counter window.', hit_frame=1)

    # ------------------------------------------------------------------ reactions (the head leads, the arms follow)
    mv['hit'] = M([(p(flash=True, lean=-6, head=(-3, -1), hf=(8, -1), hb=(4, 1), face='h', dx=-2), 50),
                   (p(lean=-16, head=(-4, 0), hf=(7, 1), hb=(3, 2), ff=(6, 0), fb=(-8, 0), face='h', dx=-2), 70),
                   (p(lean=-12, head=(-2, 0), hf=(3, 4), hb=(0, 4), ff=(6, 0), fb=(-8, 0), face='h', dx=-1), 80),
                   (p(lean=2, head=(0, 0), hf=(6, 1), hb=(3, 1), face='h'), 70), (S0, 90)],
                  cat='reaction', desc='Head snap first, body follows, overshoots forward, settles.')
    mv['hit_heavy'] = M([(p(flash=True, lean=-12, head=(-4, -1), hf=(7, 0), hb=(3, 2), face='h', dx=-4, dy=0), 50),
                         (p(lean=-28, head=(-5, -1), sq=1.04, hf=(4, 3), hb=(1, 4), ff=(8, 2), fb=(-4, 1), face='h', dx=-5), 70),
                         (p(lean=-30, head=(-4, 0), hf=(1, 6), hb=(-2, 6), ff=(9, 1), fb=(-3, 0), face='h', dx=-4), 90),
                         (p(lean=-18, head=(-2, 0), hf=(3, 5), hb=(0, 5), ff=(9, 1), fb=(-3, 0), face='h', dx=-3), 90),
                         (p(lean=6, dy=3, sq=0.95, face='o', hf=(6, 2), hb=(3, 3)), 90), (S0, 100)],
                        cat='reaction', desc='Slides back, arms fly, wobbles forward, settles.')
    ldy = body.lie_dy                              # hips on the same row when lying, whatever the leg length
    lying = dict(lean=-90, dy=ldy, head=(-2, -2), hf=(-4, 3), hb=(-7, 1), eb_f='up', eb_b='up', ff=(12, 1), fb=(10, 0), face='x', cx=5)
    mv['knockdown'] = M([
        (p(flash=True, lean=-14, head=(-4, -1), hf=(5, 2), hb=(1, 3), face='h', dx=-4), 50),
        (p(lean=-30, dy=-3, sq=1.08, head=(-5, -1), hf=(1, 5), hb=(-2, 5), ff=(8, 3), fb=(-4, 2), face='h', dx=-5), 70),
        (p(lean=-60, dy=1, sq=1.0, head=(-3, 0), hf=(0, 6), hb=(-3, 5), ff=(10, 6), fb=(7, 5), face='h', dx=-5, cx=2), 90),
        (p(**{**lying, 'lean': -82, 'dy': ldy - 1, 'cx': 4}, sq=0.90, dx=-2, fx=(('dust', 'hip', -2, 5), ('dust', 'hip', 6, 4))), 70),
        (p(**{**lying, 'dy': ldy - 2}, sq=0.96), 60),
        (p(**lying, fx=(('dust', 'hip', -6, 4),)), 110), (p(**lying), 160)],
        cat='reaction', desc='Falls through an arc, flattens on impact, bounces once.', shake=dict(frames=3, amp=1))
    mv['getup'] = M([
        (p(**lying), 160),
        (p(**{**lying, 'lean': -80, 'dy': ldy - 1, 'hf': (-2, 6), 'face': 'o'}), 100),
        (p(lean=-50, dy=8, sq=1.05, hf=(3, 9), hb=(0, 9), ff=(10, 3), fb=(6, 2), face='o', cx=3), 90),
        (p(lean=-10, dy=7, sq=0.92, hf=(6, 8), hb=(3, 8), ff=(9, 0), fb=(-7, 0), face='f', cx=1, fx=(('dust', 'ff', 4, 1),)), 80),
        (p(lean=8, dy=2, sq=1.03, ff=(8, 0), fb=(-7, 0)), 70), (S0, 90)], cat='reaction', desc='Kip up from a knockdown.')
    stars = [(('star', 'head', -7, -9), ('star', 'head', 6, -8), ('star', 'head', 0, -11)),
             (('star', 'head', 7, -9), ('star', 'head', -6, -8), ('star', 'head', 1, -11)),
             (('star', 'head', 0, -9), ('star', 'head', 8, -10), ('star', 'head', -8, -10))]
    mv['dizzy'] = M([(p(dy=2, lean=6, head=(2, 1), tilt=8, face='x', hf=(4, 5), hb=(1, 5), fx=stars[0]), 130),
                     (p(dy=2, lean=-2, head=(0, 1), tilt=-6, face='x', hf=(4, 5), hb=(1, 5), fx=stars[1]), 130),
                     (p(dy=2, lean=8, head=(2, 1), tilt=8, face='x', hf=(4, 5), hb=(1, 5), fx=stars[2]), 130),
                     (p(dy=2, lean=0, head=(1, 1), tilt=-8, face='x', hf=(4, 5), hb=(1, 5), fx=stars[0]), 130)],
                    loop=True, cat='reaction', desc='Stagger with stars. Used when a fighter is near its limit.')
    ko_stars = [(('star', 'head', -3, -8), ('star', 'head', 4, -9), ('star', 'head', -9, -7)),
                (('star', 'head', 2, -9), ('star', 'head', -5, -8), ('star', 'head', 6, -7)),
                (('star', 'head', 5, -8), ('star', 'head', -8, -9), ('star', 'head', -2, -10))]
    mv['ko'] = M([
        (p(flash=True, lean=-14, head=(-4, -1), hf=(5, 2), hb=(1, 3), face='h', dx=-4), 50),
        (p(lean=-30, dy=-3, sq=1.08, head=(-5, -1), hf=(1, 5), hb=(-2, 5), ff=(8, 3), fb=(-4, 2), face='h', dx=-5), 70),
        (p(lean=-60, dy=1, head=(-3, 0), hf=(0, 6), hb=(-3, 5), ff=(10, 6), fb=(7, 5), face='h', dx=-5, cx=2), 90),
        (p(**{**lying, 'lean': -82, 'dy': ldy - 1, 'cx': 4}, sq=0.90, dx=-2), 80),
        (p(**lying, fx=ko_stars[0]), 200), (p(**lying, fx=ko_stars[1]), 200), (p(**lying, fx=ko_stars[2]), 200)],
        loop=True, loop_range=(4, 6), cat='reaction', desc='Knocked out; stars orbit. Shown when a plan limit is hit.')

    # ------------------------------------------------------------------ emotes / states
    mv['victory'] = VICTORIES[ch.style.get('victory', 'fistpump')]()        # the character's own win pose
    mv['victory2'] = M([(p(dy=2, lean=0, chest=1.04, hf=(5, -7), hb=(2, -7), eb_f='up', eb_b='up', face='g', fist_f=4, fist_b=4), 140),
                        (p(dy=1, lean=0, chest=1.10, hf=(5, -8), hb=(2, -8), eb_f='up', eb_b='up', face='g', fist_f=4, fist_b=4), 140),
                        (p(dy=2, lean=0, chest=1.04, hf=(5, -7), hb=(2, -7), eb_f='up', eb_b='up', face='g', fist_f=4, fist_b=4), 140),
                        (p(dy=1, lean=0, chest=1.10, hf=(5, -8), hb=(2, -8), eb_f='up', eb_b='up', face='g', fist_f=4, fist_b=4), 140)],
                       cat='emote', desc='Flex. The big-win version.')
    mv['taunt'] = M([(p(lean=6, hf=(10, -1), open_f=True, face='g'), 120), (p(lean=6, hf=(9, 0), face='g'), 120),
                     (p(lean=6, hf=(10, -1), open_f=True, face='g'), 120), (p(lean=6, hf=(9, 0), face='g'), 120),
                     (p(lean=8, head=(2, 0), tilt=-6, hf=(5, 0), face='g'), 140), (S0, 100)],
                    cat='emote', desc="Come-on beckon. Used when the other fighter's idle too long.")
    mv['bow'] = M([(p(dy=1, lean=14, hf=(3, 3), hb=(2, 3), ff=(4, 0), fb=(-3, 0), face='n'), 150),
                   (p(dy=2, lean=35, head=(3, 3), hf=(2, 5), hb=(1, 5), ff=(4, 0), fb=(-3, 0), face='z'), 200),
                   (p(dy=2, lean=36, head=(3, 3), hf=(2, 5), hb=(1, 5), ff=(4, 0), fb=(-3, 0), face='z'), 250),
                   (p(dy=1, lean=14, hf=(3, 3), hb=(2, 3), ff=(4, 0), fb=(-3, 0), face='n'), 150)],
                  cat='pair', desc='Respect bow before and after a bout.')
    mv['fistbump'] = M([(p(lean=6, hf=(4, 0), face='n'), 100), (p(lean=10, hf=(11, 0), fist_f=4, face='n', smear_f=(4, 0)), 60),
                        (p(lean=12, hf=(12, 0), fist_f=4, fx=(('spark_s', 'hf', 3, -1),), face='w'), 160),
                        (p(lean=10, hf=(7, 0), face='w'), 100)],
                       cat='pair', desc='Fist bump. Ends every bout.', hit_frame=2)
    # V9: a real hop (the engine lifts it along `air`), not a 2 px rise inside the cell; the slap meets at the apex
    mv['highfive'] = M([(p(dy=3, lean=10, sq=0.92, hf=(5, 2), ff=(7, 0), fb=(-6, 0)), 100),
                        (p(dy=-1, lean=4, sq=1.08, hf=(9, -10), open_f=True, ff=(6, 3), fb=(-5, 2), ang_f=20, ang_b=20, face='w'), 70),
                        (p(dy=-1, lean=2, hf=(11, -11), open_f=True, ff=(6, 5), fb=(-4, 4), face='w', fx=(('spark', 'hf', 3, -2),)), 180),
                        (p(dy=5, lean=8, sq=0.88, head=(2, 1), hf=(8, -8), open_f=True, face='w', fx=land_dust()), 90),
                        (p(dy=2, lean=6, sq=1.02, hf=(7, -2), face='w'), 90), (S0, 100)],
                       cat='pair', desc='Jump high-five. Both finished at the same time.', hit_frame=2,
                       air_spec=[(1, 0.2, 0), (2, 0, 10, 'o'), (2, 0.35, 11, 'h'), (3, 0, 0, 'i')])
    mv['wave'] = M([(p(lean=2, hf=(7, -11), open_f=True, face='w'), 120), (p(lean=2, hf=(9, -12), open_f=True, face='w'), 120),
                    (p(lean=2, hf=(7, -11), open_f=True, face='w'), 120), (p(lean=2, hf=(5, -12), open_f=True, face='w'), 120)],
                   cat='emote', desc='Greeting wave.')
    mv['thumbs_up'] = M([(p(lean=4, hf=(6, -1), face='n'), 100), (p(lean=4, hf=(9, -3), face='w', fx=(('thumb', 'hf', 0, -2),)), 160),
                         (p(lean=4, hf=(9, -3), face='b', fx=(('thumb', 'hf', 0, -2),)), 120),
                         (p(lean=4, hf=(9, -3), face='w', fx=(('thumb', 'hf', 0, -2),)), 220)], cat='emote', desc='Approved.')
    mv['facepalm'] = M([(p(lean=8, hf=(6, -3), face='n'), 100), (p(lean=8, head=(1, 2), hf=(2, -9), face='b'), 120),
                        (p(lean=8, head=(1, 2), hf=(2, -9), face='b', fx=(('sweat', 'head', 7, -4),)), 140),
                        (p(lean=8, head=(1, 2), hf=(2, -9), face='b', fx=(('sweat', 'head', 7, -2),)), 200)],
                       cat='emote', desc='Something broke.')
    mv['shrug'] = M([(p(lean=2, dy=2, hf=(6, 3), hb=(2, 3), eb_f='up', eb_b='up', head=(0, 1), tilt=-6, face='n'), 120),
                     (p(lean=2, dy=1, hf=(6, 2), hb=(2, 2), eb_f='up', eb_b='up', head=(0, 0), tilt=-6, face='n', fx=(('qmark', 'head', 6, -13),)), 160),
                     (p(lean=2, dy=2, hf=(6, 3), hb=(2, 3), eb_f='up', eb_b='up', head=(0, 1), tilt=-6, face='n', fx=(('qmark', 'head', 6, -13),)), 160),
                     (S0, 100)], cat='emote', desc='Unsure.')
    mv['work'] = M([(p(dy=2, lean=14, hf=(11, -2), hb=(3, 0), ff=(8, 0), fb=(-6, 0), fist_f=4, smear_f=(6, 0)), 80),
                    (p(dy=1, lean=10, hf=(6, 0), hb=(5, -1)), 100),
                    (p(dy=2, lean=14, hf=(5, 0), hb=(11, -2), ff=(7, 0), fb=(-7, 0), fist_b=4, smear_b=(5, -1)), 80),
                    (p(dy=1, lean=10, hf=(7, -1), hb=(5, 0), ff=(8, 2), fb=(-6, 0)), 100),
                    (p(dy=2, lean=14, hf=(11, -2), hb=(3, 0), fist_f=4, smear_f=(7, -1)), 80),
                    (p(dy=1, lean=10, hf=(6, 0), hb=(5, -1)), 100)],
                   loop=True, cat='state', desc='Shadowboxing: the fighter is working.')
    mv['type'] = M([(p(dy=2, lean=14, head=(2, 2), hf=(9, 2), hb=(7, 3), face='f'), 90), (p(dy=2, lean=14, head=(2, 2), hf=(9, 4), hb=(7, 1), face='f'), 90),
                    (p(dy=2, lean=14, head=(2, 2), hf=(9, 2), hb=(7, 3), face='f'), 90), (p(dy=2, lean=14, head=(2, 3), hf=(9, 3), hb=(7, 4), face='f'), 90),
                    (p(dy=2, lean=14, head=(2, 2), hf=(9, 4), hb=(7, 1), face='f'), 90), (p(dy=2, lean=14, head=(2, 2), hf=(9, 2), hb=(7, 3), face='f'), 90)],
                   loop=True, cat='state', desc='Typing on an air keyboard. Used for long edit streaks.')
    mv['review'] = M([(p(dy=1, lean=16, head=(2, 1), hf=(3, -9), hb=(10, -3), doc='hb', face='f'), 120),
                      (p(dy=1, lean=16, head=(2, 2), hf=(3, -9), hb=(10, -3), doc='hb', face='f'), 120),
                      (p(dy=1, lean=16, head=(2, 1), hf=(3, -9), hb=(10, -3), doc='hb', face='n'), 120),
                      (p(dy=1, lean=16, head=(2, 2), hf=(3, -9), hb=(10, -2), doc='hb', face='f'), 120),
                      (p(dy=1, lean=14, head=(1, 1), hf=(4, -9), hb=(10, -3), doc='hb', face='g'), 120),
                      (p(dy=1, lean=16, head=(2, 1), hf=(3, -9), hb=(10, -3), doc='hb', face='f'), 120)],
                     loop=True, cat='state', desc='Strokes chin, reads the diff. Played when visiting a finished partner.')
    mv['wait'] = M([(p(dy=1, lean=4, hf=(-1, 9), hb=(-2, 9), eb_f='fwd', eb_b='back', face='n'), 150),
                    (p(dy=1, lean=4, hf=(-1, 9), hb=(-2, 9), eb_f='fwd', eb_b='back', ff=(7, 3), face='n'), 150),
                    (p(dy=1, lean=4, hf=(-1, 9), hb=(-2, 9), eb_f='fwd', eb_b='back', face='b'), 150),
                    (p(dy=1, lean=4, head=(0, 0), hf=(-1, 9), hb=(-2, 9), eb_f='fwd', eb_b='back', ff=(7, 3), face='n'), 150)],
                   loop=True, cat='state', desc='Foot tap, hands on hips: waiting for input or approval.')
    sdy = body.sit_dy                              # keep the hips the same height above the floor for every body
    sit = dict(dy=sdy, lean=24, head=(3, 3), tilt=10, hf=(8, 10), hb=(6, 11), ff=(8, 0), fb=(5, 0), kb_f='up', kb_b='up', face='z')
    mv['sleep'] = M([(p(**sit, chest=1.0, fx=(('zzz', 'head', 8, -9, 0),)), 600), (p(**{**sit, 'dy': sdy - 1, 'lean': 26}, chest=1.05, fx=(('zzz', 'head', 9, -11, 1),)), 600),
                     (p(**sit, chest=1.0, fx=(('zzz', 'head', 10, -13, 0),)), 600), (p(**{**sit, 'dy': sdy - 1, 'lean': 26}, chest=1.05, fx=(('zzz', 'head', 8, -10, 1),)), 600)],
                    loop=True, cat='state', desc='Sitting nap. No session in 30 minutes.')
    mv['wake'] = M([(p(**sit), 200), (p(dy=8, lean=10, sq=0.95, hf=(6, -4), hb=(3, -5), face='z'), 160),
                    (p(dy=3, lean=0, sq=1.08, chest=1.06, hf=(6, -12), hb=(3, -13), face='o', eb_f='up', eb_b='up'), 200), (S0, 140)],
                   cat='state', desc='Stretch and yawn.')
    mv['powerup'] = M([(p(dy=5 + (i % 2), lean=8, chest=1.0 + 0.04 * i, sq=0.97, hf=(4, 5), hb=(2, 5), fist_f=4, fist_b=4, face='f', aura=i + 1,
                          fx=(('charge', 'hf', 2 + i, -4 - i),)), 80) for i in range(5)],
                      loop=True, loop_range=(1, 4), cat='state', desc='Charging up. Context past 70%.')
    mv['rage'] = M([(p(dy=1 + (i % 2), lean=12, chest=1.06 + 0.03 * (i % 2), face='f', aura=i + 5, hf=(8, -2), hb=(5, 0)), 80) for i in range(4)],
                   loop=True, cat='state', desc='Aura on. Context past 85%.')

    # ------------------------------------------------------------------ supers
    name = ch.signature['super']
    tpl, desc, opts = ch.sig_moves[name]
    mv[name] = TEMPLATES[tpl](desc, **opts)

    # ------------------------------------------------------------------ paired moves
    mv['handoff_give'] = M([(p(lean=8, hf=(5, 0), hb=(5, 1), face='n'), 100),
                            (p(lean=10, hf=(11, -2), doc='hf', face='n'), 120),
                            (p(lean=10, hf=(11, -2), doc='hf', face='n'), 300),
                            (p(lean=10, hf=(11, -2), face='n'), 100),
                            (p(lean=8, hf=(7, 0), face='w'), 120), (S0, 100)],
                           cat='pair', desc='Holds out a finished diff. The writer hands work to the reviewer.', release_frame=3)
    mv['handoff_take'] = M([(S0, 100), (p(lean=10, hf=(10, -1), open_f=True, face='n'), 120),
                            (p(lean=12, hf=(11, -2), open_f=True, doc='hf', face='n'), 120),
                            (p(lean=8, hf=(6, -3), doc='hf', face='f'), 140),
                            (p(lean=14, head=(2, 1), hf=(5, -5), hb=(8, -3), doc='hf', face='f'), 200), (S0, 100)],
                           cat='pair', desc='Reaches out and takes the diff.', grab_frame=2)
    mv['console'] = M([(p(lean=8, hf=(10, -2), face='n'), 160), (p(lean=8, hf=(11, -3), face='n'), 160),
                       (p(lean=8, hf=(10, -2), face='n'), 160), (p(lean=8, hf=(11, -3), face='w'), 160)],
                      cat='pair', desc='Pats the other fighter on the shoulder after a KO.')

    # ------------------------------------------------------------------ V4 ultimate (+ support), then the V7 weapon moves
    import ultimates
    ultimates.add_ultimate(mv, ch)
    mv.update(weapon_moves(ch))                    # V7 rows come after every older row, so no row index ever moves
    stance = mv['idle']['frames'][0][0]
    for m in mv.values():                          # V9: a one-shot that goes back to idle ends on idle's own first pose
        settle_to_stance(m, stance)
    pin_weapons(body, mv['sleep'])                 # V9: a weapon lying by a sleeper does not flip with each breath
    st_a = _wangle(body, stance)
    if st_a is not None and mv['turn']['frames'][0][0].wa is None:     # V9: a pivot keeps the weapon where the stance holds it
        ps0, ms0 = mv['turn']['frames'][0]
        mv['turn']['frames'][0] = (_nearest_fit(body, replace(ps0, wa=round(st_a, 1))), ms0)
    for m in mv.values():                          # V8: airborne rows get their `air` keys on the final timings
        if 'air_spec' in m:
            resolve_air(body, m)
        elif not m['loop']:
            inbetween_weapons(body, m)             # V9: ground rows: a weapon never snaps between two held keys
    for m in mv.values():                          # the fit passes may pull the hands in on that last key: put the
        if m.pop('_stance_end', False):            # stance back exactly as idle draws it, or the step into idle pops
            m['frames'][-1] = (stance, m['frames'][-1][1])
    for name_, m in mv.items():                    # V9: the recovery turns toward the stance; a far end gets a settle key
        if name_ not in HELD_LAST:
            settle_frame(body, m, stance)
    return annotate_contact(ch, mv)


# ---------------------------------------------------------------------- V9: no pops (docs/ANIMATION-NOTES.md section 11)
def settle_to_stance(mv, stance):
    """A one-shot whose last key is the neutral pose S0 ends on the character's idle stance instead (its first idle key),
    so the step into idle after it is not a pop: a kanabo dragged low, a katana at the throat, a spear held level all came
    back up to the rig's rest angle for one frame and then snapped down into the stance."""
    if mv['loop'] or not mv['frames']:
        return mv
    ps, ms = mv['frames'][-1]
    if ps == S0:
        mv['frames'][-1] = (stance, ms)
        mv['_stance_end'] = True
    return mv


HELD_LAST = ('victory', 'victory2')      # the engine holds these on their last frame (the winner's pose): never add a settle
SETTLE_TIP = 14.0             # design px: a weapon tip that would jump further than this into idle gets a settle key
SETTLE_CATS = ('strike', 'special', 'super', 'ultimate', 'defense', 'emote', 'pair', 'throw', 'reaction', 'state')


def _wangle(body, ps, side='f'):
    w = rig.skeleton(body, ps)['w' + side]
    return None if w is None else w['a']


def settle_frame(body, mv, stance):
    """A one-shot that ends far from the stance (a wave with the weapon overhead, a taunt's closing pose) gets one settle
    key half way back to the stance before the engine cuts to idle, with the weapon aimed half way along the shortest arc,
    so the step into idle is two small moves instead of one pop.  Only rows that end standing (not lying, not in the
    air), with a free column, and only where the weapon tip would really jump."""
    fr = mv['frames']
    if mv['loop'] or len(fr) < 2 or mv.get('cat') not in SETTLE_CATS:
        return mv
    if mv.get('air_spec') and mv['air_spec'][-1][2] > 0:
        return mv
    n = len(fr)
    ends_on_stance = fr[-1][0] == stance
    r = n - 2 if ends_on_stance else n - 1         # the recovery key: the last one before the stance
    rec = fr[r][0] if r >= 1 else None
    if rec is not None and rec.lean >= -45 and r not in (mv.get('smear_frames') or ()) and r != mv.get('hit_frame'):
        kw = {}                                    # the recovery key turns the weapon half way toward the stance
        for side, field_ in (('f', 'wa'), ('b', 'wb')):
            al, ast = _wangle(body, rec, side), _wangle(body, stance, side)
            ap = _wangle(body, fr[r - 1][0], side)
            if al is None or ast is None or ap is None:
                continue
            if abs(_angdiff(al, ap)) > INBETWEEN_DEG or (abs(_angdiff(ast, al)) > INBETWEEN_DEG and (ends_on_stance or n >= 8)):
                if getattr(rec, field_) is None or ends_on_stance or n >= 8:
                    kw[field_] = round(ap + _angdiff(ast, ap) * 0.5, 1)
        if kw:
            fr[r] = (_nearest_fit(body, replace(rec, **kw), _drawn(body, fr[r - 1][0])), fr[r][1])
    last = fr[-1][0]
    if n >= 8 or ends_on_stance or last.lean < -45 or last.lean > 60:
        return mv
    ta, tb = _tip_of(body, last), _tip_of(body, stance)
    if ta is None or tb is None or math.hypot(tb[0] - ta[0], tb[1] - ta[1]) < SETTLE_TIP:
        return mv
    import build_fighters as _BF                   # lerp_pose lives with the afterimage code
    mid = _BF.lerp_pose(last, stance, 0.5)
    kw = {}
    for side, field_ in (('f', 'wa'), ('b', 'wb')):
        a0, a1 = _wangle(body, last, side), _wangle(body, stance, side)
        if a0 is not None and a1 is not None:
            kw[field_] = round(a0 + _angdiff(a1, a0) * 0.5, 1)
    mid = replace(mid, face=last.face, fist_f=last.fist_f, fist_b=last.fist_b, open_f=False, free_b=last.free_b, **kw)
    fr.append((mid, 100 if fr[-1][1] == 90 else 90))        # never the same duration as the key before it
    mv['frames'] = fr
    return mv


def _tip_of(body, ps):
    w = rig.skeleton(body, ps)['wf']
    return None if w is None else rig.weapon_point(w, 1.0)


def pin_weapons(body, mv):
    """Every key that leaves the weapon to the rig gets the first key's angle (a weapon lying still)."""
    a0, b0 = _wangle(body, mv['frames'][0][0], 'f'), _wangle(body, mv['frames'][0][0], 'b')
    out = []
    for ps, ms in mv['frames']:
        kw = {}
        if ps.wa is None and a0 is not None:
            kw['wa'] = round(a0, 1)
        if ps.wb is None and b0 is not None:
            kw['wb'] = round(b0, 1)
        out.append((replace(ps, **kw) if kw else ps, ms))
    mv['frames'] = _fit_chain(body, out)           # a key where that angle does not fit takes the nearest one that does
    return mv


INBETWEEN_DEG = 60.0          # a weapon that turns more than this between two drawn keys is in-betweened


def inbetween_weapons(body, mv):
    """Ground rows: a run of keys that leaves the weapon to the rig (wa / wb None) between two keys, where the weapon would
    turn more than INBETWEEN_DEG in one step (a follow-through pointing down, then the recovery with the blade snapped
    up to its rest angle), is re-aimed along the shortest arc between the keys either side of the run, spaced by time.
    Smear frames, the first and the last key stay exactly as authored (the last one meets idle)."""
    frames = mv['frames']
    n = len(frames)
    if n < 3:
        return mv
    smear = set(mv.get('smear_frames') or [])
    ms = [m for _, m in frames]
    mid = [sum(ms[:i]) + ms[i] / 2.0 for i in range(n)]
    for side, field_, spec in (('f', 'wa', body.weapon), ('b', 'wb', body.weapon_b)):
        if spec is None:
            continue
        ang = []
        for ps, _ in frames:
            w = rig.skeleton(body, ps)['w' + side]
            ang.append(None if w is None else w['a'])
        i = 1
        while i < n - 1:
            ps = frames[i][0]
            if getattr(ps, field_) is not None or i in smear or ang[i] is None:
                i += 1
                continue
            j = i
            while j + 1 < n - 1 and getattr(frames[j + 1][0], field_) is None and (j + 1) not in smear and ang[j + 1] is not None:
                j += 1
            a0, a1 = ang[i - 1], ang[j + 1]
            if a0 is None or a1 is None:
                i = j + 1
                continue
            chain = [a0] + ang[i:j + 1] + [a1]
            if max(abs(_angdiff(b, a)) for a, b in zip(chain, chain[1:])) > INBETWEEN_DEG:
                span = _angdiff(a1, a0)
                t0, t1 = mid[i - 1], mid[j + 1]
                for k in range(i, j + 1):
                    u = (mid[k] - t0) / max(1e-6, t1 - t0)
                    frames[k] = (replace(frames[k][0], **{field_: round(a0 + span * u, 1)}), frames[k][1])
            i = j + 1
    mv['frames'] = frames
    fit_weapons(body, mv)
    mv['frames'] = _fit_chain(body, mv['frames'])
    return mv


# ====================================================================== V7: weapon move families
# docs/ANIMATION-NOTES.md section 8.  Every fighter fights like its weapon: a family of rig-keyed weapon moves plus the
# shared move TYPES the choreographer uses (air juggle, throw, riposte, dash-through, guard break, a taunt variant).
# The engine never reads these names: each row carries `type` (and `family`) in anim.json and choreo.py picks by type.
FAMILY = {'katana': 'blade', 'energy': 'blade', 'short': 'dual', 'tonfa': 'dual', 'spear': 'polearm', 'staff': 'staff',
          'kunai': 'chain', 'bow': 'bow', 'fan': 'fans', 'chakram': 'fans', 'greatsword': 'heavy', 'axe': 'heavy',
          'kanabo': 'heavy'}


def family_of(ch):
    return ch.style.get('family') or FAMILY[ch.body.weapon.kind]


def W(frames, cat='strike', desc='', **meta):
    """A V7 move: like M, plus `type` / `input` / `family` metadata the engine and the move list read."""
    return M(frames, cat=cat, desc=desc, **meta)


import rig  # noqa: E402  (V7: the weapon fit pass reads the skeleton)


# ---------------------------------------------------------------- blade (katana, energy katana)
def blade_iai(desc):
    """Iai draw-slash: crouch with the blade low behind the hip, hold the tension, ONE flash cut with a lunge, a long
    frozen follow-through with the blade level, a chiburi flick, back to guard."""
    return W([
        (p(dy=4, lean=16, sq=0.95, turn=0.85, hf=(-1, 7), wa=160, ff=(9, 0), fb=(-9, 0), face='g'), 130),
        (p(dy=6, lean=22, sq=0.92, turn=0.8, hf=(-2, 8), wa=168, ff=(10, 0), fb=(-10, 0), face='g'), 170),
        (p(dy=4, lean=26, hf=(9, 1), wa=6, ff=(14, 0), fb=(-10, 0), dx=6, face='o', smear_f=(-2, 8)), 40),
        (p(dy=4, lean=28, hf=(9, 1), wa=4, ff=(14, 0), fb=(-10, 0), face='o', fx=(('spark', 'hf', 3, 0),)), 150),
        (p(dy=4, lean=26, hf=(9, 0), wa=-2, ff=(14, 0), fb=(-10, 0), face='g'), 280),
        (p(dy=3, lean=16, hf=(8, 4), wa=50, ff=(11, 0), fb=(-9, 0), face='g'), 110),
        (p(dy=2, lean=12, hf=(8, 3), wa=-40, ff=(9, 0), fb=(-8, 0)), 90),
        (S0, 120)],
        desc=desc, hit_frame=3, power=2, type='string', input='down, fwd + Strike')


def blade_cross_cut(desc):
    """Two strokes that make an X: a falling diagonal, a short check, then the rising back-cut that lands."""
    return W([
        (p(dy=2, lean=-6, chest=1.04, turn=0.85, hf=(-2, -8), eb_f='up', wa=-150, ff=(8, 0), fb=(-8, 0), face='g'), 130),
        (p(dy=3, lean=-10, sq=0.96, turn=0.85, hf=(-3, -9), eb_f='up', wa=-158, ff=(8, 0), fb=(-9, 0), face='g'), 90),
        (p(dy=3, lean=24, hf=(11, 4), wa=44, ff=(12, 0), fb=(-9, 0), dx=4, face='o', smear_f=(-3, -9)), 40),
        (p(dy=4, lean=26, hf=(10, 6), wa=60, ff=(12, 0), fb=(-9, 0), face='o'), 70),
        (p(dy=1, lean=10, hf=(7, -8), wa=-70, ff=(12, 0), fb=(-9, 0), dx=2, face='o', smear_f=(10, 6)), 40),
        (p(dy=1, lean=8, hf=(7, -8), wa=-74, ff=(12, 1), fb=(-9, 0), face='o', fx=(('spark', 'hf', 0, -3),)), 170),
        (p(dy=1, lean=4, hf=(6, -8), wa=-84, ff=(11, 1), fb=(-9, 0), face='g'), 250),
        (p(dy=2, lean=10, hf=(8, 0), ff=(9, 0), fb=(-8, 0)), 110)],
        desc=desc, hit_frame=5, power=3, type='string', input='fwd, fwd + Strike')


def blade_thrust(desc):
    """Riposte: the fast straight stab that answers a parry.  Short draw-back, one stab with speed lines, snap back."""
    return W([
        (p(dy=4, lean=-6, sq=0.95, turn=0.8, hf=(-5, 2), wa=-12, ff=(8, 0), fb=(-9, 0), face='g'), 90),
        (p(dy=3, lean=28, hf=(10, 0), wa=-2, ff=(14, 0), fb=(-9, 0), dx=6, face='o', smear_f=(-5, 2)), 40),
        (p(dy=3, lean=30, hf=(10, 0), wa=-2, ff=(14, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 4, 0),)), 140),
        (p(dy=3, lean=28, hf=(10, 1), wa=2, ff=(14, 0), fb=(-9, 0), face='g'), 190),
        (p(dy=2, lean=14, hf=(8, 2), ff=(10, 0), fb=(-8, 0)), 100),
        (S0, 90)],
        desc=desc, hit_frame=2, power=2, type='riposte', input='(after a parry) Strike')


# ---------------------------------------------------------------- shared move types (every family, weapon angles adapt)
def t_air_slash(desc):
    """Air juggle: load, push off after the launched opponent, cock the weapon back over the shoulder on the rise with the
    knees up, one slash at the top (it meets the defender hanging at 21), follow through as the body falls with the legs
    reaching down, land squashed.  V8: the leap is `air`; hit_frame 5."""
    return W([
        (p(dy=3, lean=12, sq=0.93, hf=(4, 3), hb=(1, 4), ff=(8, 0), fb=(-7, 0)), 70),
        (p(dy=6, lean=18, sq=0.87, head=(2, 1), hf=(0, 6), hb=(-3, 5), wa=-70, ff=(8, 0), fb=(-7, 0), face='g'), 100),
        (p(dy=-1, lean=4, sq=1.10, hf=(5, -4), hb=(2, -4), eb_f='up', wa=-105, ff=(5, 0), fb=(-5, 1), ang_f=22, ang_b=22, face='g',
           fx=push_dust()), 50),
        (p(dy=-1, lean=-6, sq=1.03, hf=(-3, -6), hb=(5, -2), eb_f='up', wa=-155, ff=(5, 7), fb=(-3, 6), face='g'), 170),
        (p(dy=-1, lean=24, hf=(11, 3), wa=36, hb=(-2, 1), ff=(7, 6), fb=(-5, 5), face='o', smear_f=(-3, -6)), 40),
        (p(dy=-1, lean=26, hf=(11, 4), wa=42, hb=(-3, 1), ff=(7, 5), fb=(-5, 4), face='o', fx=(('spark', 'hf', 3, 0),)), 150),
        (p(dy=0, lean=18, sq=1.04, hf=(9, 7), wa=62, hb=(-2, -4), ff=(7, 2), fb=(-5, 1), face='g'), 110),
        (p(dy=6, lean=16, sq=0.86, head=(2, 2), hf=(8, 5), wa=52, hb=(2, 3), ff=(9, 0), fb=(-8, 0), fx=land_dust()), 140)],
        desc=desc, hit_frame=5, power=2, type='air', input='up + Strike (air)',
        air_spec=[(3, 0, 0), (4, 0.25, 22, 'o'), (5, 0, 21, 'h'), (5, 0.733, 20, 'h'), (7, 0, 0, 'i')])


def t_spike(desc):
    """Air spike: load, push off, rise with the weapon raised in both hands and hover at the top (held), drive it DOWN through
    the airborne opponent on the way down (the contact stops the drop: hitstop), drop to the floor and land with a ground
    shock, recover.  V8: the leap is `air`; hit_frame 5, the landing shock is frame 6."""
    return W([
        (p(dy=3, lean=12, sq=0.93, hf=(4, 4), hb=(1, 4), wa=-80, ff=(8, 0), fb=(-7, 0)), 80),
        (p(dy=6, lean=18, sq=0.87, head=(2, 1), hf=(2, 6), hb=(-2, 5), wa=-95, ff=(8, 0), fb=(-7, 0), face='g'), 110),
        (p(dy=-1, lean=2, sq=1.10, hf=(4, -6), hb=(2, -5), eb_f='up', eb_b='up', wa=-125, ff=(5, 0), fb=(-5, 1),
           ang_f=22, ang_b=22, fx=push_dust()), 60),
        (p(dy=-1, lean=-10, sq=1.02, chest=1.04, hf=(1, -8), hb=(0, -7), eb_f='up', eb_b='up', wa=-150, ff=(5, 8), fb=(-3, 7),
           face='o'), 190),
        (p(dy=-1, lean=36, hf=(10, 7), wa=72, hb=(6, 5), ff=(6, 5), fb=(-4, 4), face='o', smear_f=(1, -8)), 40),
        (p(dy=-1, lean=40, hf=(10, 8), wa=80, hb=(7, 6), ff=(6, 3), fb=(-4, 2), face='o', fx=(('spark', 'hf', 2, 2),)), 140),
        (p(dy=7, lean=34, sq=0.86, head=(2, 2), hf=(9, 8), wa=82, hb=(7, 7), ff=(9, 0), fb=(-8, 0), face='o',
           fx=(('shock', 'abs', 40, 56), ('dust', 'ff', 4, -1), ('dust', 'fb', -5, -1))), 230),
        (p(dy=2, lean=14, sq=1.02, hf=(8, 4), wa=40, ff=(8, 0), fb=(-7, 0)), 120)],
        desc=desc, hit_frame=5, power=3, type='spike', input='(air) down + Strike', shake=dict(frames=3, amp=1),
        air_spec=[(3, 0, 0), (3, 0.842, 22, 'o'), (5, 0, 19.5, 'h'), (6, 0, 0, 'i')])


def t_dash_slash(desc):
    """Dash-through: coil, burst THROUGH the opponent with an afterimage trail, skid to a stop on the far side with the
    weapon out and the back turned; the cut registers on the frozen pose."""
    return W([
        (p(dy=5, lean=20, sq=0.92, turn=0.85, hf=(-1, 6), wa=158, ff=(9, 0), fb=(-9, 0), face='g'), 130),
        (p(dy=6, lean=24, sq=0.90, turn=0.8, hf=(-2, 7), wa=165, ff=(10, 0), fb=(-10, 0), face='g'), 110),
        (p(dx=22, dy=2, lean=34, sq=1.06, hf=(10, 1), wa=4, ff=(12, 3), fb=(-9, 2), ghost=(7, 14), face='o', smear_f=(-2, 7),
           fx=(('speedlines', 'hip', -10, -6),)), 40),
        (p(dx=22, dy=3, lean=30, hf=(11, 2), wa=8, ff=(13, 1), fb=(-10, 1), ghost=(8,), face='o', fx=(('speedlines', 'hip', -10, -6),)), 60),
        (p(dx=8, dy=5, lean=14, sq=0.92, hf=(10, 3), wa=14, ff=(13, 0), fb=(-6, 0), face='g', fx=(('dust', 'ff', 4, -1), ('dust', 'fb', -4, -1))), 90),
        (p(dy=4, lean=12, sq=0.94, hf=(10, 3), wa=12, ff=(12, 0), fb=(-8, 0), face='g'), 320),
        (p(dy=3, lean=10, hf=(8, 4), wa=50, ff=(10, 0), fb=(-8, 0)), 120),
        (S0, 100)],
        desc=desc, hit_frame=5, power=2, type='through', input='fwd, fwd + Strike (dash)')


def t_guard_break(desc):
    """Guard break: a long, heavy wind-up (three held keys), then the pommel drives into the raised guard."""
    return W([
        (p(dy=3, lean=-4, turn=0.8, hf=(-2, 1), wa=180, ff=(8, 0), fb=(-8, 0), face='g'), 140),
        (p(dy=5, lean=-10, sq=0.94, chest=1.05, turn=0.7, hf=(-5, 1), wa=180, ff=(9, 0), fb=(-9, 0), face='o'), 160),
        (p(dy=6, lean=-14, sq=0.92, chest=1.07, turn=0.65, hf=(-6, 2), wa=178, ff=(9, 0), fb=(-10, 0), face='o'), 190),
        (p(dy=3, lean=30, hf=(10, -1), wa=176, ff=(14, 0), fb=(-9, 0), dx=7, face='o', smear_b=(-6, 2), fx=(('speedlines', 'hip', -10, -6),)), 40),
        (p(dy=3, lean=32, hf=(10, -1), wa=178, ff=(14, 0), fb=(-9, 0), face='o', fx=(('block', 'hf', 3, 0), ('spark', 'hf', 4, -1))), 180),
        (p(dy=3, lean=30, hf=(10, 0), wa=176, ff=(14, 0), fb=(-9, 0), face='g'), 240),
        (p(dy=2, lean=14, hf=(8, 3), wa=60, ff=(10, 0), fb=(-8, 0)), 110),
        (S0, 100)],
        desc=desc, hit_frame=4, power=2, type='guard_break', input='back, fwd + Strike (hold)')


THROW_MS = (110, 120, 150, 170, 40, 210, 120, 100)     # attacker and defender share this clock (grab 1, release 4, slam 5)


def t_throw(desc):
    """Throw: reach in, GRAB (grab_frame), hoist the opponent overhead, slam them down in front (hit_frame).  The
    defender's `thrown` row is keyed to the same clock (THROW_MS), so the two stay in sync whoever throws whom."""
    ms = THROW_MS
    return W([
        (p(dy=3, lean=20, hf=(11, 0), wa=130, hb=(3, 4), ff=(12, 0), fb=(-8, 0), face='g'), ms[0]),
        (p(dy=3, lean=22, hf=(12, 0), wa=128, hb=(3, 4), ff=(12, 0), fb=(-8, 0), face='o', fx=(('spark_s', 'hf', 3, 0),)), ms[1]),
        (p(dy=5, lean=-2, sq=0.93, hf=(6, -8), eb_f='up', wa=-150, hb=(2, 3), ff=(9, 0), fb=(-9, 0), face='o'), ms[2]),
        (p(dy=2, lean=-14, sq=1.05, chest=1.06, hf=(2, -12), eb_f='up', wa=-170, hb=(0, 2), ff=(8, 0), fb=(-9, 0), face='o'), ms[3]),
        (p(dy=5, lean=36, hf=(12, 6), wa=80, hb=(4, 4), ff=(12, 0), fb=(-9, 0), dx=3, face='o', smear_f=(2, -12)), ms[4]),
        (p(dy=6, lean=40, sq=0.92, hf=(12, 7), wa=86, hb=(4, 5), ff=(12, 0), fb=(-9, 0), face='o', fx=(('dust', 'ff', 8, -1),)), ms[5]),
        (p(dy=3, lean=16, hf=(8, 3), wa=40, ff=(10, 0), fb=(-8, 0), face='g'), ms[6]),
        (S0, ms[7])],
        cat='throw', desc=desc, hit_frame=5, grab_frame=1, release_frame=4, power=2, type='throw', input='close: fwd + Grab')


def t_taunt_blade(desc):
    """Blade taunt: twirl the blade once round the wrist, flick it, sheathe it at the hip with a head tilt."""
    return W([
        (p(dy=2, lean=8, hf=(8, 1), wa=0, face='g'), 140),
        (p(dy=2, lean=8, hf=(8, 1), wa=80, face='g'), 70),
        (p(dy=2, lean=8, hf=(8, 1), wa=170, face='g'), 60),
        (p(dy=2, lean=8, hf=(8, 1), wa=-100, face='g'), 70),
        (p(dy=2, lean=10, hf=(9, 3), wa=40, face='w', fx=(('spark_s', 'hf', 3, 1),)), 160),
        (p(dy=3, lean=6, turn=0.85, hf=(-1, 7), wa=165, head=(2, 0), tilt=-6, face='w'), 340),
        (p(dy=2, lean=6, turn=0.9, hf=(0, 6), wa=160, face='w'), 140),
        (S0, 120)],
        cat='emote', desc=desc, type='taunt', input='Taunt')


# ---------------------------------------------------------------- shared reactions (defender)
# ---------------------------------------------------------------- dual (twin short swords, twin tonfa)
def dual_flurry(desc):
    """Flurry: a coiled guard, then three alternating cuts (lead, rear, lead rising), each one smear and a short check;
    the third lands and is held."""
    return W([
        (p(dy=4, lean=6, sq=0.95, hf=(1, -5), wa=-120, hb=(-2, 3), wb=160, ff=(9, 0), fb=(-8, 0), face='g'), 120),
        (p(dy=3, lean=22, hf=(10, 3), wa=30, hb=(-1, 3), wb=150, ff=(12, 0), fb=(-8, 0), dx=3, face='o', smear_f=(1, -5)), 40),
        (p(dy=3, lean=24, hf=(9, 5), wa=50, hb=(-1, 3), wb=150, ff=(12, 0), fb=(-8, 0), face='o'), 70),
        (p(dy=3, lean=24, hf=(3, 5), wa=90, hb=(11, -1), wb=-10, ff=(12, 0), fb=(-8, 0), dx=2, face='o', smear_b=(-1, 3)), 40),
        (p(dy=3, lean=24, hf=(3, 5), wa=95, hb=(10, 0), wb=0, ff=(12, 0), fb=(-8, 0), face='o'), 80),
        (p(dy=2, lean=14, hf=(8, -8), wa=-70, hb=(4, 3), wb=40, ff=(12, 0), fb=(-8, 0), dx=2, face='o', smear_f=(3, 5)), 40),
        (p(dy=2, lean=12, hf=(8, -9), wa=-76, hb=(4, 3), wb=40, ff=(12, 1), fb=(-8, 0), face='o', fx=(('spark', 'hf', 1, -3),)), 170),
        (p(dy=2, lean=10, hf=(7, -8), wa=-84, hb=(3, 4), wb=50, ff=(10, 0), fb=(-8, 0), face='g'), 220)],
        desc=desc, hit_frame=6, power=2, type='string', input='Strike, Strike, Strike')


def dual_scissor(desc):
    """Scissor cut: both blades thrown wide (one high back, one low back) and held, then both snap shut across the
    opponent in one frame; the X is held."""
    return W([
        (p(dy=3, lean=4, chest=1.05, hf=(-2, -7), eb_f='up', wa=-130, hb=(-4, 6), eb_b='back', wb=150, ff=(9, 0), fb=(-8, 0), face='g'), 130),
        (p(dy=5, lean=0, sq=0.94, chest=1.08, hf=(-3, -8), eb_f='up', wa=-140, hb=(-5, 7), eb_b='back', wb=160, ff=(9, 0), fb=(-9, 0), face='o'), 170),
        (p(dy=3, lean=26, hf=(10, 3), wa=25, hb=(10, -1), wb=-25, ff=(13, 0), fb=(-9, 0), dx=5, face='o', smear_f=(-3, -8), smear_b=(-5, 7)), 40),
        (p(dy=3, lean=28, hf=(10, 3), wa=28, hb=(10, -1), wb=-28, ff=(13, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 3, -1),)), 170),
        (p(dy=3, lean=28, hf=(9, 4), wa=34, hb=(9, -2), wb=-34, ff=(13, 0), fb=(-9, 0), face='g'), 250),
        (p(dy=2, lean=14, hf=(8, 1), wa=-40, hb=(3, 4), wb=40, ff=(10, 0), fb=(-8, 0)), 110),
        (S0, 100)],
        desc=desc, hit_frame=3, power=3, type='string', input='back, fwd + Strike')


def dual_dance(desc):
    """Blade dance: a full turn with both weapons held out like a spinning top (the back shows on the wind-up), the lead
    weapon sweeps the opponent and the spin stops in a low, wide finish."""
    return W([
        (p(dy=3, lean=12, sq=0.95, turn=0.85, hf=(5, 2), wa=-30, hb=(2, 3), wb=160, ff=(8, 0), fb=(-8, 0), face='g'), 130),
        (p(dy=2, lean=0, turn=0.55, face='back', hf=(-8, -1), wa=180, hb=(9, -1), wb=0, ff=(4, 0), fb=(-4, 0)), 80),
        (p(dy=2, lean=4, turn=0.35, face='back', hf=(-2, -3), wa=-120, hb=(4, -3), wb=-60, ff=(3, 1), fb=(-3, 0)), 60),
        (p(dy=3, lean=20, turn=0.8, hf=(11, 1), wa=8, hb=(-8, 1), wb=172, ff=(12, 0), fb=(-9, 0), dx=4, face='o', smear_f=(-2, -3)), 40),
        (p(dy=3, lean=22, turn=0.9, hf=(11, 2), wa=10, hb=(-8, 2), wb=170, ff=(12, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 3, 0),)), 160),
        (p(dy=5, lean=24, sq=0.93, hf=(11, 3), wa=14, hb=(-8, 3), wb=168, ff=(13, 0), fb=(-10, 0), face='g'), 240),
        (p(dy=3, lean=12, hf=(8, 2), wa=-30, hb=(3, 3), wb=40, ff=(10, 0), fb=(-8, 0)), 110),
        (S0, 100)],
        desc=desc, hit_frame=4, power=2, type='string', input='down, back + Strike')


def dual_riposte(desc):
    """Riposte: the rear weapon snaps straight out from the guard, a one-frame stab, held, back."""
    return W([
        (p(dy=3, lean=4, turn=0.85, hf=(6, -2), wa=-60, hb=(-3, 2), wb=-8, ff=(8, 0), fb=(-8, 0), face='g'), 90),
        (p(dy=3, lean=26, hf=(4, 2), wa=60, hb=(10, 0), wb=-4, ff=(13, 0), fb=(-9, 0), dx=5, face='o', smear_b=(-3, 2)), 40),
        (p(dy=3, lean=28, hf=(4, 2), wa=62, hb=(10, 0), wb=-2, ff=(13, 0), fb=(-9, 0), face='o', fx=(('spark', 'hb', 4, 0),)), 140),
        (p(dy=3, lean=26, hf=(4, 3), wa=60, hb=(10, 1), wb=2, ff=(13, 0), fb=(-9, 0), face='g'), 190),
        (p(dy=2, lean=12, hf=(7, 1), hb=(3, 3), ff=(10, 0), fb=(-8, 0)), 100),
        (S0, 90)],
        desc=desc, hit_frame=2, power=2, type='riposte', input='(after a parry) Strike')


# ---------------------------------------------------------------- polearm (spear) and staff
def pole_thrust(desc, power=2, typ='string', inp='fwd + Strike (hold)'):
    """Long thrust: draw the pole all the way back and hold, one lunging stab to full length, a long frozen extension."""
    return W([
        (p(dy=3, lean=-6, turn=0.8, hf=(-4, 2), wa=-4, ff=(9, 0), fb=(-9, 0), face='g'), 120),
        (p(dy=5, lean=-10, sq=0.94, turn=0.75, hf=(-6, 3), wa=-4, ff=(10, 0), fb=(-10, 0), face='o'), 170),
        (p(dy=3, lean=28, hf=(11, 0), wa=-2, ff=(15, 0), fb=(-9, 0), dx=7, face='o', smear_f=(-6, 3)), 40),
        (p(dy=3, lean=30, hf=(11, 0), wa=-2, ff=(15, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 4, 0),)), 150),
        (p(dy=3, lean=30, hf=(11, 1), wa=0, ff=(15, 0), fb=(-9, 0), face='g'), 260),
        (p(dy=2, lean=14, hf=(5, 2), wa=-20, ff=(11, 0), fb=(-8, 0)), 110),
        (S0, 100)],
        desc=desc, hit_frame=3, power=power, type=typ, input=inp)


def pole_jab(desc):
    """Riposte with a pole: choke up and snap the shaft forward, short and fast."""
    return W([
        (p(dy=3, lean=0, turn=0.85, hf=(-2, 2), wa=-6, ff=(8, 0), fb=(-8, 0), face='g'), 90),
        (p(dy=3, lean=24, hf=(9, 1), wa=-4, ff=(13, 0), fb=(-9, 0), dx=5, face='o', smear_f=(-2, 2)), 40),
        (p(dy=3, lean=26, hf=(9, 1), wa=-4, ff=(13, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 4, 0),)), 140),
        (p(dy=3, lean=24, hf=(9, 2), wa=0, ff=(13, 0), fb=(-9, 0), face='g'), 180),
        (p(dy=2, lean=12, hf=(5, 2), wa=-20, ff=(10, 0), fb=(-8, 0)), 100),
        (S0, 90)],
        desc=desc, hit_frame=2, power=2, type='riposte', input='(after a parry) Strike')


def pole_sweep(desc):
    """Low sweep: the pole goes up and back over the shoulder, the fighter drops low, one flat sweep along the ankles."""
    return W([
        (p(dy=2, lean=0, hf=(-1, -7), eb_f='up', wa=-150, ff=(8, 0), fb=(-8, 0), face='g'), 110),
        (p(dy=7, lean=14, sq=0.92, hf=(-3, -5), eb_f='up', wa=-162, ff=(10, 0), fb=(-10, 0), face='o'), 90),
        (p(dy=8, lean=26, sq=0.92, hf=(10, 8), wa=26, ff=(13, 0), fb=(-10, 0), dx=4, face='o', smear_f=(-3, -5)), 40),
        (p(dy=8, lean=28, sq=0.92, hf=(10, 9), wa=28, ff=(13, 0), fb=(-10, 0), face='o', fx=(('spark', 'hf', 3, 1), ('dust', 'ff', 8, -1))), 140),
        (p(dy=8, lean=26, sq=0.92, hf=(9, 9), wa=34, ff=(13, 0), fb=(-10, 0), face='g'), 190),
        (p(dy=4, lean=14, hf=(6, 4), wa=-20, ff=(10, 0), fb=(-8, 0)), 110),
        (S0, 90)],
        desc=desc, hit_frame=3, power=1, type='string', input='down + Strike')


def pole_vault(desc):
    """Vault kick: plant the pole ahead, sink onto it, spring up it (dust), ride up with both legs tucked (held), whip a
    flying kick off the top, drop with the legs reaching down, land.  V8: the ride is `air`; hit_frame 5."""
    return W([
        (p(dy=4, lean=18, sq=0.93, hf=(8, 5), wa=64, ff=(9, 0), fb=(-8, 0), face='g'), 100),
        (p(dy=6, lean=22, sq=0.88, hf=(9, 6), wa=66, ff=(8, 0), fb=(-8, 0), face='g'), 90),
        (p(dy=-1, lean=-6, sq=1.08, hf=(6, 5), wa=72, ff=(5, 2), fb=(-4, 1), ang_f=22, ang_b=22, face='o', fx=push_dust()), 70),
        (p(dy=-1, lean=-20, hf=(5, 6), wa=78, ff=(5, 9), fb=(1, 9), face='o'), 160),
        (p(dy=-1, lean=-26, sq=1.04, hf=(4, 6), wa=80, ff=(15, 12), fb=(0, 8), ang_f=-12, dx=4, face='o', smear_ff=(5, 9)), 40),
        (p(dy=-1, lean=-26, hf=(4, 6), wa=80, ff=(16, 12), fb=(0, 8), ang_f=-12, face='o', fx=(('spark', 'ff', 4, -1),)), 160),
        (p(dy=0, lean=-12, sq=1.03, hf=(5, 4), wa=72, ff=(9, 3), fb=(-3, 2), face='g'), 100),
        (p(dy=6, lean=14, sq=0.86, head=(2, 2), hf=(6, 4), wa=40, ff=(9, 0), fb=(-8, 0), fx=land_dust()), 130)],
        desc=desc, hit_frame=5, power=3, type='string', input='fwd, up + Kick',
        air_spec=[(3, 0, 0), (4, 0.25, 17.5, 'o'), (5, 0.6875, 16.5, 'h'), (7, 0, 0, 'i')])


def pole_spin(desc):
    """Pole spin: the pole whirls overhead (four quarter turns, speeding up), then comes down across the opponent."""
    return W([
        (p(dy=2, lean=0, hf=(3, -9), eb_f='up', wa=0, ff=(8, 0), fb=(-8, 0), face='g'), 100),
        (p(dy=2, lean=0, hf=(3, -9), eb_f='up', wa=90, ff=(8, 0), fb=(-8, 0), face='g'), 80),
        (p(dy=2, lean=-2, hf=(3, -9), eb_f='up', wa=180, ff=(8, 0), fb=(-8, 0), face='o'), 70),
        (p(dy=3, lean=-6, sq=0.96, hf=(2, -9), eb_f='up', wa=-100, ff=(8, 0), fb=(-9, 0), face='o'), 60),
        (p(dy=3, lean=24, hf=(11, 3), wa=30, ff=(12, 0), fb=(-9, 0), dx=4, face='o', smear_f=(2, -9)), 40),
        (p(dy=3, lean=26, hf=(11, 4), wa=34, ff=(12, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 3, 0),)), 160),
        (p(dy=3, lean=26, hf=(10, 6), wa=44, ff=(12, 0), fb=(-9, 0), face='g'), 230),
        (p(dy=2, lean=12, hf=(6, 2), wa=-20, ff=(10, 0), fb=(-8, 0)), 110)],
        desc=desc, hit_frame=5, power=2, type='string', input='Strike (hold), release')


def staff_slam(desc):
    """Overhead slam: squat, raise the staff in both hands, rise on the toes and HOLD, then bring it down in one frame;
    the ground cracks (shock + dust) and the staff stays planted for a long beat."""
    return W([
        (p(dy=5, lean=10, sq=0.92, hf=(4, 4), wa=-30, ff=(9, 0), fb=(-8, 0), face='g'), 120),
        (p(dy=1, lean=-6, sq=1.04, hf=(2, -8), eb_f='up', wa=-150, ff=(8, 0), fb=(-8, 0), face='o'), 140),
        (p(dy=0, lean=-10, sq=1.06, chest=1.06, hf=(1, -9), eb_f='up', wa=-160, ff=(8, 1), fb=(-8, 1), face='o'), 190),
        (p(dy=5, lean=36, hf=(11, 6), wa=60, ff=(12, 0), fb=(-9, 0), dx=4, face='o', smear_f=(1, -9)), 40),
        (p(dy=7, lean=40, sq=0.90, hf=(11, 7), wa=66, ff=(12, 0), fb=(-9, 0), face='o',
           fx=(('spark', 'hf', 2, 2), ('shock', 'abs', 46, 56), ('dust', 'ff', 8, -1))), 180),
        (p(dy=7, lean=38, sq=0.92, hf=(11, 7), wa=66, ff=(12, 0), fb=(-9, 0), face='g', fx=(('dust', 'ff', 10, -2),)), 290),
        (p(dy=3, lean=18, hf=(7, 3), wa=10, ff=(10, 0), fb=(-8, 0)), 120),
        (S0, 100)],
        desc=desc, hit_frame=4, power=3, type='string', input='down, up + Strike', shake=dict(frames=4, amp=2))


# ---------------------------------------------------------------- chain / kunai
def chain_pull(desc):
    """Chain pull: whirl the rear kunai on its chain, sling it out (the chain pays out across the gap), it bites, then a
    hard yank back with the whole body - the opponent comes with it (the engine slides it in on `pull_frame`)."""
    return W([
        (p(dy=3, lean=4, hf=(6, -2), wa=-60, hb=(-6, -4), wb=-150, ff=(8, 0), fb=(-8, 0), face='g'), 110),
        (p(dy=3, lean=0, hf=(6, -2), wa=-60, hb=(-2, -10), eb_b='up', wb=-100, ff=(8, 0), fb=(-8, 0), face='o'), 90),
        (p(dy=3, lean=24, hf=(4, 2), wa=60, hb=(11, -1), wb=-2, ff=(12, 0), fb=(-8, 0), dx=3, face='o', smear_b=(-2, -10),
           fx=(('chain', 'hb', 2, 0, 12),)), 40),
        (p(dy=3, lean=26, hf=(4, 2), wa=60, hb=(11, -1), wb=-2, ff=(12, 0), fb=(-8, 0), face='o',
           fx=(('chain', 'hb', 2, 0, 18), ('spark', 'hb', 22, 0))), 140),
        (p(dy=5, lean=-18, sq=0.94, hf=(2, 3), wa=80, hb=(-3, 1), wb=-10, ff=(10, 0), fb=(-9, 0), face='o',
           fx=(('chain', 'hb', 2, 0, 24),)), 130),
        (p(dy=4, lean=-12, hf=(3, 2), wa=70, hb=(-1, 2), wb=-20, ff=(10, 0), fb=(-9, 0), face='g', fx=(('chain', 'hb', 2, 0, 8),)), 150),
        (p(dy=3, lean=4, hf=(6, -1), wa=-50, hb=(1, 4), ff=(9, 0), fb=(-8, 0)), 120),
        (S0, 100)],
        desc=desc, hit_frame=3, pull_frame=4, power=1, type='pull', input='back + Grab')


def kunai_toss(desc):
    """Kunai toss: a third kunai drawn from the belt, cocked behind the ear and held, flung side-arm; it crosses the
    gap in two frames and strikes."""
    return W([
        (p(dy=3, lean=2, hf=(6, -2), wa=-60, hb=(-3, 2), wb=150, ff=(8, 0), fb=(-8, 0), face='g'), 100),
        (p(dy=3, lean=-8, sq=0.96, hf=(6, -2), wa=-60, hb=(-4, -8), eb_b='up', wb=-150, ff=(8, 0), fb=(-9, 0), face='o'), 150),
        (p(dy=3, lean=22, hf=(4, 2), wa=60, hb=(11, 0), wb=0, ff=(12, 0), fb=(-8, 0), dx=3, face='o', smear_b=(-4, -8),
           fx=(('kunai', 'hb', 9, 0),)), 40),
        (p(dy=3, lean=24, hf=(4, 2), wa=60, hb=(11, 1), wb=10, ff=(12, 0), fb=(-8, 0), face='o',
           fx=(('kunai', 'hb', 21, 1), ('spark', 'hb', 23, 1))), 140),
        (p(dy=3, lean=24, hf=(4, 3), wa=62, hb=(10, 2), wb=20, ff=(12, 0), fb=(-8, 0), face='g'), 200),
        (p(dy=2, lean=10, hf=(6, -1), wa=-50, hb=(2, 3), ff=(9, 0), fb=(-8, 0)), 110),
        (S0, 90)],
        desc=desc, hit_frame=3, power=1, type='string', input='fwd + Strike (throw)')


# ---------------------------------------------------------------- bow + dagger
def bow_point_blank(desc):
    """Point-blank shot: raise the bow, draw to the cheek and HOLD (the string bends back to the hand), release - the
    arrow crosses the gap - and the bow arm stays up through the follow-through."""
    return W([
        (p(dy=2, lean=6, hf=(9, -1), wa=0, hb=(4, -1), wb=150, ff=(8, 0), fb=(-8, 0), face='g', nock=True), 120),
        (p(dy=3, lean=2, chest=1.05, hf=(10, -1), wa=0, hb=(-2, -2), wb=150, ff=(8, 0), fb=(-9, 0), face='o', nock=True), 190),
        (p(dy=3, lean=0, hf=(10, -1), wa=0, hb=(-6, 1), wb=150, ff=(8, 0), fb=(-9, 0), face='o', smear_b=(-2, -2),
           fx=(('arrow', 'hf', 9, 0),)), 40),
        (p(dy=3, lean=0, hf=(10, -1), wa=0, hb=(-6, 1), wb=150, ff=(8, 0), fb=(-9, 0), face='o',
           fx=(('arrow', 'hf', 19, 0), ('spark', 'hf', 21, 0))), 140),
        (p(dy=3, lean=-2, hf=(10, -2), wa=-6, hb=(-5, 2), wb=150, ff=(8, 0), fb=(-9, 0), face='g'), 230),
        (p(dy=2, lean=6, hf=(7, 1), wa=0, hb=(2, 3), ff=(8, 0), fb=(-8, 0)), 110),
        (S0, 90)],
        desc=desc, hit_frame=3, power=2, type='string', input='Shoot')


def bow_volley(desc):
    """Volley: three arrows in quick succession, a fast re-nock between each, the third one lands."""
    a = dict(hf=(10, -1), wa=0, ff=(8, 0), fb=(-9, 0))
    return W([
        (p(dy=3, lean=2, chest=1.04, hb=(-2, -2), wb=150, face='o', nock=True, **a), 150),
        (p(dy=3, lean=0, hb=(-6, 1), wb=150, face='o', smear_b=(-2, -2), fx=(('arrow', 'hf', 14, 0),), **a), 40),
        (p(dy=3, lean=2, hb=(-1, -2), wb=150, face='o', nock=True, fx=(('arrow', 'hf', 22, 0),), **a), 80),
        (p(dy=3, lean=0, hb=(-6, 1), wb=150, face='o', smear_b=(-1, -2), fx=(('arrow', 'hf', 14, -1),), **a), 40),
        (p(dy=3, lean=2, hb=(-1, -2), wb=150, face='o', nock=True, fx=(('arrow', 'hf', 22, -1),), **a), 70),
        (p(dy=3, lean=0, hb=(-6, 1), wb=150, face='o', smear_b=(-1, -2), fx=(('arrow', 'hf', 12, 1),), **a), 40),
        (p(dy=3, lean=-1, hb=(-6, 1), wb=150, face='o', fx=(('arrow', 'hf', 19, 1), ('spark', 'hf', 21, 1)), **a), 160),
        (p(dy=3, lean=-2, hf=(10, -2), wa=-6, hb=(-5, 2), wb=150, ff=(8, 0), fb=(-9, 0), face='g'), 230)],
        desc=desc, hit_frame=6, power=2, type='string', input='Shoot, Shoot, Shoot')


def bow_leap_shot(desc):
    """Leaping back-shot: load, spring backwards off the front foot (dust), draw on the rise with the knees up, loose at the
    top of the leap (held), drop with the legs reaching, land skidding back.  V8: the leap is `air`; hit_frame 5."""
    return W([
        (p(dy=3, lean=12, sq=0.93, hf=(6, 3), wa=10, hb=(3, 3), ff=(8, 0), fb=(-7, 0), face='g'), 90),
        (p(dy=6, lean=18, sq=0.87, head=(2, 1), hf=(5, 5), wa=14, hb=(2, 5), ff=(8, 0), fb=(-7, 0), face='g'), 100),
        (p(dx=-5, dy=-1, lean=-12, sq=1.08, hf=(8, -1), wa=4, hb=(3, 0), wb=150, ff=(6, 0), fb=(-4, 1), ang_f=22, ang_b=22,
           face='o', nock=True, fx=push_dust()), 60),
        (p(dx=-5, dy=-1, lean=-18, chest=1.05, hf=(10, -1), wa=0, hb=(-2, -2), wb=150, ff=(5, 7), fb=(-3, 6), face='o', nock=True), 150),
        (p(dx=-2, dy=-1, lean=-18, hf=(10, -1), wa=0, hb=(-6, 1), wb=150, ff=(5, 7), fb=(-3, 6), face='o', smear_b=(-2, -2),
           fx=(('arrow', 'hf', 9, 1),)), 40),
        (p(dx=-1, dy=-1, lean=-16, hf=(10, -1), wa=0, hb=(-6, 1), wb=150, ff=(5, 6), fb=(-3, 5), face='o',
           fx=(('arrow', 'hf', 19, 2), ('spark', 'hf', 21, 2))), 140),
        (p(dx=-2, dy=0, lean=-6, sq=1.03, hf=(8, 0), wa=2, hb=(2, 1), wb=150, ff=(7, 2), fb=(-3, 1), face='g'), 110),
        (p(dx=-3, dy=6, lean=8, sq=0.86, head=(2, 2), hf=(8, 2), wa=4, hb=(2, 3), wb=150, ff=(9, 0), fb=(-8, 0), fx=land_dust()), 130)],
        desc=desc, hit_frame=5, power=2, type='string', input='back, back + Shoot',
        air_spec=[(3, 0, 0), (4, 0.25, 14, 'o'), (5, 0.714, 13.5, 'h'), (7, 0, 0, 'i')])


def bow_bash(desc):
    """Guard break with a bow: the bow comes up two-handed like a club over the shoulder (held), then the limb cracks
    down across the guard."""
    return W([
        (p(dy=3, lean=-6, turn=0.8, hf=(0, -8), eb_f='up', wa=-60, hb=(-2, 2), ff=(8, 0), fb=(-8, 0), face='g'), 150),
        (p(dy=5, lean=-12, sq=0.94, chest=1.06, turn=0.7, hf=(-2, -9), eb_f='up', wa=-80, hb=(-3, 3), ff=(9, 0), fb=(-9, 0), face='o'), 170),
        (p(dy=5, lean=-14, sq=0.93, chest=1.07, turn=0.7, hf=(-3, -9), eb_f='up', wa=-86, hb=(-3, 3), ff=(9, 0), fb=(-10, 0), face='o'), 180),
        (p(dy=3, lean=30, hf=(11, 4), wa=50, hb=(2, 4), ff=(14, 0), fb=(-9, 0), dx=6, face='o', smear_f=(-3, -9)), 40),
        (p(dy=3, lean=32, hf=(11, 5), wa=54, hb=(2, 4), ff=(14, 0), fb=(-9, 0), face='o', fx=(('block', 'hf', 3, 0), ('spark', 'hf', 4, -1))), 180),
        (p(dy=3, lean=30, hf=(10, 6), wa=60, hb=(2, 4), ff=(14, 0), fb=(-9, 0), face='g'), 240),
        (p(dy=2, lean=12, hf=(8, 1), wa=0, hb=(3, 3), ff=(10, 0), fb=(-8, 0)), 110),
        (S0, 100)],
        desc=desc, hit_frame=4, power=2, type='guard_break', input='back, fwd + Strike (hold)')


# ---------------------------------------------------------------- fans / chakram
def fan_gust(desc):
    """Fan gust: both fans swept back and held, then one huge forward fan - a gust of wind crosses the gap and shoves."""
    return W([
        (p(dy=3, lean=-4, hf=(-3, -6), eb_f='up', wa=-150, hb=(-5, 3), wb=160, ff=(8, 0), fb=(-8, 0), face='g'), 130),
        (p(dy=4, lean=-10, sq=0.95, chest=1.05, hf=(-4, -7), eb_f='up', wa=-160, hb=(-6, 4), wb=170, ff=(8, 0), fb=(-9, 0), face='o'), 170),
        (p(dy=3, lean=24, hf=(11, 0), wa=-10, hb=(9, 3), wb=10, ff=(12, 0), fb=(-9, 0), dx=3, face='o', smear_f=(-4, -7),
           fx=(('gust', 'hf', 4, 0),)), 40),
        (p(dy=3, lean=26, hf=(11, 0), wa=-8, hb=(9, 3), wb=12, ff=(12, 0), fb=(-9, 0), face='o',
           fx=(('gust', 'hf', 12, 0), ('gust', 'hf', 4, 3))), 150),
        (p(dy=3, lean=26, hf=(11, 1), wa=-4, hb=(9, 4), wb=16, ff=(12, 0), fb=(-9, 0), face='g', fx=(('gust', 'hf', 17, 0),)), 230),
        (p(dy=2, lean=12, hf=(7, -2), wa=-40, hb=(2, 3), wb=40, ff=(10, 0), fb=(-8, 0)), 110),
        (S0, 100)],
        desc=desc, hit_frame=3, power=2, type='gust', input='back, fwd + Strike')


def chakram_boomerang(desc):
    """Boomerang: cock the lead chakram across the body and hold, whip it out (it leaves the hand on proj_frame), the
    hand stays open and waits while it flies out and curves back, then it is caught (catch_frame) and twirled."""
    return W([
        (p(dy=3, lean=-6, turn=0.8, hf=(-3, -2), wa=180, ff=(8, 0), fb=(-8, 0), face='g'), 120),
        (p(dy=4, lean=-10, sq=0.95, turn=0.75, hf=(-5, -1), wa=180, ff=(8, 0), fb=(-9, 0), face='o'), 150),
        (p(dy=3, lean=24, hf=(11, -1), wa=0, ff=(12, 0), fb=(-9, 0), dx=3, face='o', smear_f=(-5, -1)), 40),
        (p(dy=3, lean=24, hf=(11, -1), open_f=True, nowf=True, ff=(12, 0), fb=(-9, 0), face='o'), 170),
        (p(dy=3, lean=14, hf=(9, -2), open_f=True, nowf=True, ff=(10, 0), fb=(-8, 0), face='g'), 330),
        (p(dy=3, lean=10, hf=(8, -2), wa=0, ff=(10, 0), fb=(-8, 0), face='w', fx=(('spark_s', 'hf', 3, 0),)), 90),
        (p(dy=2, lean=8, hf=(8, -1), wa=120, ff=(9, 0), fb=(-8, 0), face='w'), 110),
        (S0, 100)],
        cat='special', desc=desc, proj_frame=3, catch_frame=5, power=2, type='boomerang', input='down, fwd + Throw')


# ---------------------------------------------------------------- heavy (greatsword, axe, kanabo)
def heavy_cleave(desc):
    """Heavy cleave: the weapon goes all the way back over the shoulder and the fighter sinks under its weight - three
    held keys - then ONE frame down, it bites the ground and stays there; heaving it out is part of the move.  Armour:
    the fighter does not flinch from a light hit during the wind-up (`armor`)."""
    return W([
        (p(dy=3, lean=-6, chest=1.04, hf=(-1, -8), eb_f='up', wa=-140, ff=(8, 0), fb=(-8, 0), face='g'), 160),
        (p(dy=4, lean=-14, sq=0.96, chest=1.07, hf=(-3, -9), eb_f='up', wa=-160, ff=(9, 0), fb=(-9, 0), face='o'), 200),
        (p(dy=6, lean=-16, sq=0.92, chest=1.08, hf=(-4, -9), eb_f='up', wa=-166, ff=(10, 0), fb=(-10, 0), face='o'), 230),
        (p(dy=5, lean=36, hf=(11, 6), wa=58, ff=(13, 0), fb=(-9, 0), dx=5, face='o', smear_f=(-4, -9)), 50),
        (p(dy=7, lean=40, sq=0.90, hf=(11, 7), wa=66, ff=(13, 0), fb=(-9, 0), face='o',
           fx=(('spark', 'hf', 2, 2), ('dust', 'ff', 8, -1))), 210),
        (p(dy=8, lean=40, sq=0.90, hf=(11, 8), wa=72, ff=(13, 0), fb=(-9, 0), face='g', fx=(('dust', 'ff', 10, -2),)), 330),
        (p(dy=4, lean=16, hf=(6, 2), wa=-10, ff=(10, 0), fb=(-8, 0), face='g'), 150),
        (S0, 120)],
        desc=desc, hit_frame=4, power=3, type='string', armor=True, input='back + Heavy', shake=dict(frames=4, amp=2))


def heavy_ground_slam(desc):
    """Ground slam: lift and hold, slam the ground in front, the shock wave runs along the floor and reaches the
    opponent a frame later (contact on the wave, not the weapon)."""
    return W([
        (p(dy=2, lean=-8, hf=(1, -9), eb_f='up', wa=-110, ff=(8, 0), fb=(-8, 0), face='g'), 200),
        (p(dy=1, lean=-12, sq=1.05, chest=1.07, hf=(0, -10), eb_f='up', wa=-124, ff=(8, 1), fb=(-8, 1), face='o'), 260),
        (p(dy=6, lean=38, hf=(9, 8), wa=74, ff=(11, 0), fb=(-9, 0), dx=3, face='o', smear_f=(0, -10)), 50),
        (p(dy=8, lean=42, sq=0.88, hf=(9, 9), wa=80, ff=(11, 0), fb=(-9, 0), face='o',
           fx=(('shock', 'abs', 44, 56), ('dust', 'hf', 6, 6))), 110),
        (p(dy=8, lean=42, sq=0.88, hf=(9, 9), wa=80, ff=(11, 0), fb=(-9, 0), face='o',
           fx=(('shock', 'abs', 54, 56), ('spark', 'abs', 56, 50), ('dust', 'hf', 8, 7))), 170),
        (p(dy=7, lean=38, sq=0.92, hf=(9, 8), wa=78, ff=(11, 0), fb=(-9, 0), face='g'), 260),
        (p(dy=3, lean=16, hf=(6, 2), wa=-20, ff=(10, 0), fb=(-8, 0)), 140),
        (S0, 110)],
        desc=desc, hit_frame=4, power=3, type='string', input='down, down + Heavy', shake=dict(frames=5, amp=2))


def heavy_jab(desc):
    """Riposte for a heavy weapon: no time to swing, so the pommel / haft is driven straight out."""
    return W([
        (p(dy=3, lean=-2, turn=0.85, hf=(-3, 1), wa=180, ff=(8, 0), fb=(-8, 0), face='g'), 100),
        (p(dy=3, lean=24, hf=(9, 0), wa=178, ff=(13, 0), fb=(-9, 0), dx=5, face='o', smear_b=(-3, 1),
           fx=(('speedlines', 'hip', -10, -6),)), 40),
        (p(dy=3, lean=26, hf=(9, 0), wa=178, ff=(13, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 3, 0),)), 150),
        (p(dy=3, lean=24, hf=(9, 1), wa=176, ff=(13, 0), fb=(-9, 0), face='g'), 200),
        (p(dy=2, lean=12, hf=(6, 2), wa=-30, ff=(10, 0), fb=(-8, 0)), 110),
        (S0, 90)],
        desc=desc, hit_frame=2, power=2, type='riposte', input='(after a parry) Strike')


# ---------------------------------------------------------------- taunt variants (per family)
def taunt_twirl(desc, end, spins=(80, 170, -100)):
    """A weapon twirl round the wrist, a flick, then the family's own closing pose `end` (held)."""
    keys = [(p(dy=2, lean=8, hf=(8, 1), wa=0, face='g'), 140)]
    for a, ms in zip(spins, (70, 60, 70)):
        keys.append((p(dy=2, lean=8, hf=(8, 1), wa=a, face='g'), ms))
    fa = 40.0                                      # V9: the flick ends near the closing pose (no 170-degree flip into it)
    if end.get('wa') is not None and abs(_angdiff(end['wa'], fa)) > 100:
        fa = (end['wa'] + 70 + 180) % 360 - 180
    keys += [(p(dy=2, lean=10, hf=(9, 3), wa=fa, face='w', fx=(('spark_s', 'hf', 3, 1),)), 160),
             (p(**end), 360), (p(**dict(end, dy=end.get('dy', 2) + 1)), 150), (S0, 120)]
    return W(keys, cat='emote', desc=desc, type='taunt', input='Taunt')


def _lying(body):
    return dict(lean=-90, dy=body.lie_dy, head=(-2, -2), hf=(-4, 3), hb=(-7, 1), eb_f='up', eb_b='up', ff=(12, 1), fb=(10, 0), face='x', cx=5)


def r_launched(body):
    """Popped into the air by a launcher: white flash on the ground, then the trajectory (`air`) pops it to 21 while the
    body tips back with the head leading and the legs trailing, and it hangs there (last key held) for the juggle."""
    W_ = dict(wa=165, wb=170)
    return W([
        (p(flash=True, lean=-16, cx=1, head=(-3, -1), hf=(7, -1), hb=(3, 1), face='h', dx=-2), 50),
        (p(**W_, dy=-1, lean=-30, cx=1, sq=1.06, head=(-4, -1), hf=(4, -6), hb=(0, -5), ff=(4, 3), fb=(-3, 2), ang_f=20, face='h', dx=-3), 70),
        (p(**W_, dy=-1, lean=-50, cx=2, head=(-4, 0), hf=(2, -4), hb=(-3, -2), ff=(6, 6), fb=(1, 5), face='h', dx=-2), 90),
        (p(**W_, dy=-1, lean=-62, cx=3, head=(-3, 0), hf=(1, -2), hb=(-4, 0), ff=(8, 8), fb=(2, 7), face='x', dx=-1), 160),
        (p(**W_, dy=-1, lean=-66, cx=3, head=(-3, 1), hf=(1, -1), hb=(-4, 1), ff=(8, 8), fb=(2, 6), face='x'), 220)],
        cat='reaction', desc='Launched: popped up and hanging in the air, open for a juggle.', type='launched',
        air_spec=[(1, 0, 0), (3, 0, 21, 'o'), (4, 0, 22, 'h'), (4, 1, 21, 'h')])


def r_air_hit(body):
    """Struck again in the air: flash, popped up to ~25 as the body spins further back, settles back to 21 (held)."""
    W_ = dict(wa=165, wb=170)
    return W([
        (p(**W_, flash=True, dy=-1, lean=-70, cx=3, head=(-3, 0), hf=(1, -2), hb=(-4, 0), ff=(8, 9), fb=(2, 8), face='h', dx=-2), 50),
        (p(**W_, dy=-1, lean=-86, cx=3, head=(-3, 1), hf=(-2, -4), hb=(-6, -2), ff=(10, 8), fb=(4, 9), face='h', dx=-3), 80),
        (p(**W_, dy=-1, lean=-80, cx=3, head=(-2, 1), hf=(-1, -3), hb=(-5, -1), ff=(9, 9), fb=(3, 8), face='x', dx=-1), 140),
        (p(**W_, dy=-1, lean=-76, cx=3, head=(-2, 1), hf=(0, -2), hb=(-4, 0), ff=(9, 8), fb=(3, 8), face='x'), 180)],
        cat='reaction', desc='Juggled: hit again while airborne.', type='air_hit',
        air_spec=[(1, 0, 21), (2, 0.286, 25, 'o'), (3, 1, 21, 'h')])


def r_spiked(body):
    """Slammed out of the air: flash at 21, the trajectory drops it fast while the body flattens out (the hips come down
    in the cell over two quick falling keys), flat impact with dust on the floor, one small bounce, lying (then `getup`)."""
    lying, ldy = _lying(body), body.lie_dy
    W_ = dict(wa=165, wb=170)
    return W([
        (p(**W_, flash=True, dy=-1, lean=-70, cx=3, head=(-3, 0), hf=(1, -2), hb=(-4, 0), ff=(8, 9), fb=(2, 8), face='h', dx=-1), 50),
        (p(**W_, dy=ldy * 0.3, lean=-80, cx=3, head=(-3, -1), hf=(-1, -1), hb=(-5, -1), ff=(9, 8), fb=(4, 7), face='h', dx=-1), 40),
        (p(**W_, dy=ldy * 0.65, lean=-86, cx=4, head=(-3, -1), hf=(-2, 1), hb=(-6, 0), ff=(10, 6), fb=(6, 6), face='h', dx=-1), 40),
        (p(**{**lying, 'dy': ldy + 0.5}, sq=0.86, fx=(('shock', 'abs', 32, 56), ('dust', 'hip', -4, 5), ('dust', 'hip', 8, 4))), 90),
        (p(**{**lying, 'dy': ldy - 0.5}, sq=1.0), 70),
        (p(**lying, sq=0.94, fx=(('dust', 'hip', -6, 4),)), 110),
        (p(**lying), 200)],
        cat='reaction', desc='Spiked: slammed out of the air, bounces once and lies there.', type='spiked',
        shake=dict(frames=3, amp=1),
        air_spec=[(0, 0, 21), (0, 0.6, 21), (3, 0, 0, 'i'), (4, 0, 0), (4, 0.5, 3, 'o'), (5, 0, 0, 'i')])


def r_thrown(body):
    """Thrown: grabbed (frame 0 = the attacker's grab_frame), hoisted off its feet to ~14 (`air`), flipped overhead,
    driven down and slammed flat on the attacker's hit_frame (frame 4, h = 0), one bounce, lying.  Same clock as t_throw."""
    lying, ldy = _lying(body), body.lie_dy
    ms = THROW_MS
    W_ = dict(wa=165, wb=170)
    return W([
        (p(lean=22, head=(2, 1), hf=(9, 2), hb=(6, 3), ff=(9, 0), fb=(-6, 0), face='h'), ms[1]),
        (p(**W_, dy=-1, lean=4, sq=1.04, head=(1, 0), hf=(6, -3), hb=(3, -2), ff=(3, 3), fb=(-3, 2), ang_f=20, face='h'), ms[2]),
        (p(**W_, dy=-1, lean=-46, head=(-2, 0), hf=(4, -6), hb=(0, -5), ff=(6, 9), fb=(0, 8), face='h'), ms[3]),
        (p(**W_, dy=ldy * 0.55, lean=-80, head=(-3, 0), hf=(-1, -4), hb=(-5, -3), ff=(10, 7), fb=(5, 7), face='x', cx=3), ms[4]),
        (p(**{**lying, 'dy': ldy + 0.5}, flash=True, sq=0.86, fx=(('shock', 'abs', 32, 56), ('dust', 'hip', -4, 5), ('dust', 'hip', 8, 4))), ms[5]),
        (p(**{**lying, 'dy': ldy - 0.5}, sq=1.0), 80),
        (p(**lying), 220)],
        cat='reaction', desc='Thrown: grabbed, hoisted overhead and slammed flat.', type='thrown', grab_frame=0, hit_frame=4,
        shake=dict(frames=3, amp=1),
        air_spec=[(1, 0, 0), (2, 0.41, 14, 'o'), (2, 0.88, 14, 'h'), (4, 0, 0, 'i'), (5, 0, 0), (5, 0.5, 2, 'o'), (6, 0, 0, 'i')])


def r_pulled(body):
    """Yanked in by a chain: jerked forward at the waist, arms trailing, stumbles two steps, finds its feet."""
    return W([
        (p(flash=True, lean=30, head=(3, 1), hf=(-3, 5), hb=(-6, 4), ff=(5, 0), fb=(-9, 1), face='h', dx=4), 50),
        (p(lean=34, head=(3, 2), hf=(-4, 6), hb=(-7, 5), ff=(11, 3), fb=(-8, 0), face='h', dx=6), 90),
        (p(dy=3, lean=26, sq=0.95, head=(2, 1), hf=(2, 5), hb=(-2, 5), ff=(12, 0), fb=(-5, 2), face='o', dx=3), 110),
        (p(dy=2, lean=12, hf=(6, 2), hb=(2, 3), ff=(9, 0), fb=(-7, 0), face='o'), 120),
        (S0, 100)],
        cat='reaction', desc='Pulled: yanked in by a chain and stumbles forward.', type='pulled')


def r_guard_crush(body):
    """Guard broken: the raised guard is broken open (flash + guard spark), arms fly up, a staggering step back with
    stars, then the guard comes back."""
    stars = (('star', 'head', -6, -9), ('star', 'head', 6, -8))
    return W([
        (p(flash=True, dy=3, lean=-4, hf=(7, -3), hb=(5, -3), wa=-100, wb=-104, fist_f=4, face='h', dx=-2, fx=(('block', 'hf', 4, -3),)), 50),
        (p(dy=1, lean=-20, head=(-3, -1), hf=(3, -11), hb=(-3, -9), eb_f='up', eb_b='up', ff=(7, 0), fb=(-9, 0), face='h', dx=-4), 90),
        (p(dy=2, lean=-24, head=(-3, 0), hf=(2, -10), hb=(-4, -8), eb_f='up', eb_b='up', ff=(8, 2), fb=(-9, 0), face='x', dx=-2, fx=stars), 140),
        (p(dy=3, lean=-10, head=(-1, 1), tilt=8, hf=(5, 2), hb=(1, 3), ff=(8, 0), fb=(-8, 0), face='x', fx=stars), 180),
        (p(dy=3, lean=4, tilt=-4, hf=(6, 1), hb=(3, 2), face='o'), 130),
        (S0, 110)],
        cat='reaction', desc='Guard crushed: the guard flies open and the fighter staggers, wide open.', type='guard_crush')


def r_hit_high(body):
    """Hit high (a rising or overhead blow): the chin snaps up, the head leads back, the arms lift a frame later."""
    return W([
        (p(flash=True, lean=-10, head=(-3, -2), tilt=-10, hf=(7, -1), hb=(3, 1), face='h', dx=-2), 50),
        (p(lean=-20, head=(-4, -3), tilt=-14, hf=(5, -5), hb=(1, -4), ff=(7, 0), fb=(-8, 0), face='h', dx=-2), 70),
        (p(lean=-14, head=(-2, -2), tilt=-8, hf=(4, -2), hb=(1, -1), ff=(7, 0), fb=(-8, 0), face='h', dx=-1), 90),
        (p(lean=2, head=(0, 0), hf=(6, 1), hb=(3, 1), face='h'), 70), (S0, 90)],
        cat='reaction', desc='Hit high: the head snaps back first, the arms follow.', type='hit_high')


def r_hit_low(body):
    """Hit low (a sweep or a body blow): folds over the hit, the knees buckle, then straightens up."""
    return W([
        (p(flash=True, dy=3, lean=22, head=(2, 2), hf=(6, 2), hb=(3, 3), face='h', dx=-1), 50),
        (p(dy=6, lean=34, sq=0.92, head=(3, 3), hf=(3, 6), hb=(1, 6), ff=(6, 1), fb=(-8, 0), face='h', dx=-2), 90),
        (p(dy=5, lean=28, sq=0.95, head=(2, 2), hf=(4, 5), hb=(2, 5), ff=(7, 0), fb=(-8, 0), face='h', dx=-1), 100),
        (p(dy=2, lean=12, hf=(6, 2), hb=(3, 2), face='o'), 80), (S0, 90)],
        cat='reaction', desc='Hit low: doubles over the blow, knees buckle.', type='hit_low')


def r_hit_back(body):
    """Hit from behind (after a dash-through): pitched forward off its feet, stumbles two steps, catches itself."""
    return W([
        (p(flash=True, lean=22, head=(3, 1), hf=(4, 3), hb=(1, 3), face='h', dx=3), 50),
        (p(lean=34, head=(4, 2), hf=(-3, 4), hb=(-6, 3), ff=(11, 3), fb=(-7, 0), face='h', dx=4), 80),
        (p(dy=3, lean=26, sq=0.95, head=(3, 2), hf=(2, 5), hb=(-2, 5), ff=(12, 0), fb=(-5, 1), face='h', dx=3), 110),
        (p(dy=2, lean=12, hf=(6, 2), hb=(2, 3), ff=(9, 0), fb=(-7, 0), face='o'), 100), (S0, 100)],
        cat='reaction', desc='Hit from behind: pitched forward, stumbles, catches itself.', type='hit_back')


def r_clash(body):
    """Weapon clash: both fighters' weapons meet and lock (spark), a straining push with the weapons crossed high, then
    both shove off and skid back.  Both fighters play this row on the same instant."""
    return W([
        (p(dy=3, lean=26, hf=(10, -3), wa=-40, ff=(12, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 3, -2),)), 60),
        (p(dy=4, lean=30, sq=0.95, chest=1.05, hf=(10, -4), wa=-44, ff=(12, 0), fb=(-10, 0), face='o'), 130),
        (p(dy=4, lean=27, sq=0.96, chest=1.06, hf=(9, -3), wa=-40, ff=(12, 0), fb=(-10, 0), face='g', fx=(('spark_s', 'hf', 2, -3),)), 150),
        (p(dy=4, lean=31, sq=0.95, chest=1.06, hf=(10, -4), wa=-46, ff=(12, 0), fb=(-10, 0), face='o'), 120),
        (p(dy=2, lean=-12, hf=(6, 0), wa=-70, ff=(8, 2), fb=(-9, 0), dx=-6, face='o', fx=(('spark', 'hf', 4, -1),)), 90),
        (p(dy=3, lean=-4, sq=0.96, hf=(7, 2), wa=-50, ff=(9, 0), fb=(-8, 0), face='g', fx=(('dust', 'ff', 4, 1),)), 110),
        (S0, 100)],
        cat='reaction', desc='Clash: the weapons lock with a spark, a straining push, then both shove off.', type='clash', lock_frame=0)


REACTIONS = (('launched', r_launched), ('air_hit', r_air_hit), ('spiked', r_spiked), ('thrown', r_thrown),
             ('pulled', r_pulled), ('guard_crush', r_guard_crush), ('hit_high', r_hit_high), ('hit_low', r_hit_low),
             ('hit_back', r_hit_back), ('clash', r_clash))


def _turned(body, ps):
    sk = rig.skeleton(body, ps)
    for side, want in (('f', ps.wa), ('b', ps.wb)):
        w = sk['w' + side]
        if w is not None and want is not None and abs(((w['a'] - want) + 180) % 360 - 180) > 1:
            return True
    return False


def fit_weapons(body, mv):
    """Hand-tuning aid: where the rig would have to TURN a weapon away from the angle a key asks for (its ends would
    leave the cell), pull the hands in toward the shoulder in small steps until it fits at the asked angle, so the blade
    never jumps between two frames.  Keys that fit are left exactly as authored."""
    fr = []
    for ps, ms in mv['frames']:
        if (ps.wa is not None or ps.wb is not None) and _turned(body, ps):
            for k in [1.0 - 0.04 * i for i in range(1, 13)]:
                cand = replace(ps, hf=(ps.hf[0] * k, ps.hf[1] * k), hb=(ps.hb[0] * k, ps.hb[1] * k))
                if not _turned(body, cand):
                    ps = cand
                    break
        fr.append((ps, ms))
    mv['frames'] = fr
    return mv


TAUNT_END = {
    'blade': dict(dy=3, lean=6, turn=0.85, hf=(-1, 7), wa=165, head=(2, 0), tilt=-6, face='w'),
    'dual': dict(dy=2, lean=4, hf=(6, -3), wa=-50, hb=(6, -3), wb=-130, face='w', tilt=-4),
    'polearm': dict(dy=2, lean=4, hf=(8, 0), wa=-90, head=(2, 0), tilt=6, face='w'),
    'staff': dict(dy=2, lean=4, hf=(8, 0), wa=-90, head=(2, 0), tilt=6, face='w'),
    'chain': dict(dy=3, lean=14, hf=(10, -2), wa=0, hb=(1, 4), face='w', tilt=-4),
    'bow': dict(dy=1, lean=0, hf=(4, -11), eb_f='up', wa=-90, face='w'),
    'fans': dict(dy=2, lean=4, hf=(4, -6), wa=-60, head=(2, 0), tilt=-8, face='w'),
    'heavy': dict(dy=2, lean=2, chest=1.06, hf=(2, -3), wa=-150, face='w', head=(2, 0)),
}
TAUNT_DESC = {
    'blade': 'Twirls the blade, flicks it and sheathes it at the hip.',
    'dual': 'Spins one weapon, then crosses both in front of the face.',
    'polearm': 'Twirls the spear and plants it upright with a head tilt.',
    'staff': 'Twirls the staff and plants it with a head tilt.',
    'chain': 'Spins a kunai round one finger and points it at the opponent.',
    'bow': 'Twirls the bow and raises it overhead.',
    'fans': 'Twirls a fan and hides a smile behind it.',
    'heavy': 'Twirls the weapon and rests it on the shoulder.',
}

# family -> [(name, template, desc)]: the family moves first; the shared types are added after them
FAMILY_MOVES = {
    'blade': [('iai_slash', blade_iai, 'Iai: crouches with the blade low at the hip, then draws and cuts in one flash.'),
              ('cross_cut', blade_cross_cut, 'Two strokes that cross in an X: a falling diagonal, then the rising back-cut.'),
              ('riposte', blade_thrust, 'Riposte: a straight lunging stab, the answer to a parry.')],
    'dual': [('flurry', dual_flurry, 'Three alternating cuts, lead, rear, lead rising; the third one lands.'),
             ('scissor_cut', dual_scissor, 'Both weapons thrown wide, then snapped shut across the opponent like scissors.'),
             ('blade_dance', dual_dance, 'A full spin with both weapons held out; the lead one sweeps through.'),
             ('riposte', dual_riposte, 'Riposte: the rear weapon snaps out in a straight stab.')],
    'polearm': [('long_thrust', pole_thrust, 'Draws the spear all the way back, then lunges to its full length.'),
                ('pole_sweep', pole_sweep, 'Drops low and sweeps the spear flat along the ankles.'),
                ('vault_kick', pole_vault, 'Plants the spear, rides up it and whips a flying kick off the top.'),
                ('pole_spin', pole_spin, 'Whirls the spear overhead, faster each turn, then brings it down.'),
                ('riposte', pole_jab, 'Riposte: chokes up and snaps the shaft forward.')],
    'staff': [('overhead_slam', staff_slam, 'Raises the staff, rises on the toes, then cracks it into the ground.'),
              ('staff_sweep', pole_sweep, 'Drops low and sweeps the staff along the ground.'),
              ('pole_vault', pole_vault, 'Plants the staff, vaults up it and kicks off the top.'),
              ('riposte', pole_jab, 'Riposte: drives the end of the staff straight out.')],
    'chain': [('chain_pull', chain_pull, 'Slings the rear kunai out on its chain, then yanks the opponent in.'),
              ('kunai_toss', kunai_toss, 'Cocks a kunai behind the ear and flings it across the gap.'),
              ('riposte', dual_riposte, 'Riposte: a reverse-grip stab with the rear kunai.')],
    'bow': [('point_blank', bow_point_blank, 'Draws to the cheek, holds, and looses an arrow at point-blank range.'),
            ('arrow_volley', bow_volley, 'Three arrows in quick succession; the third one lands.'),
            ('leap_shot', bow_leap_shot, 'Springs backwards and shoots from the top of the leap.'),
            ('riposte', dual_riposte, 'Riposte: a quick stab with the dagger in the rear hand.')],
    'fans': [('fan_gust', fan_gust, 'Sweeps both fans back, then fans a gust of wind across the gap.'),
             ('fan_cut', dual_scissor, 'Both fans thrown wide, then snapped shut across the opponent.'),
             ('fan_flurry', dual_flurry, 'Three alternating fan cuts; the third one lands.'),
             ('riposte', dual_riposte, 'Riposte: the rear fan snaps out edge-first.')],
    'heavy': [('cleave', heavy_cleave, 'A huge wind-up it will not flinch out of, then one cleave into the ground.'),
              ('ground_slam', heavy_ground_slam, 'Slams the ground; the shock wave runs along the floor into the opponent.'),
              ('riposte', heavy_jab, 'Riposte: no time to swing, so the pommel is driven straight out.')],
}
# per-character changes to the family list (the chakram thrower boomerangs instead of gusting; names fit the weapon)
CHAR_MOVES = {
    'nomad': {'fan_gust': ('chakram_boomerang', chakram_boomerang, 'Whips a chakram out; it curves back and is caught.'),
              'fan_cut': ('ring_slash', dual_scissor, 'Both chakrams thrown wide, then snapped shut across the opponent.'),
              'fan_flurry': ('ring_flurry', dual_flurry, 'Three alternating chakram cuts; the third one lands.')},
    'monk': {'flurry': ('tonfa_flurry', dual_flurry, 'Three alternating tonfa strikes; the third one lands.'),
             'scissor_cut': ('tonfa_crush', dual_scissor, 'Both tonfa thrown wide, then slammed together on the opponent.'),
             'blade_dance': ('tonfa_whirl', dual_dance, 'A full spin with both tonfa out; the lead one sweeps through.')},
}
SHARED = [('air_slash', t_air_slash, 'Jumps after a launched opponent and strikes down through it in mid-air.'),
          ('spike', t_spike, 'Leaps, raises the weapon overhead and spikes the airborne opponent into the ground.'),
          ('throw', t_throw, 'Grabs the opponent, hoists it overhead and slams it down.'),
          ('dash_slash', t_dash_slash, 'Bursts through the opponent and stops on the far side; the cut lands a beat later.'),
          ('guard_break', t_guard_break, 'A long heavy wind-up, then the pommel breaks the guard open.')]
SHARED_NAMES = {'codex': {'dash_slash': 'shadow_step'}}
GUARD_BREAK = {'bow': bow_bash}


def _plant(body, ps, lo=24.0):
    """A downward key (a spike's landing squash) whose weapon does not fit pointing down: instead of the rig turning a
    long blade up and back behind the body (the knight's greatsword, the oni's kanabo flipped 70 degrees for one frame),
    bring the hands in and plant the tip on the floor in front, at the steepest angle from `ps.wa` down to `lo` that fits."""
    if ps.wa is None or not _turned(body, ps):
        return ps
    for a in range(int(ps.wa), int(lo) - 1, -2):
        for k in [1.0 - 0.04 * i for i in range(16)]:
            cand = replace(ps, hf=(ps.hf[0] * k, ps.hf[1] * k), hb=(ps.hb[0] * k, ps.hb[1] * k), wa=float(a))
            if not _turned(body, cand):
                return cand
    return ps


def heavier(mv, wind=1.25, follow=1.15):
    """The same keys with the weight of a heavy weapon: every frame before the smear and after the contact is held longer
    (rounded to 10 ms); the smear and the contact frame keep their timing."""
    sm = (mv.get('smear_frames') or [0])[0]
    hit = mv.get('hit_frame', sm)
    fr = []
    for i, (ps, ms) in enumerate(mv['frames']):
        k = wind if i < sm else (follow if i > hit else 1.0)
        fr.append((ps, int(round(ms * k / 10.0)) * 10 if k != 1.0 else ms))
    mv['frames'] = fr
    return mv


def weapon_moves(ch):
    """The character's V7 rows, in a fixed order: family moves, the shared types, the taunt variant, the reactions."""
    fam = family_of(ch)
    out = {}
    swap = CHAR_MOVES.get(ch.name, {})
    for name, fn, desc in FAMILY_MOVES[fam]:
        name, fn, desc = swap.get(name, (name, fn, desc))
        out[name] = fn(desc)
        out[name]['family'] = fam
    for name, fn, desc in SHARED:
        if name == 'guard_break':
            fn = GUARD_BREAK.get(fam, fn)
        name = SHARED_NAMES.get(ch.name, {}).get(name, name)
        out[name] = fn(desc)
        out[name]['family'] = fam
        if fn is t_spike:                              # V9: the landing plants the weapon in front, never flips it behind
            out[name]['frames'][6] = (_plant(ch.body, out[name]['frames'][6][0]), out[name]['frames'][6][1])
        if fam == 'heavy' and fn is not t_throw:       # a heavy weapon winds up longer and follows through longer
            air = 'air_spec' in out[name]              # V8: a leap stays inside ~1.1 s (its rise is already slow)
            out[name] = heavier(out[name], *((1.15, 1.1) if air else ()))
    out['taunt2'] = taunt_twirl(TAUNT_DESC[fam], TAUNT_END[fam])
    for name in combo_for(ch):                     # a string member can be cut short right after its contact hold
        mv = out[name]
        mv['cancel_frame'] = min(len(mv['frames']) - 1, mv['hit_frame'] + 1)
    for name, fn in REACTIONS:
        out[name] = fn(ch.body)
    return {k: fit_weapons(ch.body, v) for k, v in out.items()}


# the character's 3-hit string (anim.json `combo`): riposte -> two family moves, each cancelled on its cancel_frame
COMBO = {'blade': ('riposte', 'iai_slash', 'cross_cut'), 'dual': ('riposte', 'flurry', 'scissor_cut'),
         'polearm': ('riposte', 'long_thrust', 'pole_spin'), 'staff': ('riposte', 'staff_sweep', 'overhead_slam'),
         'chain': ('riposte', 'kunai_toss', 'guard_break'), 'bow': ('riposte', 'point_blank', 'arrow_volley'),
         'fans': ('riposte', 'fan_flurry', 'fan_cut'), 'heavy': ('riposte', 'guard_break', 'cleave')}
COMBO_NAMES = {'nomad': {'fan_flurry': 'ring_flurry', 'fan_cut': 'ring_slash'},
               'monk': {'flurry': 'tonfa_flurry', 'scissor_cut': 'tonfa_crush'}}


def combo_for(character):
    import roster
    ch = roster.get(character)
    ren = COMBO_NAMES.get(ch.name, {})
    return [ren.get(m, m) for m in COMBO[family_of(ch)]]


# ---------------------------------------------------------------- contact metadata (V7 part C): how a hit lands
BLUNT_WEAPONS = ('staff', 'kanabo', 'tonfa')
PIERCE_MOVES = ('jab', 'riposte', 'long_thrust', 'kunai_toss', 'point_blank', 'arrow_volley', 'leap_shot', 'chain_pull')
BLUNT_MOVES = ('low_kick', 'roundhouse', 'vault_kick', 'pole_vault', 'guard_break', 'throw')
HIGH_MOVES = ('uppercut', 'cross', 'roundhouse', 'cross_cut', 'spike', 'air_slash', 'overhead_slam', 'cleave', 'pole_spin',
              'vault_kick', 'pole_vault', 'scissor_cut', 'tonfa_crush', 'fan_cut', 'ring_slash')
LOW_MOVES = ('low_kick', 'pole_sweep', 'staff_sweep', 'ground_slam')
TEMPLATE_HIT = {'spin': ('blunt', 'high'), 'pound': ('blunt', 'high'), 'throw': (None, 'mid'), 'cast': ('pierce', 'mid')}


def annotate_contact(ch, mv):
    """Every move that lands gets `hit` (slash / blunt / pierce: which spark the engine draws on contact) and `height`
    (high / mid / low / back: which reaction the defender plays).  Read from the weapon and the move's shape."""
    kind = ch.body.weapon.kind
    sig_tpl = {name: tpl for name, (tpl, _d, _o) in ch.sig_moves.items()}
    for name, m in mv.items():
        if 'hit_frame' not in m or m.get('cat') not in ('strike', 'throw', 'ultimate', 'special'):
            continue
        hit, height = None, 'mid'
        if name in sig_tpl and sig_tpl[name] in TEMPLATE_HIT:
            hit, height = TEMPLATE_HIT[sig_tpl[name]]
        if name in PIERCE_MOVES or (m.get('type') == 'riposte'):
            hit = 'pierce'
        elif name in BLUNT_MOVES or kind in BLUNT_WEAPONS:
            hit = 'blunt'
        hit = hit or ('blunt' if kind in BLUNT_WEAPONS else 'slash')
        if name in HIGH_MOVES:
            height = 'high'
        elif name in LOW_MOVES:
            height = 'low'
        if m.get('type') == 'through':
            height = 'back'
        m.setdefault('hit', hit)
        m.setdefault('height', height)
    return mv
