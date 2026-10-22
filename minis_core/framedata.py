"""Platform-fighter frame data (V9, docs/ANIMATION-NOTES.md section 12): the numbers that make a hit feel like a hit.

Everything here is a pure function of a move's damage, the target's accumulated damage and the art's own timings, so the
two taskbar processes and the arena (each deriving the same timeline from a seed) agree without talking.

- **Frames** are 1/60 s, the unit fighting games are tuned in.  A move's *startup* runs until its first active frame
  (anim.json `hit_frame`), the *active* frames are the contact frame, *recovery* is the rest; a string member is
  interruptible as soon as (*IASA*) its `cancel_frame`.
- **Hitlag** (both fighters freeze on contact): floor(damage / 3 + 3) frames, at most 20.  A 12 % jab freezes 7 frames
  (117 ms), a 36 % heavy 15 (250 ms).
- **Damage** accumulates per round as a percentage (`pct`): later hits launch further.
- **Knockback** grows with the target's percentage, the move's damage and its scaling, and shrinks with weight:
  kb = ((((p / 10 + p * d / 20) * 200 / (w + 100) * 1.4) + 18) * s / 100) + b.
- **Hitstun** = 0.4 frames per unit of knockback: a bigger hit stuns longer, always.
- **Launch**: speed = kb * 0.03 units per frame, decaying by 0.051 per frame, at a per-move angle; above TUMBLE_KB the
  target tumbles (a real arc, a bounce, then a tech or a knockdown get-up).
- **Block**: shieldstun = damage * 0.45 + 2 frames for the defender, a pushback that grows with damage, and the attacker
  still freezes for the hitlag.
These follow published community frame-data research for platform fighters (sources in ANIMATION-NOTES section 12).
"""
from __future__ import annotations
import math

FPS = 60
HITLAG_CAP = 20                       # frames
HITSTUN_K = 0.4                       # frames of hitstun per unit of knockback
LAUNCH_K = 0.03                       # launch speed (units / frame) per unit of knockback
DECAY = 0.051                         # launch speed lost per frame
TUMBLE_KB = 80.0                      # above this a hit launches into a tumble instead of a flinch
WEIGHT = 100.0                        # a mid-weight fighter
WEIGHTS = {'heavy': 112.0, 'staff': 104.0, 'polearm': 100.0, 'blade': 98.0, 'bow': 94.0, 'chain': 90.0, 'dual': 92.0,
           'fans': 86.0}
DI_MAX_DEG = 18.0                     # how far a launch angle can be leaned off its line (the defender's influence)
SHIELD_PUSH_PX = (2.0, 0.35)          # block pushback (RES 1 px) = a + b * damage
UNIT_PX = 0.9                         # RES 1 px per launch unit on the taskbar (a 48 px strip: compressed below)
TASKBAR_KNOCK_MAX = 64.0              # px: the taskbar strip is short; knockback slides approach this, never exceed it
TASKBAR_LIFT_MAX = 24.0               # px: a tumble's arc stays inside the window's jump headroom (30 px)
TECH_P = 0.5                          # chance a tumbling fighter techs on landing (a roll up instead of lying down)
PCT_PER_HP = 0.5                      # our rounds count 100 HP; the percentage grows by half the HP a hit takes (a heavy: 18 %)
HITLAG_DMG_K = 0.75                   # ... and the freeze is computed on 0.75 x that HP (a 36-HP heavy: 12 frames, 200 ms)
BLOCK_LAG_K = 0.67                    # a blocked hit freezes for two thirds of it

# per power: (knockback scaling s, base knockback b, launch angle in degrees above the horizon)
POWER_KB = {1: (70.0, 4.0, 30.0), 2: (95.0, 12.0, 38.0), 3: (120.0, 22.0, 45.0)}
HEIGHT_ANGLE = {'high': 70.0, 'low': 20.0, 'back': 35.0}      # a rising blow pops up, a sweep skims the floor
SPIKE_ANGLE = -80.0                                           # a spike drives down


def ms(frames):
    return frames * 1000.0 / FPS


def frames_of_ms(m):
    return int(round(float(m) * FPS / 1000.0))


def hitlag_frames(damage):
    """Both fighters freeze this many frames on contact: floor(d / 3 + 3), at most HITLAG_CAP; no damage, no freeze."""
    if damage <= 0:
        return 0
    return min(HITLAG_CAP, int(math.floor(damage / 3.0 + 3.0)))


def hitlag_ms(damage):
    return ms(hitlag_frames(damage))


def weight_of(family):
    return WEIGHTS.get(family or '', WEIGHT)


def knockback(pct, damage, weight=WEIGHT, scaling=100.0, base=0.0):
    """Knockback units.  `pct` is the target's percentage AFTER this hit (so the hit counts itself)."""
    p, d = max(0.0, float(pct)), max(0.0, float(damage))
    return ((((p / 10.0 + p * d / 20.0) * 200.0 / (float(weight) + 100.0) * 1.4) + 18.0) * float(scaling) / 100.0) + float(base)


def hitstun_frames(kb):
    return int(math.floor(max(0.0, kb) * HITSTUN_K))


def hitstun_ms(kb):
    return ms(hitstun_frames(kb))


def launch_speed(kb):
    return max(0.0, kb) * LAUNCH_K


def launch_frames(kb):
    """Frames until the launch speed has decayed to nothing."""
    return int(math.ceil(launch_speed(kb) / DECAY)) if kb > 0 else 0


def launch_distance(kb):
    """Units travelled along the launch line while the speed decays (v + (v - k) + ... down to 0)."""
    v = launch_speed(kb)
    n = int(v / DECAY)
    return n * v - DECAY * n * (n - 1) / 2.0 if n > 0 else 0.0


def tumbles(kb):
    return kb >= TUMBLE_KB


def shieldstun_frames(damage):
    return int(math.floor(max(0.0, damage) * 0.45 + 1.99))


def shield_push_px(damage):
    return SHIELD_PUSH_PX[0] + SHIELD_PUSH_PX[1] * max(0.0, damage)


def move_kb(power, height=None, kind='strike'):
    """(scaling, base, angle) of a move from its power and the height it lands at."""
    s, b, ang = POWER_KB.get(max(1, min(3, int(power or 1))), POWER_KB[2])
    if kind in ('super', 'ultimate'):
        s, b = s * 1.15, b + 10.0
    if height in HEIGHT_ANGLE:
        ang = HEIGHT_ANGLE[height]
    return s, b, ang


def di(angle, rng):
    """The defender leans the launch off its line by up to DI_MAX_DEG (seeded: both processes agree)."""
    return angle + rng.uniform(-DI_MAX_DEG, DI_MAX_DEG)


def taskbar_knock_px(kb):
    """Knockback distance on the taskbar strip: the launch distance scaled to RES 1 px and compressed so a late hit
    still fits the strip (monotonic in kb: more damage, more distance, never past TASKBAR_KNOCK_MAX)."""
    u = launch_distance(kb) * UNIT_PX
    return TASKBAR_KNOCK_MAX * (1.0 - math.exp(-u / TASKBAR_KNOCK_MAX))


def tumble_arc(kb, angle_deg, gravity=0.095, max_fall=1.7):
    """A tumble's flight on the taskbar: -> (air keys [[t_ms, h, ease]...] for the reaction row from the contact, airtime
    ms, horizontal px).  The launch speed decays along its line while gravity pulls down; the height is compressed into
    the jump headroom, then one small bounce."""
    v = launch_speed(kb)
    a = math.radians(angle_deg)
    vx, vy = v * math.cos(a), v * math.sin(a)
    x = y = 0.0
    peak, f = 0.0, 0
    while f < 400:
        f += 1
        sp = math.hypot(vx, vy)
        if sp > 0:
            k = max(0.0, sp - DECAY) / sp
            vx, vy = vx * k, vy * k
        vy -= gravity
        vy = max(vy, -max_fall)
        x += vx
        y += vy
        peak = max(peak, y)
        if y <= 0 and f > 2:
            break
    h = min(TASKBAR_LIFT_MAX, peak * UNIT_PX * 2.2)
    up = ms(max(2, int(f * 0.42)))
    t_land = ms(f)
    bounce = min(4.0, h * 0.18)
    keys = [[0, 0], [int(up), round(h, 1), 'o'], [int(t_land), 0, 'i']]
    if bounce >= 1.0:
        keys += [[int(t_land + 70), round(bounce, 1), 'o'], [int(t_land + 150), 0, 'i']]
    return keys, t_land, taskbar_knock_px(kb)


def move_frames(atlas, move):
    """(startup, active, recovery, iasa) in 60 fps frames from a move's own art timings.  startup = everything before the
    first active frame (`hit_frame`, else `proj_frame`), active = that frame, recovery = the rest; iasa = the first frame
    another action may start (a string's `cancel_frame`, else the end)."""
    a = atlas.anim.get(move) or {}
    fr = [f['ms'] for f in a.get('frames') or []]
    if not fr:
        return 0, 0, 0, 0
    hf = a.get('hit_frame', a.get('proj_frame'))
    total = frames_of_ms(sum(fr))
    if hf is None:
        return 0, 0, total, total
    start = frames_of_ms(sum(fr[:hf]))
    active = max(1, frames_of_ms(fr[hf]))
    cf = a.get('cancel_frame')
    iasa = frames_of_ms(sum(fr[:cf])) if cf is not None else total
    return start, active, max(0, total - start - active), iasa
