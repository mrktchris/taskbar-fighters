"""Arena mode (docs/V4-WORKORDER.md, docs/ARENA.md): the two fighters leave the taskbar and fight across one whole monitor.

Everything here is pure simulation + compositing onto an abstract `surface` (write(img, x, y) / flush() / offset(dx, dy)),
so the same code runs headless in tests (Surface) and on the real monitor (minis_win.arena_window.ArenaWindow).

Stage: platforms are the TOP EDGES of visible windows' rectangles on that monitor (rectangles only - no titles are ever
read) plus the floor.  Fighters are the HD atlases drawn at 2x (~170 px tall) with anime-style flight: jumps, air dashes
with afterimages, hover.  Rounds / HP / winners follow rounds.py (power*12, ultimate 40, 25 s cap, decided vs random;
best-of-3 by default, best-of-1 / 5 or endless as an option).  Window interaction is overlay-only: cracks where a defender
is knocked into a window rect, three cracks shatter it (shards fall, random letters spray), ultimates explode and shake
the whole overlay (the window moves, nothing else does).  With a freeze backdrop (a RAM-only image handed in by the
process) shattered windows become dark holes.

V7 (docs/ARENA.md) - still strictly visual: nothing here can reach another window; it only reads the rectangle list.
  stage      wall bounces off monitor and window edges, ledge grabs / hangs / climb-ups, knock-through with a
             fighter-shaped crack, craters on the taskbar line, skids with sparks along window tops, tech recoveries
  camera     letterbox + eased zoom punch on supers / ultimates (a lens over the fighters' region, never past the
             monitor), speed lines on dashes, radial focus lines + slow motion on the final KO, colour flashes
             (honouring `flashes`)
  air        double jumps, air dashes, air-to-air exchanges, meteor spikes through the ledges, recovery jumps, juggles
  clash      two beams meet, push back and forth, the overlay shakes, one overpowers (an anime beam duel)
  set pieces hand-authored sword scenes (arena_setpieces.py): vanishing dash cuts, flurries, stance finishers, painted
             elemental trails and ink-wash impact frames, 2-4 a match
  hazards    letter rain from shattered windows, cracks that spread and drop a glass shard you can stand on
  options    rounds 1|3|5, endless, intensity calm|normal|wild, seconds, intro (VS card) / outro (winner on the highest
             window, both fly back down) - Arena(options=...) or minis.json "arena" / control.json "arena_opts"

V8 desktop weapons (forge.py, docs/ARENA.md "Forging"): fighters cut pieces out of the screen image the process grabbed
ONCE into RAM at start, morph them into weapons, swing them, crack and shatter them, throw slabs; 2-4 forges a match
(calm 1, wild 5-7).  control.json `forge` (`minis.py forge off`) switches it off and drops the grab mid-match.  The pixels
never leave RAM: the heartbeat says only whether a grab is held (`screen_pixels`), and `arena capture` refuses while it is.
"""
from __future__ import annotations
import math, random
from collections import deque
from PIL import Image, ImageDraw, ImageFilter, ImageChops

from . import choreo, framedata as FD, rounds
from . import arena_setpieces as SP
from . import forge as FG
from . import sfx as sfx_mod
from .effects import EffectPlayer
from .fx import text_image
from .render import font, text, TRACK, AMBER, RED

SCALE = 2                       # HD atlas (RES 2) drawn 2x -> 256 px cells, ~170 px fighters
GRAVITY = 2400.0
MAX_FALL = 2200.0
WALK = 240.0                    # V6: was 180; walking across half a monitor ate the rounds
FLY = 1100.0
JUMP_VY = -1150.0
REACH_PX = 72                   # hip-to-hip distance for a strike at this scale
HUD_H = 64
SPRITE_H = 228                  # ground_y (114) x SCALE: how far a standing fighter's cell reaches above its feet
MIN_PLATFORM_Y = HUD_H + SPRITE_H           # a window top higher than this would stand the fighter in the HUD: not a platform (still a crack target)
EXIT_W, EXIT_H, EXIT_MARGIN = 104, 36, 14
PHASES = ('entry', 'vs', 'intro', 'fight', 'round_end', 'winner', 'exit', 'done')
AFTERIMAGE_S = 0.28
TRAIL_EVERY_S = 0.06                          # V6: an afterimage every other frame (the art guide asks for 3-4 copies, not 8)
HOLE = (12, 12, 16, 255)
# V6 fight feel (docs/ANIMATION-NOTES.md section 7), the same rules as the taskbar timeline (rounds.py)
IMPACT_S = rounds.IMPACT_MS / 1000.0          # impact frames: heavy hits, supers, ultimates, KOs only
FINAL_DOWN_S = 1.0                            # final KO: round_end lasts this long (freeze + slow fall), then the winner beat
WINNER_S = 2.4                                # ... so KO -> exit stays inside rounds.POST_KO_MAX_S
HOLD_LAST = '@last'                           # Body.hold value: keep the last frame of a one-shot (brace, slump)
# V6 pacing: V5 rounds mostly ran out the 25 s clock (46 % TIME, mean 21 s; 39 % of fight time was spent approaching).
LEDGE_P = 0.3                                 # chance the defender flies to a window ledge before an exchange (was 0.5)
DASH_PX = 220                                 # an approach longer than this is an air dash, not a walk (was 300)
APPROACH_S = 4.0                              # give up walking and dash in after this (was 6 s)
COOLDOWN_CLOSE, COOLDOWN_FAR = (0.15, 0.35), (0.3, 0.55)    # pause between exchanges (was 0.25-0.5 / 0.5-0.9)
ARENA_UNIT_PX = 7.0                           # V9: arena px per launch unit (a launch unit per frame = 420 px/s)
ARENA_PUSH_K = 40.0                           # V9: block pushback px (RES 1) -> arena px/s
ARENA_DMG_K = 1.25                            # landed strikes / specials / supers hit this much harder than on the taskbar (the
                                              # arena spends time flying between exchanges); the ultimate stays 40

# ---- V7 stage physics (px, px/s, px/s^2 at the arena's 2x scale)
WALL_BOUNCE_V = 380.0          # a knocked fighter faster than this bounces off a monitor / window edge instead of stopping
WALL_K = 0.55                  # ... keeping this much of its speed (restitution)
BOUNCE_STOP_S = 0.06           # a short hitstop on the bounce: weight
SKID_V = 360.0                 # landing a knock-back faster than this skids instead of stopping
SKID_F = 1500.0                # skid friction: linear deceleration (~220 px for an 820 px/s knockdown)
KNOCK_F = 2400.0               # ground friction while knocked back but not skidding
CRATER_V = 1500.0              # landing on the floor faster than this (meteor, slam) leaves a crater
HANG_DY = 196                  # feet below the ledge while hanging (the jump sheet's arms-up frame reaches ~200 px)
HANG_X = 24                    # hip outside the window edge while hanging
CLIMB_S = 0.46
LAUNCH_FLOAT_K = 0.45          # gravity while a launched fighter floats (juggle hang time)
ZOOM_RECT_K = 0.4              # the zoom lens covers this fraction of the monitor around the fighters
MERGE_LIMIT = 20               # dirty rects kept apart per frame: scattered sparks / glyphs no longer merge into one big repaint
CLASH_GAP = 360                # each fighter's hip from the clash midpoint
CLASH_METER = 70.0             # both meters at least this (and a few exchanges in): they may fire at once
VS_S = 1.7
BAR_MAX_K = 0.085              # letterbox bar height as a fraction of the monitor height (scaled by intensity)

# V7 stage / camera notes stay out of the 1 s heartbeat (arena.json), which keeps naming the fight's own beats
QUIET_EVENTS = frozenset(('zoom', 'radial', 'skid', 'skid_off', 'wall_bounce', 'tech', 'double_jump', 'air_dash', 'ledge_grab', 'climb',
                          'recovery', 'through', 'crater', 'meteor_through', 'hazard_crack', 'hazard_shard', 'shard_platform',
                          'shard_crumble', 'ink', 'pound', 'launch', 'throw', 'pull', 'boomerang', 'juggle_jump', 'outro_perch',
                          'setpiece_setup', 'clash_charge', 'clash_fire', 'clash_meet', 'clash_push', 'meteor', 'forge_cut', 'forge_morph',
                          'forge_armed', 'forge_crack', 'forge_shatter', 'forge_throw', 'forge_pickup', 'forge_loose'))
ROUND_CHOICES = (1, 3, 5)
INTENSITIES = ('calm', 'normal', 'wild')
# How much destruction / FX each intensity allows.  `fx` scales particle and letter counts; None switches a feature off.
INTENSITY = {
    'calm':   dict(sp_p=0.15, fx=0.5, hazard_s=None, rain_s=1.2, zoom=1.07, letterbox=0.7, color_flash=False, speedlines=False, clash_p=0.3, clash_max=1,
                   meteor_p=0.25, craters=2, through_v=1250.0, tech_p=0.35, ledge_plan_p=0.3, shake_k=0.6),
    'normal': dict(sp_p=0.25, fx=1.0, hazard_s=8.0, rain_s=2.6, zoom=1.14, letterbox=1.0, color_flash=True, speedlines=True, clash_p=0.55, clash_max=1,
                   meteor_p=0.5, craters=4, through_v=950.0, tech_p=0.45, ledge_plan_p=0.45, shake_k=1.0),
    'wild':   dict(sp_p=0.4, fx=1.8, hazard_s=4.0, rain_s=4.5, zoom=1.2, letterbox=1.2, color_flash=True, speedlines=True, clash_p=0.85, clash_max=2,
                   meteor_p=0.8, craters=7, through_v=760.0, tech_p=0.55, ledge_plan_p=0.6, shake_k=1.3),
}
DEFAULT_OPTIONS = dict(rounds=3, intensity='normal', seconds=None, endless=False, intro=True, outro=True)


def arena_options(cfg=None, control=None, override=None):
    """The arena's options, validated: DEFAULT_OPTIONS < minis.json "arena" {...} < control.json "arena_opts" {...} <
    `override` (what the CLI passes).  rounds 1|3|5 (0 or "endless" = endless), intensity calm|normal|wild, seconds > 0
    or None, endless / intro / outro booleans.  Anything invalid falls back to the default, never raises."""
    out = dict(DEFAULT_OPTIONS)
    for src in ((cfg or {}).get('arena'), (control or {}).get('arena_opts'), override):
        if isinstance(src, dict):
            out.update({k: v for k, v in src.items() if k in DEFAULT_OPTIONS and v is not None})
    r = out.get('rounds')
    if r in (0, '0', 'endless', 'ffa'):
        out['endless'], r = True, 3
    try:
        r = int(r)
    except (TypeError, ValueError):
        r = 3
    out['rounds'] = r if r in ROUND_CHOICES else 3
    out['intensity'] = out['intensity'] if out.get('intensity') in INTENSITIES else 'normal'
    try:
        s = float(out['seconds']) if out.get('seconds') is not None else None
        out['seconds'] = s if s and s > 0 else None
    except (TypeError, ValueError):
        out['seconds'] = None
    for k in ('endless', 'intro', 'outro'):
        out[k] = bool(out.get(k)) if not isinstance(out.get(k), str) else out[k].lower() in ('1', 'true', 'on', 'yes')
    return out


def arena_dmg(beat):
    d = int(beat.get('dmg') or 0)
    return d if beat.get('kind') == 'ultimate' else int(round(d * ARENA_DMG_K))


# move traits: read from the beat, then the atlas metadata, then the move name, so new moves (weapon families, throws,
# chain pulls, boomerangs, launchers) are played without the arena knowing their names
TRAIT_KEYS = ('launch', 'launcher', 'throw', 'pull', 'boomerang', 'juggle', 'meteor', 'grab', 'pound', 'returns')
TRAIT_NAMES = {'launcher': ('uppercut', 'launch', 'rising', 'upper'), 'throw': ('throw', 'grab', 'suplex', 'hurl'),
               'pull': ('pull', 'chain', 'hook', 'reel', 'whip'), 'boomerang': ('boomerang', 'chakram', 'ring_', 'return'),
               'pound': ('pound', 'slam', 'crush', 'smash', 'earth', 'quake', 'stomp')}
TRAIT_ALIASES = {'launch': 'launcher', 'grab': 'throw', 'returns': 'boomerang'}


def move_traits(atlas, move, beat=None):
    """-> set of traits ('launcher', 'throw', 'pull', 'boomerang', 'pound', 'juggle', 'meteor', 'projectile') for a move."""
    out = set()
    a = (atlas.anim.get(move) or {}) if atlas is not None and move else {}
    srcs = [beat or {}, a]
    for src in srcs:
        for k in TRAIT_KEYS:
            if src.get(k):
                out.add(TRAIT_ALIASES.get(k, k))
        for k in ('traits', 'tags'):
            v = src.get(k)
            if isinstance(v, (list, tuple)):
                out.update(TRAIT_ALIASES.get(str(t), str(t)) for t in v)
        for k in ('family', 'template', 'kind', 'cat'):
            v = src.get(k)
            if isinstance(v, str) and v in TRAIT_NAMES:
                out.add(v)
    n = str(move or '').lower()
    projectile = 'proj_frame' in a
    if projectile:
        out.add('projectile')
    for trait, keys in TRAIT_NAMES.items():
        if any(k in n for k in keys):
            if trait == 'throw' and projectile:
                continue                                       # a thrown projectile ("chakram_throw") is not a grab
            out.add(trait)
    if 'boomerang' in out and not projectile and not (beat or {}).get('boomerang') and not a.get('boomerang'):
        out.discard('boomerang')                               # "ring_spin" is a melee spin, nothing comes back
    return out


def _ease_out(k):
    k = max(0.0, min(1.0, k))
    return 1.0 - (1.0 - k) ** 3


def _ease_in_out(k):
    k = max(0.0, min(1.0, k))
    return 0.5 - 0.5 * math.cos(math.pi * k)


def _ease_out_back(k, s=1.4):
    k = max(0.0, min(1.0, k)) - 1.0
    return 1.0 + k * k * ((s + 1.0) * k + s)


# ---------------------------------------------------------------- headless surface
class Surface:
    """RAM surface for tests / previews: `canvas` holds what the window would show."""

    def __init__(self, w, h):
        self.w, self.h = int(w), int(h)
        self.canvas = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))
        self.writes, self.flushes, self.offsets = 0, 0, []
        self.out_of_bounds = 0
        self._offset = (0, 0)

    def write(self, img, x, y):
        x, y = int(x), int(y)
        if x < 0 or y < 0 or x + img.width > self.w or y + img.height > self.h:
            self.out_of_bounds += 1
        x0, y0, x1, y1 = max(0, x), max(0, y), min(self.w, x + img.width), min(self.h, y + img.height)
        if x1 <= x0 or y1 <= y0:
            return
        self.canvas.paste(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))
        self.writes += 1

    def flush(self, full=False):
        self.flushes += 1
        return True

    def fill(self, rgba):
        """V9: the whole surface one colour (straight alpha), as the window's fill does it."""
        self.canvas.paste(tuple(rgba), (0, 0, self.w, self.h))
        self.fills = getattr(self, 'fills', 0) + 1
        self.writes += 1

    def offset(self, dx, dy):
        self._offset = (dx, dy)
        self.offsets.append((dx, dy))

    def pump(self):
        return True

    def reassert_topmost(self):
        pass

    def close(self):
        pass


# ---------------------------------------------------------------- stage
class Stage:
    """Monitor-local geometry.  windows: [(id, l, t, r, b)] in SCREEN px (ids are opaque numbers kept in RAM only)."""

    def __init__(self, rect, windows=(), floor_y=None, min_size=(160, 100)):
        self.l, self.t, self.r, self.b = [int(v) for v in rect]
        self.w, self.h = self.r - self.l, self.b - self.t
        self.floor_y = int(floor_y - self.t) if floor_y is not None else self.h
        self.min_size = tuple(min_size)
        self.windows = []
        self.extra = []                                         # V7: dropped glass shards: dict(x0, x1, y, until)
        self.update(windows)

    def update(self, windows):
        out = []
        for win in windows:
            wid, l, t, r, b = win
            l, t, r, b = l - self.l, t - self.t, r - self.l, b - self.t
            l, t, r, b = max(0, l), max(0, t), min(self.w, r), min(self.h, b)
            if r - l < self.min_size[0] or b - t < self.min_size[1]:
                continue
            if t <= 2 and (r - l) >= self.w * 0.95:
                continue                                       # maximized: its top edge is the monitor's top, no platform
            if t >= self.floor_y - 10:
                continue
            out.append(dict(id=int(wid), l=l, t=t, r=r, b=b))
        self.windows = out[:16]

    def ledges(self):
        """[(x0, x1, y)]: the window tops a fighter can stand on (clipped)."""
        return [(w['l'], w['r'], w['t']) for w in self.windows if w['t'] >= MIN_PLATFORM_Y]

    def platforms(self):
        """[(x0, x1, y)]: window tops (clipped) + dropped shards + the floor.  A top above MIN_PLATFORM_Y would stand a
        fighter inside the HUD, so it is skipped here but the window still cracks."""
        out = self.ledges()
        out += [(s['x0'], s['x1'], s['y']) for s in self.extra]
        out.append((0, self.w, self.floor_y))
        return out

    def window_at(self, x, y):
        """Topmost window rect containing the point (enumeration order = z-order, top first)."""
        for w in self.windows:
            if w['l'] <= x <= w['r'] and w['t'] <= y <= w['b']:
                return w
        return None

    def window_by_id(self, wid):
        for w in self.windows:
            if w['id'] == wid:
                return w
        return None


class Cracks:
    """Per-window crack state machine: 0 -> 1 -> 2 cracks, the third shatters (once)."""
    SHATTER_AT = 3

    def __init__(self):
        self.count = {}
        self.shattered = set()

    def hit(self, wid, heavy=False):
        """-> 'crack_small' | 'crack_big' | 'shatter' | None (already shattered)."""
        if wid in self.shattered:
            return None
        self.count[wid] = self.count.get(wid, 0) + (2 if heavy else 1)
        if self.count[wid] >= self.SHATTER_AT:
            self.shattered.add(wid)
            return 'shatter'
        return 'crack_big' if heavy else 'crack_small'

    def state(self, wid):
        return 'shattered' if wid in self.shattered else self.count.get(wid, 0)


# ---------------------------------------------------------------- fighters
class Body:
    def __init__(self, slot, atlas, x, y, facing):
        self.slot, self.atlas = slot, atlas
        self.x, self.y, self.vx, self.vy = float(x), float(y), 0.0, 0.0
        self.facing = facing
        self.anim, self.anim_t0, self.loop = 'idle', 0.0, True
        self.hp = rounds.HP_MAX
        self.grounded = False
        self.support = None
        self.fly_until = 0.0                 # gravity off while flying / hovering
        self.target = None                   # (x, y) the fighter moves towards, or None
        self.knocked_until = 0.0
        self.down = False                    # lying after a knockdown
        self.trail = deque(maxlen=8)         # afterimages: (t, anim, frame, facing, x, y)
        self.last_crack = 0.0
        self.hold = None                     # anim to settle into when a one-shot finishes
        self.stop = None                     # (t0, t1) hitstop: animation and motion stand still (V5)
        self.hover = False                   # stays in the air at its target while fly_until lasts (air-to-air) (V5)
        self.move_until = 0.0                # a reset step (backdash / walk_back) keeps its velocity until then (V5)
        self.getup_at = None                 # knocked down but not out: kip up at this time (V5)
        self.slow = None                     # (t0, t1, k): V6 slow motion of animation and motion (the final KO)
        self.slump_at = None
        # V7
        self.pose = None                     # (anim, frame index) drawn instead of the animation clock (hang, clash)
        self.hang = None                     # dict(x, y, side, until): hanging off a window ledge
        self.climb = None                    # dict(t0, x0, y0, x1, y1): climbing up over the ledge
        self.ledge_plan = None               # (side, x0, x1, y): fly to the hang point, then hang
        self.skid = False                    # sliding on a platform after a knock-back
        self.meteor = False                  # spiked down: falls through window tops to the floor
        self.float_until = 0.0               # launched: lighter gravity until then (juggle hang time)
        self.air_plan = None                 # dict(y, stage): jump, double jump, hover at y (air-to-air)
        self.chase = None                    # slot to follow in the air (juggle jump)
        self.recover_ok = False              # knocked off into the air: may use one recovery jump
        self.inside = None                   # window id it is passing through (knock-through)
        self.pull_to = None                  # x a chain pull drags it to
        self.dash_until = 0.0                # speed lines behind it until then
        self.jitter = 0                      # beam clash mash-shake (draw offset, px)
        self.arrive_play = None              # anim to play on reaching the target (the outro's victory pose)
        self.dive_at = None                  # outro: when the hop turns into the dive back to the taskbar
        self.last_spark = 0.0
        self.grab_cool = 0.0
        self.alpha = None                    # set pieces: vanish / reappear (None = opaque)
        self.fly_speed = None                # set-piece marks: a crisp constant dash instead of the slowing approach

    def play(self, name, now, loop=None, hold=None):
        if name not in self.atlas.anim:
            name = 'idle'
        if name == self.anim and self.loop and (loop is None or loop):
            return
        self.anim, self.anim_t0 = name, now
        self.loop = self.atlas.anim[name]['loop'] if loop is None else loop
        self.hold = hold

    def elapsed_ms(self, now):
        """The animation clock of the current row (hitstop stands still, slow motion slows), in ms."""
        el = now - self.anim_t0
        if self.stop is not None:
            el -= max(0.0, min(now, self.stop[1]) - max(self.stop[0], self.anim_t0))
        if self.slow is not None:
            el -= max(0.0, min(now, self.slow[1]) - max(self.slow[0], self.anim_t0)) * (1.0 - self.slow[2])
        return max(0.0, el) * 1000.0

    def frame(self, now):
        if self.pose is not None:
            return self.pose[1], False
        return self.atlas.locate(self.anim, self.elapsed_ms(now), self.loop)

    LIFT_CATS = ('ultimate', 'emote', 'pair')

    def row_lift(self, now):
        """V9: arena px the sprite is lifted by its row's `air` curve when the arena's physics is NOT already flying it:
        a standing fighter playing an ultimate / emote that is a real jump in the art (the grapple zip, the victory hops),
        which used to hop inside the cell.  Jumps, juggles and spikes stay with the physics (their rows are strikes,
        locomotion or reactions)."""
        if self.pose is not None or not self.grounded:
            return 0
        a = self.atlas.anim.get(self.anim) or {}
        if not a.get('air') or a.get('cat') not in self.LIFT_CATS:
            return 0
        return int(round(choreo.air_lift(a, self.elapsed_ms(now)) * self.atlas.res * SCALE))

    def drawn_anim(self):
        return self.pose[0] if self.pose is not None else self.anim

    def speed(self, now):
        """1.0, or the slow-motion factor while the finisher's slow window runs."""
        sl = self.slow
        return sl[2] if sl is not None and sl[0] <= now < sl[1] else 1.0

    def stopped(self, now):
        return self.stop is not None and self.stop[0] <= now < self.stop[1]

    def center(self):
        return self.x, self.y - 40 * SCALE

    def sprite_rect(self):
        w, h = self.atlas.cell
        left = int(self.x - self.atlas.anchor(self.facing) * SCALE)
        top = int(self.y - self.atlas.ground_y * SCALE)
        return left, top, left + w * SCALE, top + h * SCALE

    def frame_count(self, anim):
        return len(self.atlas.anim[anim]['frames']) if anim in self.atlas.anim else 0


# ---------------------------------------------------------------- camera (V7)
class Camera:
    """Letterbox bars, the zoom punch, colour flashes, focus lines.  All of it is paint on the overlay.

    The zoom and the bars are smoothed per drawn frame towards a target (fast in, slower out), so a second punch while
    one is running, or bars asked for again while they leave, continue from where they are: they never jump."""
    Z_W_IN, Z_W_OUT = 22.0, 9.0           # critically damped springs (1/s): continuous velocity, so they ease in AND out
    B_W_IN, B_W_OUT = 12.0, 10.0

    def __init__(self, w, h, intensity):
        self.w, self.h, self.I = w, h, intensity
        self.zoom = None                     # dict(until, z, rect, focus): the punch target
        self.z, self.zv = 1.0, 0.0           # the zoom actually drawn, and its velocity
        self.box_until = None                # the bars stay in until then
        self.bar, self.bv = 0.0, 0.0         # their drawn height, and its velocity
        self.flash = None                    # (t0, secs, rgb, alpha)
        self.radial = None                   # (t0, t1, x, y)
        self._tz = self._tb = None

    @staticmethod
    def _spring(x, v, target, w, dt):
        """One critically damped spring step (sub-stepped for stability): eases out of rest and into the target."""
        n = max(1, int(dt / 0.008) + 1)
        h = dt / n
        for _ in range(n):
            v += (w * w * (target - x) - 2.0 * w * v) * h
            x += v * h
        return x, v

    def punch(self, now, cx, cy, z=None, hold=0.22):
        z = min(float(z or self.I['zoom']), 1.35)
        if z <= 1.001:
            return
        if self.zoom is not None and self.z > 1.002:          # already zoomed: keep the lens where it is, extend it
            self.zoom.update(until=max(self.zoom['until'], now + 0.12 + hold), z=max(self.zoom['z'], z))
            return
        rw, rh = int(self.w * ZOOM_RECT_K), int(self.h * ZOOM_RECT_K)
        x0 = int(min(max(cx - rw / 2.0, 0), self.w - rw))
        y0 = int(min(max(cy - rh / 2.0, 0), self.h - rh))
        self.zoom = dict(until=now + 0.12 + hold, z=z, rect=(x0, y0, x0 + rw, y0 + rh),
                         focus=(min(max(cx, x0 + 1), x0 + rw - 1), min(max(cy, y0 + 1), y0 + rh - 1)))

    def zoom_at(self, now):
        """-> (z, rect, focus) while the lens is drawn, else None.  Call once per drawn frame."""
        dt = 0.0 if self._tz is None else max(0.0, min(0.1, now - self._tz))
        self._tz = now
        zm = self.zoom
        if zm is None:
            self.z, self.zv = 1.0, 0.0
            return None
        target = zm['z'] if now < zm['until'] else 1.0
        self.z, self.zv = self._spring(self.z, self.zv, target, self.Z_W_IN if target > 1.0 else self.Z_W_OUT, dt)
        self.z = min(self.z, zm['z'])                          # a spring never overshoots the cap
        if now >= zm['until'] and self.z <= 1.003:
            self.zoom, self.z, self.zv = None, 1.0, 0.0
            return None
        return (self.z, zm['rect'], zm['focus']) if self.z > 1.002 else None

    def letterbox(self, now, until):
        self.box_until = until if self.box_until is None or self.bar <= 0 else max(self.box_until, until)

    def unbox(self, now):
        if self.box_until is not None:
            self.box_until = min(self.box_until, now)

    def bar_h(self, now):
        """The bar height to draw this frame (even px).  Call once per drawn frame."""
        dt = 0.0 if self._tb is None else max(0.0, min(0.1, now - self._tb))
        self._tb = now
        full = self.h * BAR_MAX_K * self.I['letterbox']
        target = full if self.box_until is not None and now < self.box_until else 0.0
        self.bar, self.bv = self._spring(self.bar, self.bv, target, self.B_W_IN if target > 0 else self.B_W_OUT, dt)
        self.bar = max(0.0, min(full, self.bar))
        if target == 0.0 and self.bar < 1.5:
            self.bar, self.bv, self.box_until = 0.0, 0.0, None
        return int(round(self.bar / 2.0)) * 2

    def color_flash(self, now, rgb, alpha=0.32, secs=0.12):
        if self.I['color_flash']:
            self.flash = (now, secs, tuple(rgb), alpha)

    def flash_at(self, now):
        f = self.flash
        if f is None:
            return None
        el = now - f[0]
        if el < 0:
            return None
        if el >= f[1]:
            self.flash = None
            return None
        return f[2], f[3] * (1.0 - el / f[1])


# ---------------------------------------------------------------- procedural V7 art (cached)
_ART = {}


def _art(key, make):
    im = _ART.get(key)
    if im is None:
        if len(_ART) > 400:
            _ART.clear()
        im = _ART[key] = make()
    return im


_BAR_IDS = set()


def _is_bar(im):
    return bool(im.info.get('minis_bar'))


def _bar(w, h):
    def make():
        im = Image.new('RGBA', (w, h), (6, 6, 10, 236))
        _BAR_IDS.add(id(im))                               # the compositor repaints only the strip a bar grew or shrank by
        im.info['minis_bar'] = True                        # V9: marked on the image: an id outlives a cleared _ART cache and
        return im                                          # was reused by other images, which then were never repainted
    return _art(('bar', w, h), make)


def _shadow(w):
    def make():
        h = max(4, w // 5)
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([0, 0, w - 1, h - 1], fill=(0, 0, 0, 96))
        return im
    return _art(('shadow', w), make)


def _speedlines(variant, horizontal=True, w=520, h=150):
    def make():
        rng = random.Random(41 + variant)
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for _ in range(16):
            y = rng.uniform(6, h - 6)
            L = rng.uniform(w * 0.3, w * 0.95)
            x0 = rng.uniform(0, w - L)
            a = int(110 + 120 * (1.0 - abs(y - h / 2) / (h / 2)))
            d.line([(x0, y), (x0 + L, y)], fill=(255, 255, 255, a), width=rng.choice((1, 2, 2, 3)))
        # fade towards the far end (the fighter sits at x = w): lines thin out behind it
        mask = Image.linear_gradient('L').rotate(90).resize((w, h))
        im.putalpha(ImageChops.multiply(im.getchannel('A'), ImageChops.invert(mask)))
        return im if horizontal else im.rotate(90, expand=True)
    return _art(('speed', variant, horizontal, w, h), make)


def _radial(variant, size):
    """Anime focus lines: dark wedges converging on the centre, a clear core."""
    def make():
        rng = random.Random(97 + variant)
        im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c = size / 2.0
        n = 64
        for i in range(n):
            a = (i + rng.uniform(-0.3, 0.3)) / n * 2 * math.pi
            da = rng.uniform(0.008, 0.022)
            r0 = c * rng.uniform(0.42, 0.62)
            pts = [(c + math.cos(a) * r0, c + math.sin(a) * r0), (c + math.cos(a - da) * c * 1.5, c + math.sin(a - da) * c * 1.5),
                   (c + math.cos(a + da) * c * 1.5, c + math.sin(a + da) * c * 1.5)]
            d.polygon(pts, fill=(255, 255, 255, 200) if i % 3 == 0 else (16, 12, 20, 170))
        return im
    return _art(('radial', variant, size), make)


def _spark_img(variant):
    def make():
        rng = random.Random(7 + variant)
        L = rng.randint(16, 28)
        im = Image.new('RGBA', (L + 6, 9), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.line([(3, 4), (L + 3, 4)], fill=(150, 50, 10, 230), width=5)          # dark rim: reads on white windows too
        d.line([(3, 4), (L + 3, 4)], fill=(255, 196, 70, 255), width=3)
        d.line([(L - 5, 4), (L + 3, 4)], fill=(255, 255, 235, 255), width=3)
        return im
    return _art(('spark', variant), make)


def _rubble_img(variant):
    def make():
        rng = random.Random(13 + variant)
        s = rng.randint(7, 13)
        im = Image.new('RGBA', (s + 2, s + 2), (0, 0, 0, 0))
        pts = [(rng.uniform(0, s * 0.4), rng.uniform(0, s)), (rng.uniform(s * 0.4, s), rng.uniform(0, s * 0.4)), (rng.uniform(s * 0.6, s), rng.uniform(s * 0.6, s)),
               (rng.uniform(0, s * 0.5), rng.uniform(s * 0.7, s))]
        ImageDraw.Draw(im).polygon(pts, fill=(70, 66, 72, 255), outline=(150, 146, 156, 255))
        return im
    return _art(('rubble', variant), make)


def _ring_img(r):
    def make():
        im = Image.new('RGBA', (2 * r + 6, r + 6), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([2, 2, 2 * r + 3, r + 3], outline=(30, 30, 50, 150), width=5)        # dark edge: visible on white windows
        d.ellipse([3, 3, 2 * r + 2, r + 2], outline=(255, 255, 255, 235), width=3)
        return im
    return _art(('ring', r), make)


def _beam_strip(rgb, phase, w, bh=60):
    """One long beam strip (left to right) in a fighter's accent: glow, body, white core, wobbling edges."""
    def make():
        import colorsys
        im = Image.new('RGBA', (w, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c = bh / 2.0
        h, s, v = colorsys.rgb_to_hsv(*[x / 255.0 for x in rgb])
        sat = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h, max(s, 0.75), 1.0))      # saturated: a pale accent read white on white
        deep = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h, max(s, 0.8), 0.55))
        step = 6
        for x in range(0, w, step):
            wob = math.sin(x * 0.045 + phase * 1.7) * 2.5 + math.sin(x * 0.11 - phase * 2.3) * 1.5
            g, b2, core = c * 0.92 + wob, c * 0.6 + wob * 0.6, c * 0.22 + wob * 0.3
            d.rectangle([x, c - g, x + step, c + g], fill=sat + (110,))
            d.rectangle([x, c - b2 - 2, x + step, c + b2 + 2], fill=deep + (235,))   # a dark rim around the body
            d.rectangle([x, c - b2, x + step, c + b2], fill=sat + (245,))
            d.rectangle([x, c - core, x + step, c + core], fill=(255, 255, 255, 255))
        return im
    return _art(('beam', rgb, phase, w, bh), make)


def _clash_ball(rgb_a, rgb_b, phase, size=170):
    def make():
        rng = random.Random(phase * 31 + 5)
        im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c = size / 2.0
        for i, col in enumerate((rgb_a, rgb_b, rgb_a, rgb_b)):
            pts = []
            for k in range(18):
                a = math.pi * 2 * k / 18 + i * 0.4 + phase * 0.3
                rr = c * (0.95 - i * 0.16) * (1.0 if k % 2 == 0 else rng.uniform(0.45, 0.65))
                pts.append((c + rr * math.cos(a), c + rr * math.sin(a)))
            d.polygon(pts, fill=col + (215,))
        r = c * (0.32 + 0.05 * (phase % 2))
        d.ellipse([c - r, c - r, c + r, c + r], fill=(255, 255, 255, 255))
        return im
    return _art(('clash', rgb_a, rgb_b, phase, size), make)


def _hand_flare(rgb, phase, size=74):
    def make():
        im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c = size / 2.0
        r = c * (0.85 + 0.1 * (phase % 2))
        d.ellipse([c - r, c - r, c + r, c + r], fill=rgb + (120,))
        d.ellipse([c - r * 0.55, c - r * 0.55, c + r * 0.55, c + r * 0.55], fill=(255, 255, 255, 255))
        return im
    return _art(('flare', rgb, phase, size), make)


def _crater_img(w, seed):
    """A dent bitten into the taskbar line: jagged dark bowl below, a rubble rim and cracks along the line above."""
    rng = random.Random(seed)
    h = int(w * 0.42)
    line = int(h * 0.38)                                # the floor line inside the image
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = w / 2.0
    pts = []
    for k in range(25):
        a = math.pi * k / 24
        rx, ry = c * 0.86 * rng.uniform(0.9, 1.04), (h - line) * 0.9 * rng.uniform(0.85, 1.0)
        pts.append((c - math.cos(a) * rx, line + math.sin(a) * ry))
    d.polygon(pts, fill=(58, 50, 56, 240))
    d.line(pts, fill=(196, 188, 194, 255), width=3)                 # a lit rim: the dent reads on a dark taskbar
    inner = [(c + (x - c) * 0.62, line + (y - line) * 0.58) for x, y in pts]
    d.polygon(inner, fill=(10, 8, 12, 250))
    for k in range(7):                                  # radial cracks running down into the taskbar
        a = math.pi * (0.15 + 0.7 * k / 6.0) + rng.uniform(-0.08, 0.08)
        x0, y0 = c + math.cos(a) * c * 0.5, line + math.sin(a) * (h - line) * 0.45
        x1, y1 = c + math.cos(a) * c * 0.98, line + math.sin(a) * (h - line) * 0.98
        d.line([(x0, y0), ((x0 + x1) / 2 + rng.uniform(-5, 5), (y0 + y1) / 2), (x1, y1)], fill=(230, 226, 236, 230), width=2)
    for _ in range(9):                                  # cracks running along the line
        x = rng.uniform(0.05, 0.95) * w
        y = line
        a = math.pi if x < c else 0.0
        for seg in range(3):
            L = rng.uniform(10, 26)
            a2 = a + rng.uniform(-0.45, 0.45)
            nx, ny = x + L * math.cos(a2), y + L * math.sin(a2) * 0.5
            d.line([(x, y), (nx, ny)], fill=(235, 232, 240, 210), width=2)
            x, y = nx, ny
    for _ in range(7):                                  # rubble on the rim
        x = c + rng.choice((-1, 1)) * rng.uniform(c * 0.55, c * 0.95)
        s = rng.uniform(5, 11)
        y = line - rng.uniform(1, s)
        d.polygon([(x - s, y + s * 0.4), (x - s * 0.2, y - s * 0.6), (x + s, y), (x + s * 0.3, y + s * 0.6)], fill=(120, 112, 120, 255),
                  outline=(214, 208, 216, 255))
    return im, line


def _shard_img(w, h, seed):
    rng = random.Random(seed)
    im = Image.new('RGBA', (w, h + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = [(0, 3), (w * 0.3, 0), (w * 0.7, 2), (w, 0)]
    for k in range(7, -1, -1):
        pts.append((w * k / 7.0, h + rng.uniform(-6, 10)))
    d.polygon(pts, fill=(176, 206, 240, 225), outline=(70, 96, 140, 255))          # a dark edge so it reads on white windows
    d.line(pts[:4], fill=(255, 255, 255, 255), width=2)
    d.line([(4, 4), (w - 4, 2)], fill=(255, 255, 255, 255), width=2)
    for _ in range(3):
        x = rng.uniform(w * 0.1, w * 0.9)
        d.line([(x, 4), (x + rng.uniform(-14, 14), h - 2)], fill=(150, 176, 210, 220), width=1)
    return im


def _spread_crack(w, h, seed):
    """A crack running across a window (left to right), revealed progressively by cropping."""
    rng = random.Random(seed)
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = h / 2.0
    x = 0.0
    pts = [(x, y)]
    while x < w:
        x += rng.uniform(18, 46)
        y = min(h - 4, max(4, y + rng.uniform(-14, 14)))
        pts.append((min(x, w), y))
    d.line([(px + 1, py + 2) for px, py in pts], fill=(20, 20, 30, 170), width=3)
    d.line(pts, fill=(245, 248, 255, 240), width=3)
    for px, py in pts[1:-1:2]:                           # little branches
        a = rng.uniform(-2.4, -0.7) if rng.random() < 0.5 else rng.uniform(0.7, 2.4)
        L = rng.uniform(10, 24)
        d.line([(px, py), (px + L * math.cos(a) * 0.6, py + L * math.sin(a))], fill=(235, 240, 255, 220), width=2)
    return im, pts


def _fighter_crack(sprite, seed):
    """A fighter-shaped hole outline in the glass: the silhouette's edge as cracks, frosted inside, radial cracks out."""
    pad = 60
    a = sprite.getchannel('A').point(lambda v: 255 if v > 0 else 0)
    a = a.filter(ImageFilter.MaxFilter(5))
    edge = ImageChops.subtract(a, a.filter(ImageFilter.MinFilter(5)))
    w, h = sprite.width + 2 * pad, sprite.height + 2 * pad
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    frost = Image.new('RGBA', sprite.size, (220, 232, 250, 60))
    im.paste(frost, (pad, pad), a)
    dark = Image.new('RGBA', sprite.size, (20, 20, 30, 190))
    im.paste(dark, (pad + 2, pad + 2), edge)
    white = Image.new('RGBA', sprite.size, (250, 252, 255, 245))
    im.paste(white, (pad, pad), edge)
    bbox = a.getbbox() or (0, 0, sprite.width, sprite.height)
    cx, cy = pad + (bbox[0] + bbox[2]) / 2.0, pad + (bbox[1] + bbox[3]) / 2.0
    rx, ry = (bbox[2] - bbox[0]) / 2.0, (bbox[3] - bbox[1]) / 2.0
    rng = random.Random(seed)
    d = ImageDraw.Draw(im)
    for i in range(9):
        ang = i / 9.0 * 2 * math.pi + rng.uniform(-0.2, 0.2)
        x, y = cx + math.cos(ang) * rx * 0.9, cy + math.sin(ang) * ry * 0.9
        for seg in range(3):
            L = rng.uniform(12, 24)
            ang += rng.uniform(-0.4, 0.4)
            nx, ny = x + math.cos(ang) * L, y + math.sin(ang) * L
            d.line([(x, y), (nx, ny)], fill=(245, 248, 255, 230), width=2)
            x, y = nx, ny
    return im


# ---------------------------------------------------------------- the arena
class Arena:
    def __init__(self, stage, atlases, fx, seed=1, mode='decided', scores=None, backdrop=None, names=None, now=0.0, record=None,
                 cfg=None, chars=None, options=None, screen=None, forge=None):
        """atlases: {'a': Atlas(hd), 'b': Atlas(hd)}; backdrop: RGBA image the size of the stage kept in RAM, or None.
        options: see arena_options(); layered over minis.json "arena" (cfg) and control.json "arena_opts" - the latter only
        when a cfg is given (the real process), so a bare Arena never reads this machine's control file.
        screen: forge.ScreenImage - the monitor grabbed once into RAM for desktop weapons (None: weapons from window shapes).
        forge: desktop weapons on / off; None = control.json `forge` (default on) when a cfg is given, else off."""
        self.stage, self.fx = stage, fx
        self.rng = random.Random(seed)
        self.mode = mode if mode in rounds.MODES else 'decided'
        self.scores = dict(scores or {'a': 100.0, 'b': 100.0})
        self.p_left = rounds.p_left(self.mode, self.scores, 'a', 'b')
        self.names = dict(names or {'a': atlases['a'].display, 'b': atlases['b'].display})
        self.chars = dict(chars or {s: atlases[s].character for s in 'ab'})
        self.record = record or rounds.record_result
        self.cfg = cfg or {}
        ctl = {}
        if cfg is not None:                                    # the real process: minis.json and control.json layers apply
            try:
                from . import control
                ctl = control.read()
            except Exception:
                ctl = {}
        options = arena_options(self.cfg, ctl, options)        # explicit options (the CLI flags) win over both
        self.opts = options
        self.endless = bool(options['endless'])
        self.to_win = None if self.endless else options['rounds'] // 2 + 1
        self.I = dict(INTENSITY[options['intensity']])
        self.cam = Camera(stage.w, stage.h, self.I)
        self.backdrop = backdrop                               # RAM only: never written, never logged
        self.holes = []
        self.fxp = EffectPlayer(fx, res=SCALE * 2, fps=30)    # arena px = RES 2 art at 2x -> res 4 relative to the RES 1 rig
        self.fxp.res = 4
        self.cracks = Cracks()
        self.crack_marks = {}                                  # window id -> [(x, y, kind)] drawn while the window stands
        self.letters_spawned = 0
        self.explosions = 0
        self.fx_count = 0                                      # V7: every FX element spawned by the arena (intensity tests)
        self.decals = []                                       # V7: dict(img, x, y, wid, until, kind, reveal)
        self.particles = []                                    # V7: [img, x, y, vx, vy, g, t_end]
        self.rains = []                                        # V7: letter rain from shattered windows
        self.shards = []                                       # V7: falling glass shards that become platforms
        self.clashes = 0
        self.sp = None                                         # the set piece playing (arena_setpieces.SetPiece)
        self.sp_played = 0
        self.sp_last = -1e9
        self.sp_target = 2 + (self.rng.random() < 0.5) + (self.rng.random() < 0.3)   # 2-4 set pieces a match
        self.next_hazard = now + 6.0
        w, fy = stage.w, stage.floor_y
        self.start_x = {'a': w * 0.3, 'b': w * 0.7}
        self.f = {'a': Body('a', atlases['a'], self.start_x['a'], fy + 260, 1), 'b': Body('b', atlases['b'], self.start_x['b'], fy + 260, -1)}
        self.wins = {'a': 0, 'b': 0}
        self.round = 0
        self.rounds = []
        self.phase, self.phase_t0 = 'entry', now
        self.t0 = now
        self.round_t0 = now
        self.exchange = None                                   # dict(att, dfn, state, t, move, ...)
        self.banner = None                                     # (kind, until, x)
        self.winner = None
        self.ko_loser = None
        self.paused = False
        self.exit_requested = False
        self.last_now = now
        self.events = deque(maxlen=400)                        # content-free notes (kind, t) for tests / the log
        self.counts = {}                                       # every event kind counted over the whole match (V7)
        self.used_ult = {'a': False, 'b': False}
        self.cooldown_until = now + 0.5
        self.hp_history = []
        self.pick = {s: choreo.Picker(self.rng, atlases[s]) for s in 'ab'}        # V5 choreography state
        self.meter = {'a': 0.0, 'b': 0.0}
        self.k_round = 0
        self.air_done = False
        self.last_att, self.last_hit = None, False
        self.ult_rolled = False                                # V6: one ultimate roll per match, one ultimate per match
        self.comeback_for = None                               # the loser of the last round gets one comeback exchange
        self.sfx = None                                        # V9: sfx.Player (the real process sets it), None = silent
        self.boost = []                                        # slots whose agent just finished a task: signature super first
        self.boost_any = set()                                 # V9: ... from a live bus marker: the very next exchange, any round
        self.pct = {'a': 0.0, 'b': 0.0}                        # V9 frame data: damage % this round (later hits launch further)
        self.fd_rng = random.Random(seed * 7919 + 211)         # V9: DI draws on their own stream (the fight's rng is unchanged)
        self.fd_log = []                                       # V9: frame data of every landed hit (tests, the QA log)
        self.boost_seen = set()                                # V9: marker ids already used (one super per finished task)
        self._boost_read = -1e9
        self.impact = None                                     # (t0, t1, struck slot): impact frames on screen
        self.flashes = None                                    # control.json `flashes`; None = read it here (every 2 s)
        self._flash_cache, self._flash_read = True, -1e9
        self.final_ko = None                                   # (t, loser) of the match-deciding KO
        self._text_banners = {}
        self._vs = None
        if forge is None:                                      # desktop weapons (forge.py): the owner's default is on
            forge = bool(ctl.get('forge', self.cfg.get('forge', True))) if cfg is not None else False
        self._forge_read = now
        self.forge = FG.Forge(self, screen=screen, enabled=forge, seed=seed)
        if self.forge.enabled:                                 # V9: decode the unarmed sheets now, not on the first forged
            for s in 'ab':                                     # weapon's frame (a 130 ms stall mid-fight)
                warm = getattr(atlases[s], '_unarmed_sheets', None)
                if warm is not None:
                    try:
                        warm()
                    except Exception:
                        pass
        if cfg is not None:                                    # V9: the real process may play sounds (control.json `sound`, off by default)
            self.sfx = sfx_mod.Player(enabled=sfx_mod.control_enabled())
        for s in 'ab':
            self.f[s].vy = -1700.0                             # entry: burst out of the taskbar, upward
            self.f[s].fly_until = 0.0
            self._burst_ring(now, self.start_x[s], fy)
        self.note('entry', now)

    # ---- bookkeeping
    def note(self, kind, t, **kw):
        self.events.append((kind, round(t, 3), kw))
        if self.sfx is not None:                               # V9 sound effects (off by default; the arena plays its own)
            snd = sfx_mod.sound_for_arena(kind, kw)
            if snd:
                self.sfx.play(snd, t, t)
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def state(self):
        return dict(phase=self.phase, round=self.round, hp={s: self.f[s].hp for s in 'ab'}, wins=dict(self.wins), winner=self.winner,
                    mode=self.mode, freeze=self.backdrop is not None, shattered=len(self.cracks.shattered), cracks=sum(self.cracks.count.values()),
                    rounds=self.opts['rounds'], endless=self.endless, intensity=self.opts['intensity'],
                    forge=self.forge.state(), screen_pixels=self.forge.pixels,
                    events=[[k, t, str(kw.get('name') or kw.get('move') or '')] for k, t, kw in
                            [e for e in self.events if e[0] not in QUIET_EVENTS][-32:]])

    def request_exit(self, now):
        if self.phase not in ('exit', 'done'):
            self.exit_requested = True
            self._enter('exit', now)

    def exit_rect(self):
        return (self.stage.w - EXIT_MARGIN - EXIT_W, EXIT_MARGIN, self.stage.w - EXIT_MARGIN, EXIT_MARGIN + EXIT_H)

    def hit_exit(self, x, y):
        x0, y0, x1, y1 = self.exit_rect()
        return x0 <= x <= x1 and y0 <= y <= y1

    def _final(self, who):
        """Would one more round for `who` end the match?  (Endless: every KO gets the finisher beat.)"""
        return self.endless or self.wins[who] + 1 >= self.to_win

    def _match_over(self):
        return not self.endless and max(self.wins.values()) >= self.to_win

    def _fxn(self, n):
        """n scaled by the intensity, at least 1 when n > 0."""
        return max(1 if n > 0 else 0, int(round(n * self.I['fx'])))

    # ---- phases
    def _enter(self, phase, now):
        if self.sp is not None and phase in ('intro', 'winner', 'exit'):
            self.sp.finish(now)
            self.sp = None
        self.phase, self.phase_t0 = phase, now
        self.note(phase, now)
        if phase == 'vs':
            self._vs = None
            for s in 'ab':
                self.f[s].play('powerup' if 'powerup' in self.f[s].atlas.anim else 'idle', now + 0.25, loop=False, hold='idle')
        elif phase == 'intro':
            self.round += 1
            self.pct = {'a': 0.0, 'b': 0.0}
            for s in 'ab':
                b = self.f[s]
                b.hp = rounds.HP_MAX
                b.down = False
                self._release(b)
                b.target = (self.start_x[s], self.stage.floor_y)
                b.fly_until = now + 2.0
                b.play('getup' if b.anim in ('ko', 'knockdown') else 'idle', now, loop=False, hold='idle')
            self.used_ult = {'a': False, 'b': False} if self.round == 1 else self.used_ult      # the ultimate is once per MATCH
            if self.round == 1:
                self.ult_rolled = False
            self.banner = (self._round_banner(), now + 1.2, None)
            self.exchange = None
            self.forge.new_round()
            self.k_round, self.air_done = 0, False
            for p in self.pick.values():
                p.new_round()
            for s in 'ab':
                self.f[s].stop, self.f[s].hover, self.f[s].getup_at, self.f[s].slow = None, False, None, None
        elif phase == 'fight':
            self.banner = None
            self.round_t0 = now
            self.cooldown_until = now + 0.4
            self.next_hazard = now + (self.I['hazard_s'] or 0) * self.rng.uniform(0.6, 1.0)
        elif phase == 'winner':
            champ = self.winner
            loser = 'b' if champ == 'a' else 'a'
            C = self.f[champ]
            self.banner = ('winner', now + WINNER_S, None, self.names.get(champ))      # the name banner over the winner (x follows it)
            pose = 'victory2' if self.wins[loser] == 0 and 'victory2' in C.atlas.anim else 'victory'
            top = self._highest_ledge(C) if self.opts['outro'] else None
            if top is not None and not C.down:
                x0, x1, y = top
                C.target = (min(max((x0 + x1) / 2.0, x0 + 70), x1 - 70), y)
                C.fly_until = now + 1.6
                C.hover = False
                C.play('jump', now, loop=False, hold='idle')
                C.arrive_play = (pose, HOLD_LAST)
                self.note('outro_perch', now, who=champ)
            else:
                C.play(pose, now, loop=False, hold=HOLD_LAST)
            L = self.f[loser]
            if L.down and 'getup' in L.atlas.anim:                 # KO'd: stays down a moment longer, then slumps up (slowed)
                gu = L.atlas.total_ms('getup') / 1000.0 / rounds.GETUP_SLOW_K
                L.getup_at = None
                L.slump_at = (max(now + 0.4, now + WINNER_S - 0.1 - gu), gu)
            elif not L.down:                                       # lost on time: slumps, nobody falls over unprovoked
                sl = next((n for n in rounds.SLUMP if n in L.atlas.anim), None)
                if sl:
                    L.play(sl, now, loop=False, hold=HOLD_LAST)
            try:
                self.record(self.chars[champ], self.chars[loser], where='arena')
            except Exception:
                pass
            self.note('record', now, winner=self.chars[champ])
        elif phase == 'exit':
            self.banner = None
            self.exchange = None
            for s in 'ab':
                b = self.f[s]
                self._release(b)
                b.target = None
                b.fly_until = 0.0
                b.vy, b.vx = -620.0, 0.0                           # a hop, then the dive back down into the taskbar
                b.grounded = False
                b.down = False
                b.dive_at = now + 0.2 if self.opts['outro'] else None
                b.play('jump', now, loop=False, hold='idle')
            self.fxp.clear()
            self.particles = []
            self.rains = []

    def _release(self, b):
        """Drop every V7 per-body state (hang, climb, clash pose, chase, ...)."""
        b.pose = b.hang = b.climb = b.ledge_plan = b.air_plan = b.chase = b.pull_to = b.arrive_play = None
        b.skid = b.meteor = False
        b.jitter = 0
        b.inside = None
        b.float_until = 0.0
        b.alpha = None
        b.fly_speed = None

    def _round_banner(self):
        n = self.round
        if self.to_win and self.to_win > 1 and all(self.wins[s] == self.to_win - 1 for s in 'ab') and self.opts['rounds'] > 3:
            return 'text:FINAL ROUND'
        return f'round{n}' if n <= 3 else f'text:ROUND {n}'

    def _highest_ledge(self, b):
        ls = [p for p in self.stage.ledges() if p[1] - p[0] >= 160]
        if not ls:
            return None
        return min(ls, key=lambda p: (p[2], abs((p[0] + p[1]) / 2.0 - b.x)))

    # ---- main step
    def tick(self, now):
        dt = max(0.0, min(0.05, now - self.last_now))
        self.last_now = now
        if self.sfx is not None:
            self.sfx.quiet = self.paused                       # paused: no sound at all
        if self.paused or self.phase == 'done':
            return
        self.fxp.tick(now)
        if self.banner and now >= self.banner[1]:
            self.banner = None
        if self.opts['seconds'] and now - self.t0 >= self.opts['seconds'] and self.phase not in ('exit', 'done'):
            self.request_exit(now)
        if self.sp is not None and self.phase in ('fight', 'round_end'):
            self.sp.tick(now)
            if self.sp.done and (self.exchange is None or self.exchange.get('state') != 'setpiece'):
                self.sp = None
        ph = self.phase
        if ph == 'entry':
            if now - self.phase_t0 >= 1.5 and all(self.f[s].grounded for s in 'ab'):
                self._enter('vs' if self.opts['intro'] else 'intro', now)
        elif ph == 'vs':
            if now - self.phase_t0 >= VS_S:
                self._enter('intro', now)
        elif ph == 'intro':
            el = now - self.phase_t0
            if 1.2 <= el < 1.9 and (self.banner is None or self.banner[0] != 'fight'):
                self.banner = ('fight', self.phase_t0 + 1.9, None)
            if el >= 2.0:
                self._enter('fight', now)
        elif ph == 'fight':
            self._fight(now)
            self._hazards(now)
        elif ph == 'round_end':
            final = self.final_ko is not None and (self._match_over() or self.endless and self.ko_loser is not None)
            if now - self.phase_t0 >= (FINAL_DOWN_S if final else 2.4) + (0.6 if self.endless and final else 0.0):
                if self._match_over():
                    self.winner = 'a' if self.wins['a'] > self.wins['b'] else 'b'
                    self._enter('winner', now)
                else:
                    self._enter('intro', now)
        elif ph == 'winner':
            if now - self.phase_t0 >= WINNER_S:
                self._enter('exit', now)
        elif ph == 'exit':
            if all(self.f[s].y > self.stage.h + 320 for s in 'ab') or now - self.phase_t0 > 4.0:
                self._enter('done', now)
        for s in 'ab':
            self._move(self.f[s], now, dt)
        if ph in ('fight', 'round_end'):
            for s in 'ab':
                self._window_collisions(self.f[s], now)
        self._tick_world(now, dt)
        self._forge_poll(now)
        self._boost_poll(now)
        self.forge.tick(now, dt)
        for s in 'ab':
            b = self.f[s]
            if b.getup_at is not None and now >= b.getup_at and b.down and b.hp > 0 and self.phase in ('fight', 'round_end'):
                if b.grounded and not b.skid:
                    b.getup_at = None
                    b.down = False
                    b.play('getup', now, loop=False, hold='idle')
                    self.note('getup', now, who=s)
            sa = b.slump_at
            if sa is not None and now >= sa[0] and self.phase == 'winner':
                b.slump_at = None
                b.down = False
                b.play('getup', now, loop=False, hold='idle')
                b.slow = (now, now + sa[1], rounds.GETUP_SLOW_K)
            if b.pose is None:
                idx, done = b.frame(now)
                if done and not b.loop and b.hold != HOLD_LAST and b.hold != b.anim:   # a one-shot held as itself keeps its last
                    b.play(b.hold or 'idle', now)                                       # frame (a replayed knockdown flashed white)

    # ---- choreography (V5: choreo.py plans every exchange; the arena plays its beats with physics)
    def _reach(self, slot, move):
        """Player px a move's own effect reaches from the hand (a beam), else 0."""
        name = self._main_fx(self.f[slot].atlas, move)
        return self.fxp.reach(name) if name else 0.0

    @staticmethod
    def _main_fx(atlas, move):
        sched = atlas.move_fx(move) if move else []
        for off, name, until in sched:
            if name == move:
                return name
        return sched[-1][1] if sched else None

    def _range_for(self, who, beat):
        """Hip distance the actor wants before this attack beat lands."""
        kind, move = beat['kind'], beat['anim']
        if kind == 'special':
            return max(REACH_PX * 2.5, 260.0)
        if kind == 'ultimate':
            name = self._main_fx(self.f[who].atlas, move)
            e = self.fx.get(name) if name else None
            reach = self.fxp.reach(name) if name else 0.0
            if reach > 0:
                return reach * 0.8                                 # the defender stands inside the beam, near its end
            if e is not None and e.travel:
                return 260.0
        try:
            r = float((self.f[who].atlas.anim.get(move) or {}).get('reach') or 0) * SCALE
        except (TypeError, ValueError):
            r = 0.0
        return float(REACH_PX) if r <= 0 else max(float(REACH_PX), min(r * 0.9, 220.0))   # a long weapon fights from further out

    def _new_exchange(self, now):
        a, b = self.f['a'], self.f['b']
        k = self.k_round
        boost = comeback = False
        if self.boost and (k < 2 or self.boost[0] in self.boost_any):
            att, boost = self.boost.pop(0), True                   # its agent just finished a task: the signature super opens
            self.boost_any.discard(att)
        elif self.comeback_for is not None and k == 1:
            att, comeback = self.comeback_for, True                # lost the last round: one exchange where everything lands
            self.comeback_for = None
        elif self.last_att is not None and self.last_hit and self.rng.random() < 0.45:
            att = self.last_att                                    # pressure: the winner of the last exchange keeps coming
        else:
            att = 'a' if self.rng.random() < self.p_left else 'b'
        dfn = 'b' if att == 'a' else 'a'
        A = self.f[att].atlas
        air = (not self.air_done) and ((k >= 1 and self.rng.random() < 0.35) or k >= 3) and not (boost or comeback)
        drama = (choreo.dramatic(self.wins[att], self.f[att].hp, self.f[dfn].hp, k) and now - self.round_t0 > 4.0
                 and not any(self.used_ult.values()) and not self.ult_rolled and not (boost or comeback))
        if drama:                                                  # V6: ONE roll per match, the first time anyone qualifies
            self.ult_rolled = True
            drama = self.rng.random() < choreo.ULT_CHANCE
        dist = abs(self.f[att].x - self.f[dfn].x)
        reach = self._reach(att, A.ultimate()) if A.ultimate() else 0.0
        sit = dict(range='far' if dist > REACH_PX * 1.6 else 'close', meter=self.meter[att], ult_ok=not any(self.used_ult.values()), dramatic=drama,
                   ult_sure=drama, friendly=False, air=air, k=k, ult_reaches=reach >= dist - 20, boost=boost, comeback=comeback,
                   edge=choreo.edge_for(self.f[att].hp, self.f[dfn].hp, self.wins[att], self.wins[dfn]))
        ex = choreo.plan_exchange(self.rng, self.pick[att], self.pick[dfn], sit)
        beats = [bt for bt in ex['beats'] if not (bt.get('kind') == 'move' and (bt.get('dx') or 0) > 0)]   # openers are played by the approach
        self.k_round += 1
        first = next((bt for bt in beats if bt.get('kind') not in ('move', 'emote')), None)
        sp_owed = not self.endless and self.sp_played < 2 and max(self.wins.values()) >= self.to_win - 1
        if not air and not boost and not sp_owed and self._forge_try(att, dfn, k, now):
            return
        if not air and not (boost or comeback) and self._setpiece_try(att, dfn, k, now):
            return
        if first is not None and not air and not (boost or comeback) and self._clash_ok(att, dfn, first, now):
            self._start_clash(att, dfn, first, now)
            return
        if air:
            self.air_done = True
            y = max(float(MIN_PLATFORM_Y), min(min(a.y, b.y) - 260.0, self.stage.floor_y - 300.0))   # up in the air, under the HUD
            for s in (att, dfn):
                f = self.f[s]
                f.target, f.hover = None, False
                f.air_plan = dict(y=y, stage=0)                     # V7: jump, double jump at the apex, hover there
            self.note('air', now)
        elif self.rng.random() < LEDGE_P:                         # the defender takes to a window ledge first
            D = self.f[dfn]
            plats = self.stage.platforms()
            cur = [p for p in plats if abs(p[2] - D.y) < 2]
            choice = [p for p in plats if p not in cur] or plats
            x0, x1, y = choice[self.rng.randrange(len(choice))]
            hang = None
            if y < self.stage.floor_y and (x0, x1, y) in self.stage.ledges() and self.rng.random() < self.I['ledge_plan_p']:
                sides = [s for s, hx in (('l', x0 - HANG_X), ('r', x1 + HANG_X)) if 60 <= hx <= self.stage.w - 60]
                if sides:
                    hang = sides[self.rng.randrange(len(sides))]
            if hang:                                               # V7: fly up short of it and catch the ledge
                hx = x0 - HANG_X if hang == 'l' else x1 + HANG_X
                D.target = (hx, y + HANG_DY)
                D.ledge_plan = (hang, x0, x1, y)
            else:
                D.target = (min(max(x0 + 60, self.rng.uniform(x0, x1)), x1 - 60), y)
            D.fly_until = now + 1.6
            D.play('jump', now, loop=False, hold='idle')
            self.note('fly', now, who=dfn)
        self.exchange = dict(att=att, dfn=dfn, beats=beats, i=0, state='approach', t=now, deadline=now + APPROACH_S + 2.0, air=air, kind=ex['kind'],
                             opener=ex.get('opener'), range_after=ex.get('range_after', 'close'), hit=False)

    def _fight(self, now):
        over = now - self.round_t0 - rounds.ROUND_CAP_S
        ex = self.exchange
        if over >= 0 and (ex is None or ex['state'] in ('approach', 'beat', 'wait', 'sp_setup', 'forge') or over > (2.5 if ex['state'] in ('clash', 'setpiece') else 1.0)):
            if ex is not None and ex['state'] == 'clash':
                self._end_clash(ex, now)
            if self.sp is not None:
                self.sp.finish(now)
                self.sp = None
            self._end_round(now, None)                             # time: the round is called on HP (a strike in flight gets 1 s)
            return
        if ex is None:
            if now < self.cooldown_until or any(self.f[x].down or self.f[x].hang or self.f[x].climb for x in 'ab'):
                return                                             # nobody starts an exchange while someone is on the floor
            self._new_exchange(now)
            return
        if ex['air']:
            for s in 'ab':
                if self.f[s].hover:
                    self.f[s].fly_until = now + 2.0
        if ex['state'] == 'approach':
            self._approach(ex, now)
        elif ex['state'] == 'beat':
            self._start_beat(ex, now)
        elif ex['state'] == 'wait':
            if now >= ex['until']:
                ex['i'] += 1
                ex['state'] = 'beat'
        elif ex['state'] == 'strike':
            self._tick_strike(ex, now)
        elif ex['state'] == 'clash':
            self._tick_clash(ex, now)
        elif ex['state'] == 'sp_setup':
            self._tick_sp_setup(ex, now)
        elif ex['state'] == 'forge':
            if ex['job'].done or now >= ex['deadline']:
                if not ex['job'].done:
                    self.forge._finish(ex['job'], now, release=True)
                self.exchange = None
                self.last_att, self.last_hit = ex['att'], ex['job'].kind == 'slab'
                self.cooldown_until = now + self.rng.uniform(*COOLDOWN_CLOSE)
        elif ex['state'] == 'setpiece':
            if self.sp is None or self.sp.done:
                self.sp = None
                self.sp_last = now
                self.exchange = None
                self.last_att, self.last_hit = ex['att'], True
                self.cooldown_until = now + self.rng.uniform(*COOLDOWN_FAR)

    def _first_attack(self, ex):
        for bt in ex['beats'][ex['i']:]:
            if bt.get('kind') not in ('move', 'emote'):            # any attack kind, including ones the moves side adds later
                return bt
        return None

    def _approach(self, ex, now):
        att, dfn = self.f[ex['att']], self.f[ex['dfn']]
        first = self._first_attack(ex)
        if first is None:
            ex['state'] = 'beat'
            return
        if dfn.hang is not None or dfn.climb is not None:
            if now < ex['deadline'] - 2.0:
                return                                             # let it climb up first
        want = self._range_for(ex['att'], first)
        dx = dfn.x - att.x
        if abs(dx) > 8:                                            # on top of each other: keep the facing (V5 flipped it every frame)
            att.facing = 1 if dx >= 0 else -1
        want_x = dfn.x - att.facing * want
        want_x = min(max(want_x, 40.0), self.stage.w - 40.0)
        if ex['air']:
            both_up = all(self.f[s].hover and self.f[s].air_plan is None for s in 'ab')
            if not both_up and now < ex['deadline'] - 2.0:
                return
            ty = dfn.y
            if abs(att.x - want_x) > 24 or abs(att.y - ty) > 24:
                if att.target is None or abs(att.target[0] - want_x) > 4:
                    if abs(att.x - want_x) > 160 and not ex.get('air_dash'):
                        ex['air_dash'] = True                      # V7: an air dash, with afterimages and speed lines
                        att.play('dash', now, loop=False, hold='idle')
                        self.note('air_dash', now, who=ex['att'])
                att.target = (want_x, ty)
                att.hover, att.fly_until = True, now + 2.0
                return
            att.target = (att.x, ty)
            self.note('air_strike', now)
        else:
            far = abs(att.x - want_x) > 24 or abs(att.y - dfn.y) > 36
            if far and first['kind'] != 'special':
                att.target = (want_x, dfn.y)
                dist = math.hypot(att.x - want_x, att.y - dfn.y)
                if dist > DASH_PX or abs(att.y - dfn.y) > 36 or now > ex['deadline'] - 2.0 or ex['opener'] == 'dash':   # a ledge: fly up
                    att.fly_until = now + 0.6                   # air dash: straight line, afterimages
                    if att.anim not in ('dash', 'jump'):
                        att.play('dash', now, loop=False, hold='idle')
                elif ex['opener'] == 'jump' and att.grounded:
                    att.vy = JUMP_VY * 0.85                     # jump-in: leave the ground towards the defender
                    att.grounded = False
                    att.play('jump', now, loop=False, hold='idle')
                elif att.grounded:
                    att.play('walk', now)
                if now < ex['deadline']:
                    return
            att.target = None
            att.vx = 0.0
        ex['state'] = 'beat'

    def _start_beat(self, ex, now):
        if ex['i'] >= len(ex['beats']):
            self._end_exchange(ex, now)
            return
        bt = ex['beats'][ex['i']]
        who = ex['att'] if bt.get('who', 'att') == 'att' else ex['dfn']
        tgt = 'b' if who == 'a' else 'a'
        W, T = self.f[who], self.f[tgt]
        kind = bt.get('kind', 'strike')
        if kind == 'move':
            if bt.get('juggle') or (bt.get('anim') == 'jump' and not bt.get('dx')):
                dur = W.atlas.total_ms('jump') / 1000.0 * 0.6 if 'jump' in W.atlas.anim else 0.35
                W.play('jump', now, loop=False, hold='idle')       # V7 juggle: jump up after the launched defender
                W.chase, W.hover, W.fly_until = tgt, True, now + dur + 1.2
                W.grounded = False
                ex['until'] = now + dur
                ex['state'] = 'wait'
                self.note('juggle_jump', now, who=who)
                return
            dur = W.atlas.total_ms(bt['anim']) / 1000.0 if bt['anim'] in W.atlas.anim else 0.4
            away = -1 if T.x >= W.x else 1
            W.play(bt['anim'], now, loop=False if bt['anim'] == 'backdash' else None, hold='idle')
            W.vx = away * (560.0 if bt['anim'] == 'backdash' else WALK)
            W.move_until = now + dur
            W.target = None
            ex['until'] = now + dur
            ex['state'] = 'wait'
            self.note('reset', now, who=who, move=bt['anim'])
            return
        if kind == 'emote':
            W.play(bt['anim'], now, loop=False, hold='idle')
            ex['until'] = now + W.atlas.total_ms(bt['anim']) / 1000.0 if bt['anim'] in W.atlas.anim else now + 0.5
            ex['state'] = 'wait'
            self.note('taunt', now, who=who)
            return
        # ---- an attack beat
        move = bt.get('anim')
        if move not in W.atlas.anim or T.down and kind != 'ultimate' and not T.meteor:
            ex['i'] += 1
            return
        juggling = bool(bt.get('juggle')) and not W.grounded
        if (kind not in ('counter', 'special') and not ex['air'] and not juggling and abs(W.x - T.x) > self._range_for(who, bt) * 1.4 + 30
                and now < ex['deadline']):
            # (a projectile flies to its target: V5 bounced a far special between approach and beat until the deadline)
            ex['state'] = 'approach'                               # the defender moved (knockback, reset): close in again
            ex['att'], ex['dfn'] = who, tgt
            return
        dx = T.x - W.x
        W.facing = 1 if dx >= 0 else -1
        if not T.down:
            T.facing = -W.facing
        W.target, W.vx = None, 0.0
        if juggling:
            W.chase, W.hover, W.fly_until = None, True, now + 1.2
            W.vy = 0.0
        outcome = bt.get('outcome', 'hit')
        sig = W.atlas.signature()['strike']                        # V6: a plain strike that would KO becomes the signature strike
        if (outcome == 'hit' and kind in ('strike', 'counter') and T.hp - arena_dmg(bt) <= 0 and sig and move != sig
                and not bt.get('juggle') and self.pick[who].used[sig] < choreo.MAX_PER_ROUND):
            move = sig
            bt = dict(bt, anim=move, dmg=max(bt.get('dmg') or 0, choreo.damage_of(W.atlas, move, 'strike')), hitstop=choreo.hitstop_ms(W.atlas, move, 'strike'))
            ex['beats'][ex['i']] = bt
            self.pick[who].note(move)
        t_c = now + rounds._contact_s(W.atlas, move)
        fx_list = []
        name = self._main_fx(W.atlas, move)
        dist = abs(dx)
        if kind in ('ultimate', 'super'):
            for off, fx_name, until in W.atlas.move_fx(move):
                lead = self.fxp.hit_frame_time(fx_name) if fx_name == move else 0.0
                fx_list.append([max(now, now + off - lead), fx_name, (now + until) if until else None])
            if kind == 'ultimate' and name:
                e = self.fx.get(name)
                k = self.fxp.res / float(e.res)
                spawn = [it[0] for it in fx_list if it[1] == name]
                if spawn:
                    if e.grow:
                        t_c = max(t_c, spawn[0] + e.grow['ms'] / 1000.0 * min(1.0, dist / max(1.0, e.grow['to_w'] * k)))
                    elif e.travel:
                        t_c = max(t_c, spawn[0] + max(0.0, dist - 40.0) / (e.travel['speed'] * k))
            self.cam.letterbox(now, t_c + 0.55)                     # V7: bars in for the wind-up
        elif kind == 'special':
            proj = f'{move}_proj'
            a = W.atlas.anim[move]
            spawn = now + W.atlas.start_ms(move, a.get('proj_frame', a.get('hit_frame', 0))) / 1000.0
            if self.fx.has_art(proj):
                e = self.fx.get(proj)
                speed = (e.travel['speed'] if e.travel else 320.0) * self.fxp.res / float(e.res)
                fx_list.append([spawn, proj, None])
                t_c = max(t_c, spawn + max(0.0, dist - 40.0) / speed)
                ex['proj'] = proj
        W.play(move, now, loop=False, hold='idle')
        if (kind in ('super', 'ultimate', 'special') and t_c - now >= rounds.BRACE_MIN_S and outcome != 'whiff'
                and bt.get('pre') != 'block' and not T.down):          # V6: a long wind-up: guard up (low guard when hurt)
            brace = 'crouch_block' if T.hp - ((bt.get('dmg') or 0) if outcome == 'hit' else 0) < rounds.WORRIED_HP and 'crouch_block' in T.atlas.anim else 'block'
            if brace in T.atlas.anim and T.hang is None and T.climb is None:
                T.play(brace, now + 0.12)
                self.note('brace', now, who=tgt, move=brace)
        hs = (bt.get('hitstop') or 0) / 1000.0
        ex.update(state='strike', who=who, tgt=tgt, beat=bt, contact=t_c, end=max(now + W.atlas.total_ms(move) / 1000.0, t_c + 0.25) + hs,
                  hit_done=False, fx_list=fx_list, pre_done=False, main=name)
        self.note('strike', now, who=who, move=move, move_kind=kind)
        if kind == 'ultimate':
            self.used_ult[who] = True
            self.note('ultimate', now, who=who, move=move)
        if ex['air']:
            self.note('air_exchange', now)

    def _tick_strike(self, ex, now):
        W, T = self.f[ex['who']], self.f[ex['tgt']]
        bt = ex['beat']
        for item in ex['fx_list']:
            if item[0] is not None and now >= item[0]:
                t_at, fx_name, until = item
                item[0] = None
                hand = W.atlas.hand(bt['anim'])
                inst = self.fxp.spawn(fx_name, now, W.x, W.y, W.facing, owner=ex['who'], hand=(hand[0] * SCALE, hand[1] * SCALE) if hand else None,
                                      fade_ms=(max(1.0, (until - now) * 1000.0) if until else None), tag=fx_name)
                if fx_name == ex.get('main') and bt['kind'] == 'ultimate':
                    self.note('beam', now, name=fx_name, grow=bool(inst.effect.grow))
                if ex.get('proj') == fx_name:
                    inst.vx = W.facing * abs(inst.vx or (320.0 * self.fxp.res / float(inst.effect.res)))
                    inst.fade_ms = max(1.0, (ex['contact'] - now + 0.05) * 1000.0)
                    ex['proj_inst'] = inst
        if not ex['pre_done'] and bt.get('pre') and now >= ex['contact'] - (0.15 if bt['pre'] == 'backdash' else 0.25):
            ex['pre_done'] = True
            if not T.down and T.hang is None and T.climb is None:
                if bt['pre'] == 'backdash':
                    T.play('backdash', now, loop=False, hold='idle')
                    T.vx = -W.facing * 640.0
                    T.move_until = now + 0.3
                    T.target = None
                else:
                    T.play(bt['pre'], now)
        if not ex['hit_done'] and now >= ex['contact']:
            ex['hit_done'] = True
            self._resolve_beat(ex, now)
            if self.phase != 'fight':
                return
        if now >= ex['end']:
            if self.exchange is ex:
                ex['i'] += 1
                ex['state'] = 'beat'
                if bt.get('kind') == 'counter':
                    ex['att'], ex['dfn'] = ex['who'], ex['tgt']

    def _resolve_beat(self, ex, now):
        W, T = self.f[ex['who']], self.f[ex['tgt']]
        bt = ex['beat']
        kind, move, outcome = bt.get('kind', 'strike'), bt['anim'], bt.get('outcome', 'hit')
        cx, cy = T.center()
        hs = (bt.get('hitstop') or 0) / 1000.0
        if outcome == 'whiff' or T.down and kind != 'ultimate' and not T.meteor:
            self.note('whiff', now, who=ex['who'], move=move)
            return
        traits = move_traits(W.atlas, move, bt)
        final = (outcome == 'hit' and T.hp - arena_dmg(bt) <= 0 and self._final(ex['who']))
        if final:                                                  # the finisher: a long freeze, then the fall in slow motion
            hs = max(hs, rounds.KO_HITSTOP_MS / 1000.0)
            for f in (W, T):
                f.slow = (now + hs, now + hs + rounds.SLOW_S, rounds.SLOW_K)
            self.final_ko = (now, ex['tgt'])
            self._finisher_camera(now, cx, cy, ex['who'], hs)
        if hs:
            for f in (W, T):
                f.stop = (now, now + hs)
        T.hang = T.climb = T.ledge_plan = None                     # a hit knocks it off the ledge
        T.pose = None
        if outcome in ('block', 'crouch_block', 'parry'):
            react = bt.get('react') or 'block_hit'
            T.play(react, now, loop=False, hold='idle')
            self.fxp.spawn_at('block_spark', now, cx + T.facing * 24, cy)
            d = arena_dmg(bt) * FD.PCT_PER_HP or choreo.damage_of(W.atlas, move, kind) * FD.PCT_PER_HP
            push = FD.shield_push_px(d) * ARENA_PUSH_K                 # V9: pushback and shieldstun grow with the blocked damage
            T.vx = W.facing * (push if outcome != 'parry' else 0.0)
            T.knocked_until = max(T.knocked_until, now + hs + FD.ms(FD.shieldstun_frames(d)) / 1000.0)
            self.note('block' if outcome != 'parry' else 'parry', now, who=ex['tgt'])
            self.forge.on_hit_landed(ex['who'], now)                  # a blocked forged weapon still cracks
            return
        dmg = arena_dmg(bt)
        fd = self._frame_data(ex, W, T, bt, kind, move, dmg)
        if not final and hs and fd['hitlag'] / 1000.0 > hs:          # V9: the hitlag grows with the damage (both freeze)
            hs = fd['hitlag'] / 1000.0
            for f in (W, T):
                f.stop = (now, now + hs)
        T.hp = max(0, T.hp - dmg)
        self.meter[ex['who']] += dmg
        self.meter[ex['tgt']] += dmg / 2.0
        if kind == 'super':
            self.meter[ex['who']] = 0.0
        self.hp_history.append((round(now, 3), ex['tgt'], T.hp))
        heavy = dmg >= 24
        beam = kind == 'ultimate' and self._reach(ex['who'], move) > 0
        down = (T.hp <= 0 or bt.get('down') or bt.get('react') == 'knockdown' or 'throw' in traits
                or (fd['tumble'] and not ex['air']))                   # V9: knockback past the tumble line knocks it down
        T.hover, T.fly_until, T.target = False, 0.0, None
        airborne = not T.grounded
        T.grounded = False
        if down:
            T.play('knockdown', now, loop=False, hold='ko' if T.hp <= 0 else 'knockdown')
            T.down = True
            vx, vy = fd['v']
            T.vx, T.vy = W.facing * (950.0 if beam else max(560.0, vx)), (0.0 if beam else min(-420.0, vy))   # V9: the launch arc
            T.knocked_until = now + max(1.2, hs + fd['stun'])
            if T.hp > 0:
                T.getup_at = now + hs + T.atlas.total_ms('knockdown') / 1000.0     # V6: springs up the moment the fall ends
            self.note('knockdown', now, who=ex['tgt'], ko=T.hp <= 0)
        else:
            T.play('hit_heavy' if heavy else 'hit', now, loop=False, hold='idle')
            vx, vy = fd['v']                                              # V9: knockback from damage, % and weight
            T.vx = W.facing * (950.0 if beam else max(200.0, vx))
            T.vy = 0.0 if beam else min(-80.0, vy)
            T.knocked_until = now + max(0.3, hs + fd['stun'])             # V9: hitstun proportional to the knockback
            T.recover_ok = True
        self._traits(ex, W, T, traits, bt, now, down, airborne or ex['air'] or bool(bt.get('juggle')))
        ix = cx
        if beam:                                                   # the impact burst sits at the beam's end, on the defender
            inst = next((i for i in self.fxp.active if i.tag == ex.get('main') and i.owner == ex['who']), None)
            if inst is not None:
                end = self.fxp.beam_end(inst, now)
                ix = min(cx, end) if W.facing > 0 else max(cx, end)
        self.fxp.spawn_at('hit_heavy' if heavy else 'hit_light', now, ix, cy, W.facing)
        self.fx_count += 1
        sh = choreo.move_shake(W.atlas, move)
        if sh:
            self.fxp.add_shake(now, sh['frames'], sh['amp'] * SCALE)
        elif fd['kb'] >= 40:                                               # V9: the screen shakes with the knockback
            self.fxp.add_shake(now, 2 + int(fd['kb'] // 60), min(4.0, fd['kb'] / 40.0) * SCALE)
        if kind == 'ultimate':
            imp = f'{move}_impact' if self.fx.has_art(f'{move}_impact') else 'explosion'
            self.fxp.spawn_at(imp, now, ix, cy, W.facing)
            if imp != 'explosion':
                self.fxp.spawn_at('explosion', now, ix, cy, W.facing)
            if self.flashes_on(now):
                self.fxp.flash_at(now, seconds=rounds.FLASH_MS / 1000.0)
            self.explosions += 1
            self.note('explosion', now)
            self.note('flash', now)
        if kind in ('super', 'ultimate') and not final:
            self.cam.punch(now, (W.x + T.x) / 2.0, cy)              # V7: the zoom punch on contact
            self.note('zoom', now)
        if kind in ('super', 'ultimate') or T.hp <= 0 or dmg >= 3 * choreo.DMG_PER_POWER:
            self._impact(now, ex['tgt'], cx, cy, W.facing)
        if ex['who'] == ex['att']:
            ex['hit'] = True
        self.note('hit', now, who=ex['tgt'], dmg=dmg, hp=T.hp, air=ex['air'])
        self.forge.on_hit_landed(ex['who'], now, heavy=heavy, final=final)
        if T.hp <= 0:
            self._end_round(now, ex['tgt'])

    def _frame_data(self, ex, W, T, bt, kind, move, dmg):
        """V9 platform-fighter frame data for an arena hit (framedata.py): the target's % grows by the hit, then knockback
        (damage, %, weight, the move's scaling / base), its launch velocity along the move's angle leaned by DI, the
        hitstun, the hitlag, and whether it tumbles."""
        tgt = ex['tgt']
        a = W.atlas.anim.get(move) or {}
        d = dmg * FD.PCT_PER_HP
        self.pct[tgt] += d
        s, base, ang = FD.move_kb(W.atlas.power(move, 1), a.get('height'), kind)
        if a.get('type') == 'spike':
            ang = FD.SPIKE_ANGLE
        ang = FD.di(ang, self.fd_rng)
        fam = (T.atlas.anim.get('riposte') or {}).get('family')
        kb = FD.knockback(self.pct[tgt], d, FD.weight_of(fam), s, base)
        v = FD.launch_speed(kb) * FD.FPS * ARENA_UNIT_PX                     # px / s at the moment of launch
        r = math.radians(ang)
        out = dict(kb=kb, pct=self.pct[tgt], angle=ang, v=(v * math.cos(r), -v * math.sin(r)), stun=FD.hitstun_ms(kb) / 1000.0,
                   hitlag=max(choreo.HITSTOP_FLOOR_MS, FD.hitlag_ms(dmg * FD.HITLAG_DMG_K)), tumble=FD.tumbles(kb))
        self.fd_log.append(dict(who=ex['who'], tgt=tgt, move=move, kind=kind, dmg=dmg, pct=round(self.pct[tgt], 2),
                                kb=round(kb, 2), stun=round(out['stun'], 3), tumble=out['tumble']))
        return out

    def _traits(self, ex, W, T, traits, bt, now, down, aerial):
        """V7: what a move's family does to the defender's flight (launch, throw, pull, boomerang, pound, meteor)."""
        tgt = ex['tgt']
        if aerial and down and T.y < self.stage.floor_y - 220 and self.rng.random() < self.I['meteor_p']:
            T.meteor = True                                        # spiked: straight down through the ledges
            T.vx, T.vy = W.facing * 160.0, 1900.0
            T.recover_ok = False
            self.note('meteor', now, who=tgt)
            return
        if 'launcher' in traits and not down and T.hp > 0:
            T.vx, T.vy = W.facing * 120.0, -1150.0                 # popped up: floats (juggle hang time)
            T.float_until = now + 1.0
            T.knocked_until = now + 0.9
            T.recover_ok = False
            self.note('launch', now, who=tgt)
        elif 'throw' in traits:
            T.vx, T.vy = W.facing * 1350.0, -480.0                 # hurled: into a wall, a window, or a long skid
            self.note('throw', now, who=tgt)
        elif 'pull' in traits and not down:
            T.vx = -W.facing * 900.0                               # dragged back in
            T.vy = -160.0
            T.pull_to = W.x + W.facing * REACH_PX
            self.note('pull', now, who=tgt)
        if 'boomerang' in traits and ex.get('proj_inst') is not None:
            inst = ex['proj_inst']
            back = self.fxp.spawn_at(inst.effect.name, now, inst.x, inst.y, -W.facing, owner=ex['who'], tag='boomerang')
            sp = abs(inst.vx) or 900.0
            back.vx = -W.facing * sp
            back.fade_ms = max(1.0, abs(inst.x - W.x) / sp * 1000.0)
            self.fx_count += 1
            self.note('boomerang', now, who=ex['who'])
        if 'pound' in traits and W.grounded:
            if abs(W.y - self.stage.floor_y) < 2:
                self._crater(now, T.x if abs(T.y - W.y) < 4 else W.x + W.facing * 60, 1700.0)
            else:
                win = self._ledge_window(W.x, W.y)
                if win is not None:
                    self._crack_window(win, now, W.x + W.facing * 50, W.y + 6, heavy=False)
            self.note('pound', now, who=ex['who'])

    def _finisher_camera(self, now, cx, cy, who, hs):
        """The match-deciding KO: letterbox, zoom punch, focus lines and a colour flash in the winner's accent."""
        self.cam.letterbox(now, now + hs + rounds.SLOW_S + 0.4)
        self.cam.punch(now, cx, cy, hold=hs + 0.25)
        self.cam.radial = (now, now + hs + rounds.SLOW_S + 0.15, cx, cy)
        if self.flashes_on(now):
            self.cam.color_flash(now, self.f[who].atlas.accent, alpha=0.3, secs=0.14)
        self.note('radial', now)
        self.note('zoom', now)

    def flashes_on(self, now):
        """control.json `flashes` (impact frames and white flashes), default on; read at most every 2 s, so the arena
        loop no longer has to override the effect player from outside on every frame."""
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

    BOOST_POLL_S = 0.5

    def _boost_poll(self, now, buses=None, wall=None):
        """V9: the task-finished boost, across processes.  The slot whose agent went working -> done publishes a short-lived
        marker on its bus file ({'id', 'left'}: brain.boost_marker); the arena reads both bus files every 0.5 s (only in the
        real process, i.e. with a cfg) and queues that slot, so its next exchange opens with the signature super, as the
        taskbar does.  Each marker id is used once.  `buses` / `wall` are for tests."""
        if buses is None and not self.cfg:
            return
        if now - self._boost_read < self.BOOST_POLL_S and now >= self._boost_read:
            return
        self._boost_read = now
        import time as _time
        wall = _time.time() if wall is None else wall
        if buses is None:
            try:
                from . import bus
                buses = {s: bus.read(s, now=wall) for s in 'ab'}
            except Exception:
                return
        for s in 'ab':
            d = buses.get(s) or {}
            m = d.get('boost') if isinstance(d, dict) else None
            if not isinstance(m, dict) or not m.get('id'):
                continue
            try:
                until = float(d.get('ts', 0)) + float(m.get('left', 0))
            except (TypeError, ValueError):
                continue
            key = (s, str(m['id']))
            if key in self.boost_seen or until <= wall or self.phase in ('winner', 'exit', 'done'):
                continue
            self.boost_seen.add(key)
            if s not in self.boost:
                self.boost.append(s)
            self.boost_any.add(s)
            self.note('boost', now, who=s)

    def _forge_poll(self, now):
        """control.json `forge` read every 2 s in the real process: switched off mid-match, the grab is dropped at once."""
        if not self.forge.enabled or self.cfg is None or not self.cfg or now - self._forge_read < 2.0:
            return
        self._forge_read = now
        try:
            from . import control
            on = control.forge_on(default=self.cfg.get('forge', True))
        except Exception:
            on = True
        if not on:
            self.forge.disable(now)
            self.note('forge_off', now)

    def _forge_try(self, att, dfn, k, now):
        """V8 desktop weapons: this exchange is a forge (forge.py decides who and when) -> True when one started."""
        who = self.forge.want(att, dfn, k, now)
        if who is None:
            return False
        other = 'b' if who == 'a' else 'a'
        job = self.forge.start(who, self.forge.kind_for(who), now)
        if job is None:
            return False
        self.exchange = dict(att=who, dfn=other, beats=[], i=0, state='forge', t=now, deadline=now + 4.0, air=False, kind='forge', opener=None,
                             range_after='far', hit=False, job=job)
        return True

    def _forge_hit(self, att, dfn, now, dmg=10):
        """A thrown slab lands: a heavy hit through the same bookkeeping as any hit (HP, meter, KO, the finisher camera)."""
        A, D = self.f[att], self.f[dfn]
        if D.hp <= 0 or self.phase != 'fight':
            return
        cx, cy = D.center()
        D.hp = max(0, D.hp - dmg)
        self.meter[att] += dmg
        self.meter[dfn] += dmg / 2.0
        self.hp_history.append((round(now, 3), dfn, D.hp))
        away = 1.0 if D.x >= A.x else -1.0
        D.hang = D.climb = D.ledge_plan = None
        D.pose, D.hover, D.fly_until, D.target, D.grounded = None, False, 0.0, None, False
        hs = 0.1
        if D.hp <= 0:
            D.play('knockdown', now, loop=False, hold='ko')
            D.down = True
            D.vx, D.vy = away * 700.0, -480.0
            D.knocked_until = now + 1.2
            if self._final(att):
                hs = rounds.KO_HITSTOP_MS / 1000.0
                for f in (A, D):
                    f.slow = (now + hs, now + hs + rounds.SLOW_S, rounds.SLOW_K)
                self.final_ko = (now, dfn)
                self._finisher_camera(now, cx, cy, att, hs)
        else:
            D.play('hit_heavy', now, loop=False, hold='idle')
            D.vx, D.vy = away * 520.0, -260.0
            D.knocked_until = now + 0.6
            D.recover_ok = True
        D.stop = (now, now + hs)
        self.fxp.spawn_at('hit_heavy', now, cx, cy, int(away))
        self.fx_count += 1
        self._impact(now, dfn, cx, cy, int(away))
        self.note('hit', now, who=dfn, dmg=dmg, hp=D.hp, air=False)
        if D.hp <= 0:
            self._end_round(now, dfn)

    def _impact(self, now, tgt, cx, cy, facing):
        """V6 impact frames for IMPACT_S: the fx `impact` on the struck fighter when the sheet has it, and both fighters drawn
        as silhouettes (struck = white, striker = dark).  Only the two sprite rects change, never a full-screen frame, so
        it stays inside the arena's CPU budget.  Nothing at all with flashes off."""
        if not self.flashes_on(now):
            return
        self.impact = (now, now + IMPACT_S, tgt)
        if self.fx.has_art('impact'):
            self.fxp.spawn_at('impact', now, cx, cy, facing)                  # the art's own 100-160 ms
        self.note('impact', now, who=tgt)

    def _end_exchange(self, ex, now):
        self.exchange = None
        self.last_att, self.last_hit = ex['att'], ex['hit']
        self.forge.on_exchange_end((ex['att'], ex['dfn']), now)
        for s in 'ab':
            f = self.f[s]
            if f.hover or f.chase:
                f.fly_until = 0.0
                f.target = None
            f.hover = False
            f.chase = None
            if ex['air']:
                f.fly_until = 0.0
                f.target = None
                f.air_plan = None
        self.cooldown_until = now + (self.rng.uniform(*COOLDOWN_CLOSE) if ex['range_after'] == 'close' else self.rng.uniform(*COOLDOWN_FAR))

    def _resolve(self, ex, now):
        """Compatibility shim for the V4 tests: resolve a bare exchange dict as a landed strike beat."""
        beat = dict(who='att', kind=ex.get('kind', 'strike'), anim=ex['move'], dmg=ex.get('dmg', 12), outcome='hit', pre=None,
                    react='hit_heavy' if ex.get('dmg', 12) >= 24 else 'hit', hitstop=0, knock=0, down=False)
        ex.update(who=ex['att'], tgt=ex['dfn'], beat=beat, air=False, main=self._main_fx(self.f[ex['att']].atlas, ex['move']))
        self._resolve_beat(ex, now)

    def _end_round(self, now, ko_loser):
        if ko_loser is not None:
            winner = 'b' if ko_loser == 'a' else 'a'
            self.banner = ('ko', now + 1.5, None)
            self.fxp.spawn_at('ko_stars', now + 0.7, *self.f[ko_loser].center(), fade_ms=3200)   # gone before the next round
        else:
            ha, hb = self.f['a'].hp, self.f['b'].hp
            winner = ('a' if self.rng.random() < 0.5 else 'b') if ha == hb else ('a' if ha > hb else 'b')
            self.banner = ('time', now + 1.2, None)                # V6: called on time, and the loser slumps
            L = self.f['b' if winner == 'a' else 'a']
            sl = next((n for n in rounds.SLUMP if n in L.atlas.anim), None)
            if sl and not L.down and L.hang is None and L.climb is None:
                L.target, L.vx = None, 0.0
                L.play(sl, now + 0.3, loop=False, hold=HOLD_LAST)
        self.comeback_for = 'b' if winner == 'a' else 'a'
        for j in [j for j in self.forge.jobs if not j.setpiece]:   # a forge cut short by the round's end
            self.forge._finish(j, now, release=True)
        if ko_loser is not None:
            self.forge.shatter(ko_loser, now)                       # the KO'd fighter's weapon breaks as it falls
        self.wins[winner] += 1
        self.rounds.append(dict(n=self.round, winner=winner, ko=ko_loser is not None, hp={s: self.f[s].hp for s in 'ab'}, dur=round(now - self.round_t0, 2)))
        self.exchange = None
        for s in 'ab':
            f = self.f[s]
            if self.sp is None or self.sp.done:
                f.pose = None
            f.jitter, f.chase = 0, None
            if f.hover or f.air_plan:
                f.hover, f.air_plan, f.fly_until, f.target = False, None, 0.0, None
        w = self.f[winner]
        w.target, w.vx = None, 0.0
        if not (ko_loser is not None and self._match_over()) and w.hang is None and w.climb is None and self.sp is None:   # the final KO goes straight to the pose
            w.play('taunt', now + 0.3, loop=False, hold='idle')
        self.ko_loser = ko_loser
        self.note('round', now, n=self.round, winner=winner, ko=ko_loser is not None)
        self._enter('round_end', now)

    # ---- set pieces (V7, arena_setpieces.py)
    def _setpiece_try(self, att, dfn, k, now):
        owed = not self.endless and self.sp_played < 2 and (max(self.wins.values()) >= self.to_win - 1 or
                                                            (self.sp_played < self.round and now - self.round_t0 > 5.0))
        if (k < 1 and not (owed and self.round > 1)) or self.sp is not None or now - self.round_t0 > rounds.ROUND_CAP_S - 5.0 or now - self.sp_last < 5.0:
            return False
        if not self.endless and self.sp_played >= self.sp_target:
            return False
        A, D = self.f[att], self.f[dfn]
        if A.down or D.down or A.hp <= 0 or D.hp <= 0 or D.hang or D.climb or A.hang or A.climb or D.hover or A.hover:
            return False
        p = self.I['sp_p'] if self.endless else max(self.I['sp_p'], min(0.85, 0.3 * (self.sp_target - self.sp_played)))   # the match owes 2-4
        if owed:
            p = 1.0                                            # this round may be the last: the match still owes its two
        if self.rng.random() >= p:
            return False
        names = ['vanishing_cut', 'flurry'] + (['stance_finisher'] * (3 if D.hp <= SP.SETPIECES['stance_finisher']['dmg'] else 1))
        first = names[self.rng.randrange(len(names))]
        for name in [first] + [n for n in SP.SETPIECES if n != first]:
            plan = self._setpiece_plan(name, A, D)
            if plan is not None:
                self._start_sp_setup(name, att, dfn, plan, now)
                return True
        return False

    def _setpiece_plan(self, name, A, D):
        """-> (s, D0, ground y) so every mark of the set piece fits on the defender's platform and the monitor, else None."""
        spec = SP.SETPIECES[name]
        floor = (0, self.stage.w, self.stage.floor_y)
        here = next((p for p in self.stage.platforms() if p[0] - 10 <= D.x <= p[1] + 10 and abs(p[2] - D.y) < 2), None) if D.grounded else None
        for p in ([here] if here and here != floor else []) + [floor]:
            r = self._setpiece_fit(spec, A, D, p)
            if r is not None:
                return r
        return None

    def _setpiece_fit(self, spec, A, D, p):
        plat, y = (p[0], p[1]), p[2]
        lo, hi = max(plat[0] + 30, 80), min(plat[1] - 30, self.stage.w - 80)
        gap, (s0, s1) = spec['gap'], spec['span']
        best = None
        for s in ((1, -1) if D.x >= A.x else (-1, 1)):
            if s > 0:
                dlo, dhi = lo + gap - s0, hi + gap - s1
            else:
                dlo, dhi = lo - gap + s1, hi - gap + s0
            if dlo > dhi:
                continue
            d0 = min(max(D.x, dlo), dhi)
            if abs(d0 - D.x) <= 420 and (best is None or abs(d0 - D.x) < abs(best[1] - D.x)):
                best = (s, d0, y)
        return best

    def _start_sp_setup(self, name, att, dfn, plan, now):
        s, d0, y = plan
        A, D = self.f[att], self.f[dfn]
        for b, x in ((A, d0 - s * SP.SETPIECES[name]['gap']), (D, d0)):
            self._release(b)
            if abs(b.x - x) > 6 or abs(b.y - y) > 2:
                b.target, b.fly_until, b.hover = (x, y), now + 1.2, False
                b.fly_speed = 1500.0
                away = (x - b.x) * s > 0 if b is D else False
                b.play('backdash' if away and 'backdash' in b.atlas.anim else 'dash', now, loop=False, hold='idle')
        self.exchange = dict(att=att, dfn=dfn, beats=[], i=0, state='sp_setup', t=now, deadline=now + 1.2, air=False, kind='setpiece', opener=None,
                             range_after='far', hit=False, sp=dict(name=name, s=s, d0=d0, y=y))
        self.note('setpiece_setup', now, name=name)

    def _tick_sp_setup(self, ex, now):
        A, D = self.f[ex['att']], self.f[ex['dfn']]
        if any(b.down for b in (A, D)):
            self.exchange = None
            return
        if all(b.target is None for b in (A, D)) or now >= ex['deadline']:
            if any(b.target is not None for b in (A, D)):
                self.exchange = None                               # could not reach the marks: back to the procedural fight
                for b in (A, D):
                    b.target, b.fly_until = None, 0.0
                return
            sp = ex['sp']
            A.fly_speed = D.fly_speed = None
            A.facing, D.facing = sp['s'], -sp['s']
            origin = sp['d0'] - sp['s'] * SP.SETPIECES[sp['name']]['gap']
            self.sp = SP.SetPiece(self, sp['name'], ex['att'], ex['dfn'], sp['y'], origin, sp['s'], now)
            self.sp_played += 1
            ex['state'] = 'setpiece'
            self.note('setpiece', now, name=sp['name'], element=self.sp.el['A'])

    def _setpiece_hit(self, sp, p, now):
        """A set piece's cut lands: HP, meter, knock-down, KO and the finisher camera, the same bookkeeping as any hit."""
        a, d = sp.slot['A'], sp.slot['D']
        A, D = self.f[a], self.f[d]
        if D.hp <= 0 or self.phase != 'fight':
            return
        dmg = int(p['dmg'])
        if not p.get('final') and D.hp - dmg <= 0:
            dmg = max(0, D.hp - 1)                                 # the flurry's small cuts never KO: the big cut does
        D.hp = max(0, D.hp - dmg)
        self.meter[a] += dmg
        self.meter[d] += dmg / 2.0
        self.hp_history.append((round(now, 3), d, D.hp))
        react = p.get('react', 'recoil')
        if react in ('stagger', 'recoil') and D.hp > 0:
            D.pose = SP.resolve_slot(D.atlas, react)
            D.x += sp.s * p.get('push', 0)
            self.note('hit', now, who=d, dmg=dmg, hp=D.hp, air=False)
            return
        sp.released.add('D')
        D.last_crack = now + 0.6                                   # the cut is the moment: no glass spray on top of it
        cx, cy = D.center()
        D.pose, D.alpha = None, None
        D.hover, D.fly_until, D.target, D.grounded = False, 0.0, None, False
        D.down = True
        D.play('knockdown', now, loop=False, hold='ko' if D.hp <= 0 else 'knockdown')
        away = 1.0 if D.x >= A.x else -1.0                         # always away from the attacker (it may be behind)
        D.vx, D.vy = away * 480.0, -420.0
        D.facing = -int(away)
        D.knocked_until = now + 1.2
        hs = 0.12
        if D.hp <= 0 and self._final(a):
            hs = rounds.KO_HITSTOP_MS / 1000.0
            for f in (A, D):
                f.slow = (now + hs, now + hs + rounds.SLOW_S, rounds.SLOW_K)
            self.final_ko = (now, d)
            self._finisher_camera(now, cx, cy, a, hs)
        elif D.hp > 0:
            D.getup_at = now + hs + D.atlas.total_ms('knockdown') / 1000.0
        for f in (A, D):
            f.stop = (now, now + hs)
        if self.impact is None or self.impact[1] < now:
            self._impact(now, d, cx, cy, sp.s)
        self.fxp.spawn_at('hit_heavy', now, cx, cy, sp.s)
        self.fx_count += 1
        self.note('knockdown', now, who=d, ko=D.hp <= 0)
        self.note('hit', now, who=d, dmg=dmg, hp=D.hp, air=False)
        if D.hp <= 0:
            self._end_round(now, d)

    # ---- beam clash (V7)
    def _clash_move(self, atlas, prefer_ult):
        sig = atlas.signature()
        for m in ((sig['ultimate'], sig['super']) if prefer_ult else (sig['super'], sig['ultimate'])):
            if m and m in atlas.anim:
                return m
        return None

    def _clash_ok(self, att, dfn, first, now):
        fired = first.get('kind') in ('super', 'ultimate') and first.get('outcome') != 'whiff'
        charged = self.k_round >= 3 and min(self.meter[att], self.meter[dfn]) >= CLASH_METER    # both charged: both fire at once
        if not (fired or charged):
            return False
        if self.clashes >= self.I['clash_max'] or now - self.round_t0 > rounds.ROUND_CAP_S - 6.0:
            return False
        A, D = self.f[att], self.f[dfn]
        if A.down or D.down or A.hp <= 0 or D.hp <= 0 or D.hang or D.climb:
            return False
        if self._clash_move(D.atlas, False) is None or self._clash_move(A.atlas, False) is None:
            return False
        return self.rng.random() < self.I['clash_p']

    def _start_clash(self, att, dfn, first, now):
        A, D = self.f[att], self.f[dfn]
        left, right = ('a', 'b') if self.f['a'].x <= self.f['b'].x else ('b', 'a')
        mid = min(max((A.x + D.x) / 2.0, CLASH_GAP + 120.0), self.stage.w - CLASH_GAP - 120.0)
        y = max(float(MIN_PLATFORM_Y) + 40.0, min(min(A.y, D.y), self.stage.floor_y) - 300.0)
        fired = first.get('kind') in ('super', 'ultimate') and first['anim'] in A.atlas.anim
        moves = {att: first['anim'] if fired else self._clash_move(A.atlas, False), dfn: self._clash_move(D.atlas, False)}
        if not fired:
            first = dict(first, kind='super', anim=moves[att])
        self.meter[att] = self.meter[dfn] = 0.0                # both spent their charge on it
        kinds = {att: first['kind'], dfn: 'ultimate' if moves[dfn] == D.atlas.signature()['ultimate'] and moves[dfn] != D.atlas.signature()['super'] else 'super'}
        if first['kind'] == 'ultimate':
            self.used_ult[att] = True
            self.note('ultimate', now, who=att, move=moves[att])
        for s, x in ((left, mid - CLASH_GAP), (right, mid + CLASH_GAP)):
            b = self.f[s]
            self._release(b)
            b.target, b.hover, b.fly_until = (x, y), True, now + 6.0
            b.grounded = False
            b.facing = 1 if s == left else -1
            b.play('dash' if abs(b.x - x) > 160 else 'jump', now, loop=False, hold='idle')
        p_att = self.p_left if att == 'a' else 1.0 - self.p_left
        p_att = 0.5 * p_att + 0.5 * (0.5 + (A.hp - D.hp) / 200.0)
        winner = att if self.rng.random() < p_att else dfn
        struggle = 2.0 + 0.3 * (self.I['fx'] > 1.0)
        self.exchange = dict(att=att, dfn=dfn, beats=[], i=0, state='clash', t=now, deadline=now + 12.0, air=False, kind='clash', opener=None,
                             range_after='far', hit=False, stage='setup', st0=now, left=left, right=right, mid=mid, y=y, moves=moves,
                             kinds=kinds, winner=winner, x_c=mid, fronts={left: None, right: None}, struggle=struggle,
                             phase0=self.rng.uniform(0, 6.28), next_spark=now)
        self.clashes += 1
        self.cam.letterbox(now, now + 6.0)
        self.note('clash', now, who=att)

    def _clash_hand(self, s, ex):
        """Where the beam leaves the hand: the move's `hand` point at the hit-frame pose, else chest height."""
        b = self.f[s]
        h = b.atlas.hand(ex['moves'][s])
        if h is not None:
            return b.x + b.facing * h[0] * SCALE, b.y + h[1] * SCALE
        return b.x + b.facing * 70.0, b.y - 120.0

    def _tick_clash(self, ex, now):
        L, R = self.f[ex['left']], self.f[ex['right']]
        el = now - ex['st0']
        st = ex['stage']
        if st == 'setup':
            arrived = all(b.target is None or math.hypot(b.x - b.target[0], b.y - b.target[1]) < 8 for b in (L, R))
            if arrived or el > 1.3:
                for s in (ex['left'], ex['right']):
                    b = self.f[s]
                    b.target, b.vx, b.vy = None, 0.0, 0.0
                    b.hover, b.fly_until = True, now + 8.0
                    b.play('powerup' if 'powerup' in b.atlas.anim else 'idle', now)
                ex.update(stage='charge', st0=now)
                self.note('clash_charge', now)
        elif st == 'charge':
            for b in (L, R):
                b.fly_until = now + 8.0
            if el >= 0.5:
                for s in (ex['left'], ex['right']):
                    b = self.f[s]
                    m = ex['moves'][s]
                    b.pose = (m, SP.frame_of(b.atlas, m, 'hit'))
                    b.target = (b.x, b.y)
                    hx, hy = self._clash_hand(s, ex)
                    ex['fronts'][s] = hx
                ex['hand_y'] = (self._clash_hand(ex['left'], ex)[1] + self._clash_hand(ex['right'], ex)[1]) / 2.0
                ex.update(stage='fire', st0=now)
                self.fxp.add_shake(now, 4, 3 * self.I['shake_k'])
                self.note('clash_fire', now)
        elif st == 'fire':
            v = 2600.0 * min(0.05, max(0.0, now - ex.get('last', now)))
            fl, fr = ex['fronts'][ex['left']], ex['fronts'][ex['right']]
            fl, fr = min(ex['mid'], fl + v), max(ex['mid'], fr - v)
            ex['fronts'] = {ex['left']: fl, ex['right']: fr}
            if fl >= ex['mid'] and fr <= ex['mid']:
                ex.update(stage='struggle', st0=now, x_c=ex['mid'])
                self.fxp.spawn_at('hit_heavy', now, ex['mid'], ex['hand_y'])
                self.fxp.add_shake(now, 8, 6 * self.I['shake_k'])
                self.fx_count += 1
                self.note('clash_meet', now)
        elif st == 'struggle':
            T = ex['struggle']
            k = el / T
            sway = 70.0 * math.sin(el * 2 * math.pi * 0.85 + ex['phase0']) * (1.0 - 0.5 * k)
            loser_dir = 1.0 if ex['winner'] == ex['left'] else -1.0
            bias = loser_dir * 150.0 * _ease_in_out((k - 0.6) / 0.4) if k > 0.6 else 0.0
            ex['x_c'] = ex['mid'] + sway + bias + self.rng.uniform(-4, 4)
            ex['fronts'] = {ex['left']: ex['x_c'], ex['right']: ex['x_c']}
            jit = 2 if int(now * 30) % 2 else -2
            for b in (L, R):
                b.fly_until = now + 8.0
                b.jitter = jit
            if now >= ex['next_spark']:
                ex['next_spark'] = now + 0.06 / self.I['fx']
                for _ in range(2):
                    a = self.rng.uniform(0, 2 * math.pi)
                    sp = self.rng.uniform(260, 620)
                    self._particle(_spark_img(self.rng.randrange(4)), ex['x_c'], ex['hand_y'] + self.rng.uniform(-14, 14), math.cos(a) * sp,
                                   math.sin(a) * sp - 120, 900.0, now + self.rng.uniform(0.25, 0.45), rotate=a)
            if int(el * 10) != int((el - 1 / 30.0) * 10):
                self.fxp.add_shake(now, 3, (2.0 + 2.0 * k) * self.I['shake_k'])      # mash-shake: the whole overlay trembles
            if el >= T:
                ex.update(stage='push', st0=now, push_from=ex['x_c'])
                for b in (L, R):
                    b.jitter = 0
                self.note('clash_push', now, who=ex['winner'])
        elif st == 'push':
            loser = 'b' if ex['winner'] == 'a' else 'a'
            Lb = self.f[loser]
            end = Lb.x - Lb.facing * 10.0
            k = _ease_out(el / 0.22)
            x = ex['push_from'] + (end - ex['push_from']) * k
            ex['fronts'] = {ex['winner']: x, loser: None}
            if el >= 0.22:
                self._clash_hit(ex, now)
                ex.update(stage='fade', st0=now)
        elif st == 'fade':
            if el >= 0.3:
                self._end_clash(ex, now)
                self.exchange = None
                self.last_att, self.last_hit = ex['winner'], True
                self.cooldown_until = now + self.rng.uniform(*COOLDOWN_FAR)
        ex['last'] = now

    def _clash_hit(self, ex, now):
        w = ex['winner']
        l = 'b' if w == 'a' else 'a'
        W, T = self.f[w], self.f[l]
        kind = ex['kinds'][w]
        dmg = choreo.DMG_ULTIMATE if kind == 'ultimate' else int(round(choreo.DMG_SUPER * ARENA_DMG_K))
        cx, cy = T.center()
        final = T.hp - dmg <= 0 and self._final(w)
        hs = rounds.KO_HITSTOP_MS / 1000.0 if final else 0.16
        T.pose, T.jitter, T.hover, T.fly_until, T.target = None, 0, False, 0.0, None
        T.hp = max(0, T.hp - dmg)
        self.meter[w] += dmg
        self.hp_history.append((round(now, 3), l, T.hp))
        T.play('knockdown', now, loop=False, hold='ko' if T.hp <= 0 else 'knockdown')
        T.down, T.grounded = True, False
        T.vx, T.vy = W.facing * 980.0, -260.0
        T.knocked_until = now + 1.2
        if T.hp > 0:
            T.getup_at = now + hs + T.atlas.total_ms('knockdown') / 1000.0
        for f in (W, T):
            f.stop = (now, now + hs)
        if final:
            for f in (W, T):
                f.slow = (now + hs, now + hs + rounds.SLOW_S, rounds.SLOW_K)
            self.final_ko = (now, l)
            self._finisher_camera(now, cx, cy, w, hs)
        else:
            self.cam.punch(now, cx, cy)
            self.note('zoom', now)
            if self.flashes_on(now):
                self.cam.color_flash(now, W.atlas.accent)
        self.fxp.spawn_at('explosion', now, cx, cy, W.facing)
        self.fxp.spawn_at('hit_heavy', now, cx, cy, W.facing)
        self.fx_count += 2
        self.explosions += 1
        self._impact(now, l, cx, cy, W.facing)
        self.note('explosion', now)
        if self.flashes_on(now) and self.I['color_flash']:
            self.note('flash', now)                                # every explosion that flashes says so (the colour flash)
        self.note('clash_win', now, who=w)
        self.note('hit', now, who=l, dmg=dmg, hp=T.hp, air=True)
        if T.hp <= 0:
            self._end_round(now, l)

    def _end_clash(self, ex, now):
        for s in 'ab':
            b = self.f[s]
            b.pose, b.jitter = None, 0
            if not b.down:
                b.hover, b.fly_until, b.target = False, 0.0, None
                b.play('jump', now, loop=False, hold='idle')
        self.cam.unbox(now)

    # ---- physics
    def _move(self, b, now, dt):
        if dt <= 0 or b.stopped(now):
            return                                                 # hitstop: the whole body stands still
        dt *= b.speed(now)                                         # V6: the finisher's fall plays in slow motion
        fighting = self.phase in ('fight', 'round_end')
        if b.climb is not None:
            self._climb_step(b, now)
            return
        if b.hang is not None:
            h = b.hang
            el = now - h['t0']
            b.y = h['y'] + HANG_DY + 7.0 * math.exp(-el * 9.0) * math.sin(el * 26.0)    # the catch: a small damped bob, no pop
            if now >= h['until'] and self.phase in ('fight', 'round_end', 'intro', 'winner'):
                b.y = h['y'] + HANG_DY
                self._start_climb(b, now)
            return
        if b.dive_at is not None and now >= b.dive_at:
            b.dive_at = None                                       # outro: the dive back into the taskbar
            b.vy = 1500.0
            b.dash_until = now + 0.6
        if b.chase is not None:
            T = self.f[b.chase]
            b.target = (T.x - b.facing * REACH_PX, T.y)
            b.fly_until = max(b.fly_until, now + 0.2)
        if now < b.move_until and b.target is None and not b.down:
            b.x += b.vx * dt                                       # a reset step keeps its velocity for the anim's length
            b.x = max(40.0, min(self.stage.w - 40.0, b.x))
            return
        if b.air_plan is not None and not b.down:
            self._air_plan(b, now)
        flying = now < b.fly_until and (b.target is not None or b.hover) and not b.down
        if b.target is not None and now >= b.knocked_until and not b.down:
            tx, ty = b.target
            dx, dy = tx - b.x, ty - b.y
            dist = math.hypot(dx, dy)
            if dist < 6:
                b.x, b.vx = tx, 0.0
                if flying:
                    b.y, b.vy = ty, 0.0
                    if b.ledge_plan is not None:
                        self._start_hang(b, now, *b.ledge_plan)
                        return
                    if b.hover:
                        return                                     # stays up there (air-to-air)
                    b.grounded = ty >= self.stage.floor_y - 1 or any(x0 <= tx <= x1 and abs(y - ty) < 2 for x0, x1, y in self.stage.platforms())
                    b.fly_until = 0.0
                    if b.grounded:
                        self._land_fx(b, now, 700.0)
                b.target = None
                if b.arrive_play is not None:
                    b.play(b.arrive_play[0], now, loop=False, hold=b.arrive_play[1])
                    b.arrive_play = None
                elif b.anim in ('walk', 'dash', 'jump'):
                    b.play('idle', now)
            elif flying:
                sp = FLY if dist > 200 else max(260.0, dist * 4.0)
                if b.fly_speed:
                    sp = min(b.fly_speed, max(dist * 14.0, 200.0))
                b.vx, b.vy = dx / dist * sp, dy / dist * sp
                b.grounded = False
                if sp > 700:
                    b.dash_until = now + 0.1
                    if not b.trail or now - b.trail[-1][0] >= TRAIL_EVERY_S:
                        b.trail.append((now, b.drawn_anim(), b.frame(now)[0], b.facing, b.x, b.y))
            else:
                b.vx = math.copysign(min(WALK, abs(dx) / max(dt, 1e-3)), dx) if abs(dx) > 2 else 0.0
                if dy < -40 and b.grounded:                     # the target is higher: jump
                    b.vy = JUMP_VY
                    b.grounded = False
                    b.play('jump', now, loop=False, hold='idle')
                if b.grounded and b.anim == 'idle' and abs(b.vx) > 1:
                    b.play('walk', now)
                b.facing = 1 if dx > 0 else -1 if dx < 0 else b.facing
        if not flying:
            if not b.grounded:
                g = GRAVITY * (LAUNCH_FLOAT_K if now < b.float_until and b.vy > -400 else 1.0)
                b.vy = min(MAX_FALL, b.vy + g * dt)
            elif b.target is None:
                self._friction(b, now, dt)
        if b.pull_to is not None:
            if (b.vx > 0 and b.x >= b.pull_to) or (b.vx < 0 and b.x <= b.pull_to) or abs(b.vx) < 30:
                b.vx, b.pull_to = 0.0, None
        y_prev, x_prev = b.y, b.x
        b.x += b.vx * dt
        b.y += b.vy * dt
        if (abs(b.vx) > 650 or abs(b.vy) > 1100) and not flying and (not b.trail or now - b.trail[-1][0] >= TRAIL_EVERY_S):
            b.trail.append((now, b.drawn_anim(), b.frame(now)[0], b.facing, b.x, b.y))
            if abs(b.vx) > 900 or b.meteor:
                b.dash_until = now + 0.1
        # walls (and the ceiling: nobody leaves through the HUD)
        if self.phase != 'exit':
            m = 40
            if b.x < m or b.x > self.stage.w - m:
                side = -1 if b.x < m else 1
                b.x = float(m) if side < 0 else float(self.stage.w - m)
                into = b.vx * side
                if fighting and into > WALL_BOUNCE_V and (now < b.knocked_until or b.down):
                    self._wall_bounce(b, now, side, b.x + side * 30, b.center()[1])
                else:
                    b.vx = -side * abs(b.vx) * 0.3 if into > 0 else b.vx
            top = float(MIN_PLATFORM_Y)
            if b.y < top:
                b.y = top
                if b.vy < 0:
                    b.vy = 0.0
                if b.target is not None and b.target[1] < top:
                    b.target = (b.target[0], top)
        # landing (falling through a platform's top edge), not while flying or exiting
        if not flying and self.phase != 'exit' and b.vy >= 0:
            best = None
            floor = self.stage.floor_y
            for x0, x1, y in self.stage.platforms():
                if x0 - 10 <= b.x <= x1 + 10 and y_prev <= y <= b.y + 0.001:
                    if b.meteor and y < floor - 0.5:
                        self._meteor_through(b, now, x0, x1, y)
                        continue
                    if best is None or y < best:
                        best = y
            if best is not None:
                landed_from, vx0 = b.vy, b.vx
                b.y, b.vy, b.grounded = best, 0.0, True
                b.recover_ok = False
                b.float_until = 0.0
                if b.meteor or (fighting and landed_from >= CRATER_V and abs(best - floor) < 1):
                    self._meteor_land(b, now, landed_from)
                else:
                    self._land_fx(b, now, landed_from)
                if fighting and abs(vx0) > SKID_V and (now < b.knocked_until or b.down):
                    if not b.skid:
                        self.note('skid', now, who=b.slot, on='floor' if abs(best - floor) < 1 else 'ledge')
                    b.skid = True
                if b.anim in ('jump', 'dash') and not b.down:
                    b.play('idle', now)
            elif fighting:
                self._ledge_grab(b, now, y_prev)
                self._recovery(b, now)
        elif not flying and b.grounded:
            on = any(x0 - 10 <= b.x <= x1 + 10 and abs(y - b.y) < 2 for x0, x1, y in self.stage.platforms())
            if not on:
                b.grounded = False
                if b.skid:
                    b.skid = False
                    b.recover_ok = not b.down
                    self.note('skid_off', now, who=b.slot)
        elif self.phase == 'exit' and y_prev < self.stage.floor_y <= b.y and b.vy > 0:
            self._burst_ring(now, b.x, self.stage.floor_y)        # back into the taskbar
        while b.trail and now - b.trail[0][0] > AFTERIMAGE_S:
            b.trail.popleft()

    def _friction(self, b, now, dt):
        if b.skid:
            dv = SKID_F * dt
            if abs(b.vx) <= dv + 30:
                b.vx, b.skid = 0.0, False
            else:
                b.vx -= math.copysign(dv, b.vx)
                if now - b.last_spark >= 0.045:
                    b.last_spark = now
                    self._skid_fx(b, now)
        elif now < b.knocked_until or b.down:
            dv = KNOCK_F * dt
            b.vx = 0.0 if abs(b.vx) <= dv else b.vx - math.copysign(dv, b.vx)
        elif now >= b.knocked_until:
            b.vx *= max(0.0, 1.0 - 8.0 * dt)
            if abs(b.vx) < 5:
                b.vx = 0.0

    def _skid_fx(self, b, now):
        """Sparks off a window top (glass and metal), dust on the floor."""
        back = -1.0 if b.vx > 0 else 1.0
        on_floor = abs(b.y - self.stage.floor_y) < 1
        if on_floor:
            if self.rng.random() < 0.5:
                self.fxp.spawn_at('dust', now, b.x + back * 30, b.y - 10)
                self.fx_count += 1
            return
        for _ in range(self._fxn(3)):
            a = math.pi + self.rng.uniform(0.15, 0.6) if back < 0 else -self.rng.uniform(0.15, 0.6)     # up and back
            sp = self.rng.uniform(300, 650) * (0.6 + 0.4 * min(1.0, abs(b.vx) / 900.0))
            self._particle(_spark_img(self.rng.randrange(4)), b.x + back * 26, b.y - 2, math.cos(a) * sp, math.sin(a) * sp, 1400.0,
                           now + self.rng.uniform(0.18, 0.32), rotate=a)

    def _land_fx(self, b, now, landed_from):
        if landed_from > 900:
            self.fxp.spawn_at('dust', now, b.x, b.y - 8)
            self.fx_count += 1

    def _wall_bounce(self, b, now, side, wx, wy, window=None):
        """A knocked fighter meets a monitor or window edge: bounce back with a short stop, a spark, a little shake, and
        a chance to tech (flip off the wall on its feet)."""
        b.vx = -side * abs(b.vx) * WALL_K
        if not b.grounded:
            b.vy = min(b.vy, -260.0)
        b.stop = (now, now + BOUNCE_STOP_S)
        self.fxp.spawn_at('block_spark', now, wx, wy, -side)
        self.fxp.add_shake(now, 4, 4 * self.I['shake_k'])
        self.fx_count += 1
        self.note('wall_bounce', now, who=b.slot, on='window' if window else 'edge')
        if b.hp > 0 and (b.down or now < b.knocked_until) and not b.meteor and self.rng.random() < self.I['tech_p']:
            b.down, b.getup_at, b.skid = False, None, False
            b.knocked_until = now
            b.vx, b.vy = -side * 300.0, -780.0
            b.grounded = False
            b.recover_ok = False
            b.facing = -side
            b.play('jump', now + BOUNCE_STOP_S, loop=False, hold='idle')
            self._burst_ring(now, wx, wy + 40)
            self.note('tech', now, who=b.slot)
            self.note('getup', now, who=b.slot, how='tech')          # a tech is how this knockdown gets up

    def _ledge_grab(self, b, now, y_prev):
        """Falling past a window's side: the hands catch the ledge (not while down, flying or spiked)."""
        if b.down or b.meteor or b.hp <= 0 or b.vy < 120 or now < b.grab_cool or now < b.knocked_until - 0.2:
            return
        for x0, x1, y in self.stage.ledges():
            if not (y_prev - HANG_DY < y <= b.y - HANG_DY):
                continue
            if x0 - 70 <= b.x < x0 - 10 and x0 - HANG_X >= 50:
                self._start_hang(b, now, 'l', x0, x1, y)
                return
            if x1 + 10 < b.x <= x1 + 70 and x1 + HANG_X <= self.stage.w - 50:
                self._start_hang(b, now, 'r', x0, x1, y)
                return

    def _start_hang(self, b, now, side, x0, x1, y):
        hx = x0 - HANG_X if side == 'l' else x1 + HANG_X
        b.ledge_plan = None
        b.target, b.hover, b.fly_until = None, False, 0.0
        b.x, b.y, b.vx, b.vy = float(hx), float(y + HANG_DY), 0.0, 0.0
        b.grounded, b.skid, b.recover_ok = False, False, False
        b.facing = 1 if side == 'l' else -1
        b.trail.clear()
        b.hang = dict(side=side, x0=x0, x1=x1, y=y, t0=now, until=now + self.rng.uniform(0.35, 0.6))
        anim = next((n for n in ('ledge_hang', 'hang') if n in b.atlas.anim), 'jump')
        b.pose = (anim, SP.frame_of(b.atlas, anim, 'apex')) if anim == 'jump' else None     # the jump's apex tuck: arms up
        if anim != 'jump':
            b.play(anim, now)
        self._burst_ring(now, x0 if side == 'l' else x1, y)
        self.note('ledge_grab', now, who=b.slot)

    def _start_climb(self, b, now):
        h = b.hang
        b.hang = None
        ex = (h['x0'] + 38) if h['side'] == 'l' else (h['x1'] - 38)
        b.climb = dict(t0=now, x0=b.x, y0=b.y, x1=float(ex), y1=float(h['y']))
        self.note('climb', now, who=b.slot)

    def _climb_step(self, b, now):
        c = b.climb
        k = min(1.0, (now - c['t0']) / CLIMB_S)
        ky = _ease_in_out(min(1.0, k / 0.7))                     # up first (eased both ends: no first-frame jump) ...
        kx = _ease_in_out(max(0.0, (k - 0.32) / 0.68))           # ... then over the lip
        lift = 20.0 * math.sin(math.pi * min(1.0, k / 0.9))      # a little hop above the top before settling on it
        b.x = c['x0'] + (c['x1'] - c['x0']) * kx
        b.y = c['y0'] + (c['y1'] - c['y0']) * ky - lift
        if 'jump' in b.atlas.anim:
            b.pose = ('jump', SP.frame_of(b.atlas, 'jump', 'rise' if k < 0.55 else 'apex'))   # pull up, then tuck over the lip
        if k >= 1.0:
            b.climb = None
            b.pose = None
            b.x, b.y, b.vx, b.vy = c['x1'], c['y1'], 0.0, 0.0
            b.grounded = True
            b.grab_cool = now + 0.8
            b.play('crouch' if 'crouch' in b.atlas.anim else 'idle', now, loop=False, hold='idle')

    def _air_plan(self, b, now):
        """Air-to-air set-up: jump, double jump at the apex (a ring under the feet), hover where the apex lands."""
        p = b.air_plan
        rise = b.y - p['y']
        if p['stage'] == 0:
            if rise <= 30:
                p['stage'] = 2
            else:
                b.vy = -math.sqrt(2 * GRAVITY * rise * 0.55)
                b.grounded = False
                b.target, b.hover = None, False
                b.fly_until = 0.0
                b.play('jump', now, loop=False, hold='idle')
                p['stage'] = 1
        if p['stage'] == 1 and b.vy > -140:
            rise = b.y - p['y']
            if rise > 30:
                b.vy = -min(1600.0, math.sqrt(2 * GRAVITY * rise))
                b.play('jump', now, loop=False, hold='idle')
                self._burst_ring(now, b.x, b.y)
                self.note('double_jump', now, who=b.slot)
            p['stage'] = 2
        if p['stage'] == 2 and (b.vy >= -60 or b.y <= p['y']):
            b.air_plan = None
            b.vy = 0.0
            b.target, b.hover, b.fly_until = (b.x, b.y), True, now + 6.0

    def _recovery(self, b, now):
        """Knocked off into the air: one recovery jump back up (towards the nearest ledge when one is close)."""
        if not b.recover_ok or b.down or b.vy < 250 or now < b.knocked_until or b.hp <= 0:
            return
        if self.stage.floor_y - b.y < 280:
            return
        b.recover_ok = False
        best = None
        for x0, x1, y in self.stage.ledges():
            if y < b.y - 40:
                for ex in (x0, x1):
                    d = abs(ex - b.x)
                    if d < 420 and (best is None or d < best[0]):
                        best = (d, ex)
        b.vx = 0.0 if best is None else max(-320.0, min(320.0, (best[1] - b.x) * 1.4))
        b.vy = -1000.0
        b.play('jump', now, loop=False, hold='idle')
        self._burst_ring(now, b.x, b.y)
        self.note('recovery', now, who=b.slot)

    def _meteor_through(self, b, now, x0, x1, y):
        win = self._ledge_window(b.x, y)
        if win is not None:
            self._crack_window(win, now, b.x, y + 6, heavy=True)
        for _ in range(self._fxn(4)):
            a = -math.pi / 2 + self.rng.uniform(-1.1, 1.1)
            sp = self.rng.uniform(250, 600)
            self._particle(_spark_img(self.rng.randrange(4)), b.x, y, math.cos(a) * sp, math.sin(a) * sp, 1400.0, now + 0.35, rotate=a)
        self.note('meteor_through', now, who=b.slot)

    def _meteor_land(self, b, now, landed_from):
        b.meteor = False
        self._crater(now, b.x, landed_from)
        b.vy = -320.0                                              # one bounce off the crater floor
        b.grounded = False
        b.stop = (now, now + 0.07)

    def _crater(self, now, x, v):
        if len([d for d in self.decals if d['kind'] == 'crater']) >= self.I['craters']:
            old = next(d for d in self.decals if d['kind'] == 'crater')
            self.decals.remove(old)
            self.holes.append((old['x'], old['y'], old['x'] + old['img'].width, old['y'] + old['img'].height))
        w = int(min(260, max(140, v * 0.11)))
        im, line = _crater_img(w, self.rng.randrange(1 << 30))
        fy = self.stage.floor_y
        self.decals.append(dict(img=im, x=int(x - w / 2), y=int(fy - line), wid=None, until=None, kind='crater', reveal=None))
        self.fxp.spawn_at('dust', now, x - 40, fy - 10)
        self.fxp.spawn_at('dust', now, x + 40, fy - 10)
        self.fxp.add_shake(now, 8, 7 * self.I['shake_k'])
        for _ in range(self._fxn(7)):
            a = -math.pi / 2 + self.rng.uniform(-1.0, 1.0)
            sp = self.rng.uniform(320, 760)
            self._particle(_rubble_img(self.rng.randrange(6)), x + self.rng.uniform(-30, 30), fy - 6, math.cos(a) * sp, math.sin(a) * sp,
                           2200.0, now + 0.9, floor=True)
        self.fx_count += 3
        self.note('crater', now)

    def _burst_ring(self, now, x, y):
        """A flat white ring on the spot (take-off, double jump, ledge catch, tech)."""
        self._particle(_ring_img(40), x, y, 0.0, 0.0, 0.0, now + 0.22, grow=True)

    def _particle(self, img, x, y, vx, vy, g, t_end, rotate=None, floor=False, grow=False):
        if rotate is not None:
            deg = -math.degrees(rotate)
            img = _art(('rot', id(img), int(deg / 15)), lambda: img.rotate(int(deg / 15) * 15, expand=True))
        cap = int(60 * self.I['fx'])
        if len(self.particles) >= cap:
            self.particles.pop(0)
        self.particles.append([img, float(x), float(y), float(vx), float(vy), float(g), float(t_end), floor, grow, self.last_now])
        self.fx_count += 1

    # ---- windows: cracks, knock-through, shatter
    def _ledge_window(self, x, y):
        for w in self.stage.windows:
            if w['l'] - 10 <= x <= w['r'] + 10 and abs(w['t'] - y) < 3:
                return w
        return None

    def _crack_window(self, win, now, cx, cy, heavy):
        kind = self.cracks.hit(win['id'], heavy)
        if kind is None:
            return None
        self.note(kind, now)
        if kind != 'crack_small':
            self.forge.on_window_crack(win, now, cx, cy, heavy=True)   # a chunk may break off: a weapon to pick up
        if kind == 'shatter':
            self._shatter(win, now, cx, cy)
        else:
            self.crack_marks.setdefault(win['id'], []).append((cx, cy, kind))
            self.fxp.spawn_at(kind, now, cx, cy, fade_ms=20000)
            self.fx_count += 1
            if kind == 'crack_big':
                self._letters(win, now, cx, cy, 5)
        return kind

    def _window_collisions(self, b, now):
        """A knocked-back fighter whose centre enters a window rect cracks it (overlay only); slow enough, it bounces off
        the glass; fast enough, it goes THROUGH and leaves its own outline cracked into the window."""
        cx, cy = b.center()
        win = self.stage.window_at(cx, cy)
        if win is None or (b.inside is not None and b.inside != win['id']):
            b.inside = None
        if (now >= b.knocked_until and not b.meteor) or now - b.last_crack < 0.45 or win is None or b.inside == win['id']:
            return
        if b.meteor:
            return                                                 # the spike cracks the tops it passes (_meteor_through)
        speed = abs(b.vx)
        heavy = speed > 600 or b.down
        b.last_crack = now
        if speed >= self.I['through_v'] and win['id'] not in self.cracks.shattered:
            b.inside = win['id']
            b.vx *= 0.8
            self._through_mark(b, win, now)
            heavy = True
        elif speed > WALL_BOUNCE_V:
            side = 1 if b.vx > 0 else -1
            ex = win['l'] if side > 0 else win['r']
            self._wall_bounce(b, now, side, ex, cy, window=win)
        else:
            b.vx *= -0.35
        self._crack_window(win, now, cx, cy, heavy)

    def _through_mark(self, b, win, now):
        idx, _ = b.frame(now)
        spr = self._sprite(b.atlas, b.drawn_anim(), idx, b.facing)
        im = _fighter_crack(spr, self.rng.randrange(1 << 30))
        l, t, r, bt = b.sprite_rect()
        x, y = l - 60, t - 60
        box = (max(x, win['l']), max(y, win['t']), min(x + im.width, win['r']), min(y + im.height, win['b']))
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        im = im.crop((box[0] - x, box[1] - y, box[2] - x, box[3] - y))   # the outline stays on the glass
        self.decals.append(dict(img=im, x=box[0], y=box[1], wid=win['id'], until=now + 20.0, kind='through', reveal=None))
        self.fxp.add_shake(now, 5, 5 * self.I['shake_k'])
        self.fx_count += 1
        self.note('through', now, who=b.slot)

    def _shatter(self, win, now, cx, cy):
        if self.sfx is not None:
            self.sfx.play('shatter', now, now)
        self.crack_marks.pop(win['id'], None)
        self.fxp.clear(tag=None)
        for d in [d for d in self.decals if d['wid'] == win['id']]:
            self.decals.remove(d)
            self.holes.append((d['x'], d['y'], d['x'] + d['img'].width, d['y'] + d['img'].height))
        e = self.fx.get('shatter')
        for i in range(self._fxn(len(e.frames))):
            inst = self.fxp.spawn_at('shatter', now, cx + self.rng.uniform(-60, 60), cy + self.rng.uniform(-40, 40), 1,
                                     vx=self.rng.uniform(-420, 420), vy=self.rng.uniform(-850, -300), gravity=2600.0, fade_ms=1100)
            inst.data = {'frame': i % len(e.frames)}
            self.fx_count += 1
        self._letters(win, now, cx, cy, 9)
        if self.backdrop is not None:
            self._punch_hole(win)
        if self.I['rain_s']:
            self.rains.append(dict(l=win['l'], t=win['t'], r=win['r'], b=win['b'], until=now + self.I['rain_s'], next=now + 0.2))
        self.note('hole' if self.backdrop is not None else 'shatter_done', now)

    def _letters(self, win, now, cx, cy, n):
        """Random glyphs knocked off the glass (never text read from anywhere).  V7: drawn at the sheet's own size (the 2x
        glyphs were bigger than a fighter's head and read as screen garbage) and falling with full gravity."""
        e = self.fx.get('letters')
        for _ in range(self._fxn(n)):
            img = e.image(self.rng.randrange(len(e.frames)), 1, 1.0)
            self._particle(img, cx + self.rng.uniform(-50, 50), cy + self.rng.uniform(-30, 30), self.rng.uniform(-620, 620),
                           self.rng.uniform(-950, -420), 2600.0, now + self.rng.uniform(0.8, 1.2), floor=True,
                           rotate=math.radians(self.rng.uniform(-45, 45)))      # tilted: tumbling debris, not a line of text
            self.letters_spawned += 1

    def _punch_hole(self, win):
        """Freeze mode: the shattered window becomes a dark hole in the RAM backdrop (jagged inset edge)."""
        d = ImageDraw.Draw(self.backdrop)
        l, t, r, b = win['l'], win['t'], win['r'], win['b']
        pts = []
        n = 14
        for i in range(n):
            k = i / n
            pts.append((l + (r - l) * k, t + self.rng.uniform(0, 14)))
        for i in range(n):
            k = i / n
            pts.append((r - self.rng.uniform(0, 14), t + (b - t) * k))
        for i in range(n):
            k = i / n
            pts.append((r - (r - l) * k, b - self.rng.uniform(0, 14)))
        for i in range(n):
            k = i / n
            pts.append((l + self.rng.uniform(0, 14), b - (b - t) * k))
        d.polygon(pts, fill=HOLE)
        self.holes.append((l, t, r + 1, b + 1))       # the polygon's boundary lands on row b / column r too (PIL paints it)

    # ---- stage hazards and the world's own particles (V7)
    def _hazards(self, now):
        if not self.I['hazard_s'] or now < self.next_hazard:
            return
        self.next_hazard = now + self.I['hazard_s'] * self.rng.uniform(0.8, 1.3)
        cands = [w for w in self.stage.windows if w['id'] not in self.cracks.shattered and w['r'] - w['l'] >= 240 and w['b'] - w['t'] >= 160
                 and not any(d['kind'] == 'spread' and d['wid'] == w['id'] for d in self.decals)]
        if not cands:
            return
        cands.sort(key=lambda w: -self.cracks.count.get(w['id'], 0))
        win = cands[0] if self.rng.random() < 0.6 else cands[self.rng.randrange(len(cands))]
        y = int(win['t'] + (win['b'] - win['t']) * self.rng.uniform(0.35, 0.6))
        w = win['r'] - win['l']
        im, pts = _spread_crack(w, 60, self.rng.randrange(1 << 30))
        self.decals.append(dict(img=im, x=win['l'], y=y - 30, wid=win['id'], until=now + 20.0, kind='spread', reveal=(now, 0.75),
                                drop=dict(at=now + 0.8, win=win, y=y)))
        self.note('hazard_crack', now)

    def _tick_world(self, now, dt):
        # spreading cracks: when one has run across its window, a glass shard drops out of it
        for d in list(self.decals):
            if d['until'] is not None and now >= d['until']:
                self.decals.remove(d)
                self.holes.append((d['x'], d['y'], d['x'] + d['img'].width, d['y'] + d['img'].height))
                continue
            drop = d.get('drop')
            if drop and now >= drop['at'] and self.phase in ('fight', 'round_end'):
                d['drop'] = None
                win = drop['win']
                if win['id'] in self.cracks.shattered:
                    continue
                sw = int(min(240, max(150, (win['r'] - win['l']) * 0.35)))
                sx = self.rng.uniform(win['l'] + 20, win['r'] - sw - 20)
                self.shards.append(dict(img=_shard_img(sw, 26, self.rng.randrange(1 << 30)), x=sx, y=float(drop['y']), vy=0.0, w=sw, landed=None))
                self._crack_window(win, now, sx + sw / 2.0, drop['y'], heavy=False)
                self.note('hazard_shard', now)
        # falling shards land on the first top below them and become platforms for a while
        for s in list(self.shards):
            if s['landed'] is None:
                y0 = s['y']
                s['vy'] = min(MAX_FALL, s['vy'] + GRAVITY * 0.8 * dt)
                s['y'] += s['vy'] * dt
                cx = s['x'] + s['w'] / 2.0
                tops = [y for x0, x1, y in self.stage.ledges() if x0 <= cx <= x1 and y0 + 26 <= y <= s['y'] + 26] + \
                       ([self.stage.floor_y] if y0 + 26 <= self.stage.floor_y <= s['y'] + 26 else [])
                if tops:
                    top = min(tops)
                    s['y'] = top - 26
                    s['landed'] = now
                    plat = dict(x0=int(s['x']), x1=int(s['x'] + s['w']), y=int(top - 26), until=now + 12.0)
                    s['plat'] = plat
                    self.stage.extra.append(plat)
                    self.fxp.spawn_at('dust', now, cx, top - 6)
                    self.fxp.add_shake(now, 3, 3 * self.I['shake_k'])
                    self.fx_count += 1
                    self.note('shard_platform', now)
                elif s['y'] > self.stage.h:
                    self.shards.remove(s)
            elif now >= s['plat']['until'] or self.phase in ('exit',):
                if s['plat'] in self.stage.extra:
                    self.stage.extra.remove(s['plat'])
                self.shards.remove(s)
                self.holes.append((int(s['x']), int(s['y']), int(s['x'] + s['w']), int(s['y'] + 40)))
                e = self.fx.get('shatter')
                for i in range(self._fxn(3)):
                    inst = self.fxp.spawn_at('shatter', now, s['x'] + s['w'] * (i + 0.5) / 3.0, s['y'] + 10, 1, vx=self.rng.uniform(-120, 120),
                                             vy=self.rng.uniform(-300, -80), gravity=1500.0, fade_ms=1200)
                    inst.data = {'frame': i % len(e.frames)}
                self.note('shard_crumble', now)
        # letter rain from shattered windows
        for r in list(self.rains):
            if now >= r['until']:
                self.rains.remove(r)
                continue
            if now >= r['next']:
                r['next'] = now + 0.11 / self.I['fx']
                e = self.fx.get('letters')
                x = self.rng.uniform(r['l'] + 16, r['r'] - 16)
                y = self.rng.uniform(r['t'] + 10, r['t'] + (r['b'] - r['t']) * 0.35)
                fall = max(0.3, math.sqrt(2 * max(1.0, self.stage.floor_y - y) / 1100.0))
                img = e.image(self.rng.randrange(len(e.frames)), 1, 1.0)
                self._particle(img, x, y, self.rng.uniform(-30, 30), self.rng.uniform(0, 80), 1100.0, now + fall, floor=True)
                self.letters_spawned += 1
        # particles
        keep = []
        fy = self.stage.floor_y
        for p in self.particles:
            if now >= p[6]:
                continue
            p[4] += p[5] * dt
            p[1] += p[3] * dt
            p[2] += p[4] * dt
            if p[7] and p[2] > fy - 3:
                if abs(p[4]) > 200 and p[5] > 1500:
                    p[2], p[4], p[3] = fy - 3, -abs(p[4]) * 0.3, p[3] * 0.6      # rubble bounces once
                else:
                    continue
            keep.append(p)
        self.particles = keep

    # ---- drawables for the compositor
    def drawables(self, now):
        """-> [(image, left, top)] in stage px, back to front."""
        out = []
        rad = self.cam.radial
        if rad is not None:
            if now >= rad[1]:
                self.cam.radial = None
            elif now >= rad[0]:
                size = int(min(self.stage.w, self.stage.h) * 1.05)
                im = _radial(int((now - rad[0]) * 15) % 3, size)
                out.append((im, int(rad[2] - size / 2), int(rad[3] - size / 2)))
        for d in self.decals:
            im = d['img']
            if d['reveal'] is not None:
                k = (now - d['reveal'][0]) / d['reveal'][1]
                if k < 1.0:
                    wpx = int(im.width * max(0.0, k) / 8) * 8      # 8 px steps: few distinct crops
                    if wpx <= 0:
                        continue
                    im = _art(('reveal', id(d['img']), wpx), lambda: d['img'].crop((0, 0, wpx, d['img'].height)))
                else:
                    d['reveal'] = None
            out.append((im, d['x'], d['y']))
        for s in self.shards:
            out.append((s['img'], int(s['x']), int(s['y'])))
        out.extend(self.forge.drawables(now, 'back'))            # forge holes and loose pieces lying on the tops
        if self.sp is not None:
            out.extend(self.sp.drawables(now, 'back'))
        for im, lx, ty, layer, inst in self.fxp.placements(now, layer='back'):
            out.append((im, lx, ty))
        ex = self.exchange
        if ex is not None and ex.get('state') == 'clash' and ex['stage'] in ('fire', 'struggle', 'push', 'fade'):
            out.extend(self._clash_drawables(ex, now))
        bh = self.cam.bar_h(now)
        if bh > 0:                                             # letterbox: behind the fighters, so it never hides a foot
            bar = _bar(self.stage.w, bh)
            out.append((bar, 0, 0))
            out.append((bar, 0, self.stage.h - bh))
        for s in 'ab':
            b = self.f[s]
            sh = self._shadow_of(b)
            if sh is not None:
                out.append(sh)
        if self.I['speedlines']:
            for s in 'ab':
                b = self.f[s]
                if now < b.dash_until and self.phase not in ('done',):
                    out.append(self._speedline_of(b, now))
        for s in 'ab':
            b = self.f[s]
            for (t, anim, fr, facing, x, y) in b.trail:
                age = (now - t) / AFTERIMAGE_S
                if age >= 1.0:
                    continue
                im, dx, dy = self._sprite_trim(b.atlas, anim, fr, facing, alpha=int(110 * (1.0 - int(age * 4) / 4.0)),   # 4 steps
                                               unarmed=self.forge.armed(s))
                if im is not None:
                    out.append((im, int(x - b.atlas.anchor(facing) * SCALE) + dx, int(y - b.atlas.ground_y * SCALE) + dy))
        imp = self.impact if (self.impact and self.impact[0] <= now < self.impact[1]) else None
        for s in 'ab':
            b = self.f[s]
            idx, _ = b.frame(now)
            sil = None if imp is None else ('white' if s == imp[2] else (None if len(imp) > 3 else 'dark'))
            armed = self.forge.armed(s)                        # V8: a forged weapon replaces the drawn one (unarmed sheet)
            if b.alpha is not None and sil is None:
                if b.alpha <= 0.05:
                    continue
                im, dx, dy = self._sprite_trim(b.atlas, b.drawn_anim(), idx, b.facing, alpha=int(255 * round(b.alpha * 4) / 4.0), unarmed=armed)
                l, t, r, bt = b.sprite_rect()
                if im is not None:
                    out.append((im, l + b.jitter + dx, t + dy))
                continue
            out.extend(self.forge.held(s, now, 'back'))        # a dual-wielder's second forged weapon, behind the body
            im, dx, dy = self._sprite_trim(b.atlas, b.drawn_anim(), idx, b.facing, silhouette=sil, unarmed=armed)
            l, t, r, bt = b.sprite_rect()
            if im is not None:
                out.append((im, l + b.jitter + dx, t - b.row_lift(now) + dy))
            out.extend(self.forge.held(s, now, 'front'))       # the forged weapon at this frame's grip, swinging with the arm
        out.extend(self.forge.drawables(now, 'front'))           # cuts, morphs, slabs, debris
        for im, lx, ty, layer, inst in self.fxp.placements(now, layer='front'):
            out.append((im, lx, ty))
        if self.sp is not None:
            out.extend(self.sp.drawables(now, 'front'))
        for p in self.particles:
            im = p[0]
            if p[8]:                                               # a ring: grows and fades over its short life
                k = min(1.0, max(0.0, (now - p[9]) / max(1e-3, p[6] - p[9])))
                step = int(k * 4)
                im = _art(('ringk', id(p[0]), step), lambda: p[0].resize((int(p[0].width * (0.6 + 0.25 * step)), int(p[0].height * (0.6 + 0.25 * step))),
                                                                          Image.NEAREST))
            out.append((im, int(p[1] - im.width / 2), int(p[2] - im.height / 2)))
        if self.phase == 'vs':
            out.extend(self._vs_drawables(now))
        if self.banner:
            kind, until, x = self.banner[:3]
            if kind.startswith('text:'):
                im = self._text_banner(kind[5:])
            else:
                im = self.fx.banner(kind, name=self.banner[3] if len(self.banner) > 3 else None)
            if kind == 'winner' and self.winner:
                x = self.f[self.winner].x
                y = min(self.stage.h * 0.28, self.f[self.winner].y - 300)
                cy = max(HUD_H + im.height, y)
            else:
                cy = self.stage.h * 0.28
            cx = self.stage.w / 2.0 if x is None else min(max(x, im.width / 2 + 10), self.stage.w - im.width / 2 - 10)
            out.append((im, int(cx - im.width / 2), int(cy - im.height / 2)))
        if self.phase not in ('entry', 'exit', 'done'):
            hud = self._hud()
            out.append((hud, 0, 0))
        out.append((self._exit_button(), self.exit_rect()[0], self.exit_rect()[1]))
        return out

    def _shadow_of(self, b):
        """A soft ground shadow on the top below the fighter: it reads the height of a jump and grounds it on busy desktops."""
        if self.phase in ('exit', 'done') or b.y > self.stage.floor_y + 2:
            return None
        below = [y for x0, x1, y in self.stage.platforms() if x0 - 10 <= b.x <= x1 + 10 and y >= b.y - 1]
        if not below:
            return None
        py = min(below)
        k = max(0.0, 1.0 - (py - b.y) / 520.0)
        if k <= 0.08:
            return None
        w = int((70 + 50 * k) / 8) * 8
        im = _shadow(w)
        return (im, int(b.x - w / 2), int(py - im.height / 2))

    def _speedline_of(self, b, now):
        variant = int(now * 20) % 3
        if abs(b.vy) > abs(b.vx) * 1.5:
            im = _speedlines(variant, horizontal=False)
            return (im, int(b.x - im.width / 2), int(b.y - 100 - (im.height if b.vy > 0 else 0)))
        im = _speedlines(variant)
        moving = 1 if b.vx >= 0 else -1
        if moving < 0:
            im = _art(('speedflip', id(im)), lambda: im.transpose(Image.FLIP_LEFT_RIGHT))
        cx, cy = b.center()
        return (im, int(cx - im.width if moving > 0 else cx), int(cy - im.height / 2))

    def _clash_drawables(self, ex, now):
        out = []
        y = ex['hand_y']
        phase = int(now * 24) % 4
        alpha_k = 1.0 - min(1.0, (now - ex['st0']) / 0.3) if ex['stage'] == 'fade' else 1.0
        for s in (ex['left'], ex['right']):
            front = ex['fronts'].get(s)
            if front is None:
                continue
            b = self.f[s]
            hx, hy = self._clash_hand(s, ex)
            L = int(abs(front - hx))
            if L < 4:
                continue
            strip = _beam_strip(b.atlas.accent, phase, self.stage.w)
            im = _art(('beamcrop', id(strip), L // 4), lambda: strip.crop((0, 0, (L // 4) * 4, strip.height)))
            if b.facing < 0:
                im = _art(('beamflip', id(im)), lambda: im.transpose(Image.FLIP_LEFT_RIGHT))
            if alpha_k < 1.0:
                q = int(alpha_k * 4) / 4.0
                def faded(im=im, q=q):
                    out = im.copy()
                    out.putalpha(im.getchannel('A').point(lambda v: int(v * q)))      # alpha only: blending RGB with black went grey
                    return out
                im = _art(('beamfade', id(im), q), faded)
            x0 = int(hx) if b.facing > 0 else int(hx - im.width)
            out.append((im, x0, int(hy - im.height / 2)))
            fl = _hand_flare(b.atlas.accent, phase % 2)
            out.append((fl, int(hx - fl.width / 2), int(hy - fl.height / 2)))
        if ex['stage'] == 'struggle':
            A, B = self.f[ex['left']].atlas.accent, self.f[ex['right']].atlas.accent
            ball = _clash_ball(A, B, phase)
            out.append((ball, int(ex['x_c'] - ball.width / 2), int(y - ball.height / 2)))
        return out

    def _vs_drawables(self, now):
        """The VS card: two name plates slide in from the sides, VS lands in the middle, then they slide away."""
        if self._vs is None:
            self._vs = {s: self._vs_plate(s) for s in 'ab'}
            self._vs['vs'] = text_image('VS', 88, (255, 236, 120, 255), (40, 20, 10, 255))
        el = now - self.phase_t0
        W, H = self.stage.w, self.stage.h
        out = []
        y = int(H * 0.36)
        for s, side in (('a', -1), ('b', 1)):
            im = self._vs[s]
            home = W / 2.0 - im.width - 50 if side < 0 else W / 2.0 + 50
            off = -im.width - 20 if side < 0 else W + 20
            if el < 0.4:
                k = _ease_out_back(el / 0.4)
            elif el < VS_S - 0.32:
                k = 1.0
            else:
                k = 1.0 - _ease_in_out((el - (VS_S - 0.32)) / 0.32)
            x = off + (home - off) * k
            out.append((im, int(x), y))
        vs = self._vs['vs']
        if 0.3 <= el < VS_S - 0.2:
            q = min(1.0, (el - 0.3) / 0.15)
            sc = 2.2 - 1.2 * _ease_out(q)
            step = round(sc * 10) / 10.0
            im = _art(('vs', step), lambda: vs.resize((int(vs.width * step), int(vs.height * step)), Image.NEAREST))
            out.append((im, int(W / 2 - im.width / 2), int(y + 90 - im.height / 2)))
        return out

    def _vs_plate(self, s):
        b = self.f[s]
        acc = b.atlas.accent
        w, h = 620, 190
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        flip = s == 'b'
        poly = [(30, 0), (w, 0), (w - 30, h), (0, h)] if not flip else [(0, 0), (w - 30, 0), (w, h), (30, h)]
        d.polygon(poly, fill=(18, 16, 24, 235), outline=acc + (255,))
        d.line([poly[0], poly[1]], fill=acc + (255,), width=6)
        spr = self._sprite(b.atlas, 'idle', 0, -1 if flip else 1)
        sx = w - spr.width + 20 if flip else -20
        im.alpha_composite(spr.crop((0, 0, spr.width, min(spr.height, h + 30))).crop((0, 30, spr.width, min(spr.height, h + 30))), (sx, 0))
        nm = str(self.names[s]).upper()[:14]
        f = font(40, True)
        tw = int(d.textlength(nm, font=f))
        tx = 40 if flip else w - 40 - tw
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            d.text((tx + dx, 70 + dy), nm, font=f, fill=(10, 8, 12, 255))
        d.text((tx, 70), nm, font=f, fill=(255, 255, 255, 255))
        return im

    def _text_banner(self, s):
        im = self._text_banners.get(s)
        if im is None:
            im = self._text_banners[s] = text_image(s, 14 * self.fx.res, (255, 236, 120, 255))
        return im

    _sprite_cache = {}

    def _sprite(self, atlas, anim, idx, facing, alpha=None, silhouette=None, unarmed=False):
        key = (id(atlas), anim, idx, facing >= 0, alpha, silhouette, bool(unarmed))
        im = self._sprite_cache.get(key)
        if im is None:
            if len(self._sprite_cache) > 480:                # V6: 160 thrashed (two fighters x trails x impact silhouettes)
                self._sprite_cache.clear()
            fr = atlas.unarmed_frame(anim, idx, facing) if unarmed and hasattr(atlas, 'unarmed_frame') else atlas.frame_image(anim, idx, facing)
            im = fr.resize((fr.width * SCALE, fr.height * SCALE), Image.NEAREST)
            if alpha is not None:
                im = im.copy()
                im.putalpha(im.getchannel('A').point(lambda v: v * alpha // 255))
            if silhouette is not None:                         # impact frames: the flat silhouette of the pose
                col = (255, 255, 255, 255) if silhouette == 'white' else (16, 12, 20, 255)
                flat = Image.new('RGBA', im.size, col)
                flat.putalpha(im.getchannel('A').point(lambda v: 255 if v > 0 else 0))
                im = flat
            self._sprite_cache[key] = im
        return im

    _trim_cache = {}

    def _sprite_trim(self, atlas, anim, idx, facing, alpha=None, silhouette=None, unarmed=False):
        """V9 (arena 30 fps): the sprite cut to the box of its opaque pixels -> (image or None, dx, dy).  A 256 px cell is
        mostly transparent, so the fighter's dirty rectangle - and the premultiply and the window upload behind it - shrinks
        to the body.  The transparent margin composites to nothing: the same pixels on screen.  Sprites are never changed
        after they are made, so the box is measured once per cached sprite."""
        im = self._sprite(atlas, anim, idx, facing, alpha=alpha, silhouette=silhouette, unarmed=unarmed)
        e = self._trim_cache.get(id(im))
        if e is None or e[0] is not im:
            bb = im.getchannel('A').getbbox()
            if bb is None:
                e = (im, None, 0, 0)
            elif bb == (0, 0, im.width, im.height):
                e = (im, im, 0, 0)
            else:
                e = (im, im.crop(bb), bb[0], bb[1])
            if len(self._trim_cache) > 1000:
                self._trim_cache.clear()
            self._trim_cache[id(im)] = e
        return e[1], e[2], e[3]

    _hud_cache = {}

    def _hud(self):
        pc = {s: int(round(self.pct.get(s, 0.0))) for s in 'ab'}
        key = (self.f['a'].hp, self.f['b'].hp, self.wins['a'], self.wins['b'], self.round, self.names['a'], self.names['b'], self.stage.w, self.to_win,
               pc['a'], pc['b'])
        im = self._hud_cache.get(key)
        if im is not None:
            return im
        w = self.stage.w
        im = Image.new('RGBA', (w, HUD_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        bar_w = int(w * 0.32)
        for s, x0, flip in (('a', 24, False), ('b', w - 24 - bar_w - (EXIT_W + EXIT_MARGIN + 12), True)):   # clear of the EXIT button
            hp = max(0, min(100, int(self.f[s].hp)))
            d.rectangle([x0, 18, x0 + bar_w, 34], fill=TRACK + (230,), outline=(230, 230, 240, 255), width=2)
            fw = int((bar_w - 4) * hp / 100.0)
            col = (150, 230, 150) if hp > 50 else (AMBER if hp > 25 else RED)
            if fw:
                if flip:
                    d.rectangle([x0 + bar_w - 2 - fw, 20, x0 + bar_w - 2, 32], fill=col + (255,))
                else:
                    d.rectangle([x0 + 2, 20, x0 + 2 + fw, 32], fill=col + (255,))
            nm = str(self.names[s])[:14]
            tw = int(d.textlength(nm, font=font(16, True)))
            text(d, (x0 + bar_w - tw if flip else x0, 38), nm, (245, 245, 250), 16)
            pt = f'{pc[s]}%'                                     # V9: the damage %, next to the name
            pw = int(d.textlength(pt, font=font(14, True)))
            nx = x0 + bar_w - tw - 10 - pw if flip else x0 + tw + 10
            from .render import dmg_colour
            text(d, (nx, 39), pt, dmg_colour(pc[s]), 14)
            dots = f'x{self.wins[s]}' if self.to_win is None else ' '.join('*' if i < self.wins[s] else 'o' for i in range(self.to_win))
            dw = int(d.textlength(dots, font=font(14, True)))
            text(d, (x0 if flip else x0 + bar_w - dw, 38), dots, (255, 226, 122), 14)
        rt = f'ROUND {self.round}'
        text(d, (w // 2 - int(d.textlength(rt, font=font(14, True))) // 2, 20), rt, (255, 236, 120), 14)
        if len(self._hud_cache) > 32:
            self._hud_cache.clear()
        self._hud_cache[key] = im
        return im

    _exit_img = None

    def _exit_button(self):
        if Arena._exit_img is None:
            im = Image.new('RGBA', (EXIT_W, EXIT_H), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([0, 0, EXIT_W - 1, EXIT_H - 1], 6, fill=(40, 24, 26, 235), outline=(255, 120, 110, 255), width=2)
            s = 'EXIT  (Esc)'
            text(d, (EXIT_W // 2 - int(d.textlength(s, font=font(14, True))) // 2, 9), s, (255, 230, 230), 14)
            Arena._exit_img = im
        return Arena._exit_img


# ---------------------------------------------------------------- compositor
class Compositor:
    """Writes only what changed: the rects of drawables that appeared, moved, changed image or disappeared since the last
    frame (V7: an unchanged HUD, decal or banner is no longer repainted every frame), re-based on the backdrop (or
    transparency) and composited.  Shake moves the surface (the window), never the pixels.  The zoom punch re-renders
    one region (the lens) scaled about the fighters; it never reaches outside the monitor."""

    def __init__(self, arena, surface):
        self.arena, self.surface = arena, surface
        self.prev = []                                          # [(image, x, y)] of the last frame (the images are kept alive)
        self.full_pending = True
        self.frames = 0
        self.flashed = False
        self.zoomed = None                                      # the lens rect drawn last frame
        self.max_zoom = 1.0                                     # tests: the largest zoom ever drawn
        self.bar_h = 0                                          # letterbox height drawn last frame

    def _compose(self, items, x0, y0, x1, y1):
        a = self.arena
        base = a.backdrop.crop((x0, y0, x1, y1)) if a.backdrop is not None else Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
        for im, x, y in items:
            if x < x1 and x + im.width > x0 and y < y1 and y + im.height > y0:
                _paste(base, im, x - x0, y - y0)
        return base

    def _render(self, now):
        a = self.arena
        W, H = a.stage.w, a.stage.h
        items = a.drawables(now)
        if self.full_pending:                                   # first frame: the whole surface once (backdrop + everything)
            self.full_pending = False
            self.surface.write(self._compose(items, 0, 0, W, H), 0, 0)
            self.prev = items
            self.surface.offset(*a.fxp.shake(now))
            self.surface.flush()
            self.frames += 1
            return [(0, 0, W, H)]
        cur = {(id(im), x, y) for im, x, y in items}
        old = {(id(im), x, y) for im, x, y in self.prev}
        rects = [(x, y, x + im.width, y + im.height) for im, x, y in items if (id(im), x, y) not in old and not _is_bar(im)]
        rects += [(x, y, x + im.width, y + im.height) for im, x, y in self.prev if (id(im), x, y) not in cur and not _is_bar(im)]
        bh = next((im.height for im, x, y in items if _is_bar(im)), 0)
        if bh != self.bar_h:                                    # letterbox: only the strips between the old and new heights
            lo, hi = min(bh, self.bar_h), max(bh, self.bar_h)
            rects += [(0, lo, W, hi), (0, H - hi, W, H - lo)]
            self.bar_h = bh
        if a.holes:
            rects += [tuple(h) for h in a.holes]
            a.holes = []
        zoom = a.cam.zoom_at(now)
        if self.zoomed is not None and zoom is None:
            rects.append(self.zoomed)                           # the lens is gone: repaint its region plainly
        dirty = _merge(rects, W, H, limit=MERGE_LIMIT)
        if zoom is not None:
            zr = zoom[1]
            dirty = [r for r in dirty if not (r[0] >= zr[0] and r[1] >= zr[1] and r[2] <= zr[2] and r[3] <= zr[3])]
        for (x0, y0, x1, y1) in dirty:
            self.surface.write(self._compose(items, x0, y0, x1, y1), x0, y0)
        if zoom is not None:
            z, (x0, y0, x1, y1), (fx, fy) = zoom
            base = self._compose(items, x0, y0, x1, y1)
            self.surface.write(_lens(base, z, fx - x0, fy - y0), x0, y0)
            self.zoomed = (x0, y0, x1, y1)
            self.max_zoom = max(self.max_zoom, z)
            dirty = dirty + [self.zoomed]
        else:
            self.zoomed = None
        self.prev = items
        dx, dy = a.fxp.shake(now)
        self.surface.offset(dx, dy)
        self.surface.flush()
        self.frames += 1
        return dirty

    def render(self, now):
        a = self.arena
        flash = a.fxp.flash(now) if a.flashes_on(now) else 0.0
        cf = a.cam.flash_at(now) if a.flashes_on(now) else None
        tint = getattr(self.surface, 'tint', None)
        if tint is not None:                 # V8: the surface washes the window itself (macOS: a GPU layer): no full-frame repaint
            if flash > 0:
                tint((255, 255, 255), min(1.0, flash))
            elif cf is not None:
                tint(cf[0], min(1.0, cf[1]))
            else:
                tint(None, 0.0)
            return self._render(now)
        if flash <= 0 and cf is None and not self.flashed:
            return self._render(now)
        W, H = a.stage.w, a.stage.h          # V5: a white screen flash is one full frame (and the frame after it clears it)
        items = a.drawables(now)
        if flash > 0:                        # the whole overlay goes white for a frame (click-through stays: it is only paint)
            ov = (255, 255, 255, int(255 * min(1.0, flash)))
        elif cf is not None:                 # V7: a colour flash in the striker's accent
            ov = tuple(cf[0]) + (int(255 * min(1.0, cf[1])),)
        else:
            ov = None
        fill = getattr(self.surface, 'fill', None)
        if ov is not None and self.flashed and ov == self.flash_ov and self.zoomed is None:
            dirty = self._flash_step(items, ov, W, H)      # V9: the same flash as last frame: only what moved under it
        elif fill is not None and a.backdrop is None:
            fill(ov or (0, 0, 0, 0))                        # V9: one fill for the empty screen, then only the drawables
            for x0, y0, x1, y1 in _merge([(x, y, x + im.width, y + im.height) for im, x, y in items], W, H, limit=MERGE_LIMIT):
                reg = self._compose(items, x0, y0, x1, y1)
                if ov is not None:
                    reg.alpha_composite(Image.new('RGBA', reg.size, ov))
                self.surface.write(reg, x0, y0)
            dirty = [(0, 0, W, H)]
        else:
            self.surface.write(self._flash_frame(items, ov, W, H), 0, 0)
            dirty = [(0, 0, W, H)]
        self.prev = items
        self.bar_h = next((im.height for im, x, y in items if _is_bar(im)), 0)
        self.zoomed = None
        self.flashed = ov is not None
        self.flash_ov = ov
        self.surface.offset(*a.fxp.shake(now))
        self.surface.flush()
        self.frames += 1
        return dirty

    flash_ov = None

    def _flash_frame(self, items, ov, W, H):
        """A whole frame with the flash colour `ov` over everything (None: the plain frame that clears a flash).
        V9: with no backdrop (the live arena), everywhere outside the drawables the result is just `ov` over transparency,
        i.e. `ov` itself, so the frame starts as one fill and only the drawables' rects are composited and washed - the
        same pixels as compositing the full frame and washing it all (tests/test_arena.py ArenaPerf9), about 10 ms less at
        1920x1080."""
        a = self.arena
        if ov is None or a.backdrop is not None:
            base = self._compose(items, 0, 0, W, H)
            if ov is not None:
                base.alpha_composite(Image.new('RGBA', (W, H), ov))
            return base
        base = Image.new('RGBA', (W, H), ov)
        for x0, y0, x1, y1 in _merge([(x, y, x + im.width, y + im.height) for im, x, y in items], W, H, limit=MERGE_LIMIT):
            reg = self._compose(items, x0, y0, x1, y1)
            reg.alpha_composite(Image.new('RGBA', reg.size, ov))
            base.paste(reg, (x0, y0))
        return base

    def _flash_step(self, items, ov, W, H):
        """The second and later frames of one steady flash: the wash is already on the window, so only the rects whose
        drawables appeared, moved, changed or left are composited, washed with the same colour and written."""
        cur = {(id(im), x, y) for im, x, y in items}
        old = {(id(im), x, y) for im, x, y in self.prev}
        rects = [(x, y, x + im.width, y + im.height) for im, x, y in items if (id(im), x, y) not in old]
        rects += [(x, y, x + im.width, y + im.height) for im, x, y in self.prev if (id(im), x, y) not in cur]
        a = self.arena
        if a.holes:
            rects += [tuple(h) for h in a.holes]
            a.holes = []
        dirty = _merge(rects, W, H, limit=MERGE_LIMIT)
        for x0, y0, x1, y1 in dirty:
            reg = self._compose(items, x0, y0, x1, y1)
            reg.alpha_composite(Image.new('RGBA', reg.size, ov))
            self.surface.write(reg, x0, y0)
        return dirty


def _lens(base, z, fx, fy, grid=4):
    """Zoom `base` by z about (fx, fy) with a seamless rim: the inner grid points are scaled, the border points stay
    put, so the zoomed middle blends into the unzoomed edge (no seam at the lens rect)."""
    w, h = base.size
    xs = [w * i / grid for i in range(grid + 1)]
    ys = [h * j / grid for j in range(grid + 1)]

    def src(i, j):
        x, y = xs[i], ys[j]
        if i in (0, grid) or j in (0, grid):
            return x, y
        return fx + (x - fx) / z, fy + (y - fy) / z
    mesh = []
    for j in range(grid):
        for i in range(grid):
            box = (int(xs[i]), int(ys[j]), int(xs[i + 1]), int(ys[j + 1]))
            quad = src(i, j) + src(i, j + 1) + src(i + 1, j + 1) + src(i + 1, j)
            mesh.append((box, quad))
    return base.transform((w, h), Image.MESH, mesh, Image.NEAREST)        # nearest: crisp pixel art, ~4x cheaper than bilinear


def _paste(dst, src, x, y):
    w, h = dst.size
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(src.width, w - x), min(src.height, h - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    if (sx0, sy0, sx1, sy1) != (0, 0, src.width, src.height):
        src = src.crop((sx0, sy0, sx1, sy1))
    dst.alpha_composite(src, (max(0, x), max(0, y)))


MERGE_CELL = 64                  # V9: px; many small rects (debris, letters, sparks) are first pooled per cell of this grid
MERGE_POOL_N = 64                # ... once a frame has more dirty rects than this (a shatter, a burst of debris)


def _overlaps(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _merge(rects, W, H, limit=10):
    """Dirty rects -> at most `limit` rects that cover all of them (the compositor repaints exactly these).
    V9 (arena 30 fps): the same cover, but cheap on busy frames.  Before, touching rects were merged pairwise until
    nothing changed and the excess was then reduced by trying every pair for every merge (cubic): a shatter or a burst of
    debris (100+ rects) cost up to 33 ms in this function alone.  Now many small rects are first pooled per 64 px cell
    (a superset: every pixel stays covered), overlaps are merged in one sorted sweep, and the excess is reduced greedily
    from a heap of pair costs, recomputing only the merged rect's costs."""
    import heapq
    rs = []
    for x0, y0, x1, y1 in rects:
        x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1))
        if x1 > x0 and y1 > y0:
            rs.append((x0, y0, x1, y1))
    if len(rs) > MERGE_POOL_N:
        cells = {}
        for r in rs:
            k = ((r[0] + r[2]) // (2 * MERGE_CELL), (r[1] + r[3]) // (2 * MERGE_CELL))
            cells[k] = _union(cells[k], r) if k in cells else r
        rs = list(cells.values())
    changed = True
    while changed:                                        # merge everything that touches, until stable
        changed = False
        rs.sort()
        out = []
        for r in rs:
            for i in range(len(out) - 1, -1, -1):
                o = out[i]
                if _overlaps(o, r):
                    r = _union(o, r)
                    out.pop(i)
                    changed = True
            out.append(r)
        rs = out
    if len(rs) <= limit:
        return rs
    alive = {i: r for i, r in enumerate(rs)}
    nxt = len(rs)

    def cost(a, b):
        u = _union(a, b)
        return (u[2] - u[0]) * (u[3] - u[1])
    heap = []
    ids = list(alive)
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            i, j = ids[ai], ids[bi]
            heap.append((cost(alive[i], alive[j]), i, j))
    heapq.heapify(heap)
    while len(alive) > limit and heap:
        c, i, j = heapq.heappop(heap)
        if i not in alive or j not in alive:
            continue                                      # a stale pair (one side was merged already)
        u = _union(alive.pop(i), alive.pop(j))
        k, nxt = nxt, nxt + 1
        for m, r in alive.items():
            heapq.heappush(heap, (cost(u, r), m, k))
        alive[k] = u
    return list(alive.values())


def synthetic_backdrop(w, h, seed=1):
    """A test backdrop that is obviously not a screen: coloured bands (tests only)."""
    im = Image.new('RGBA', (w, h), (30, 34, 44, 255))
    d = ImageDraw.Draw(im)
    rng = random.Random(seed)
    for i in range(0, w, 160):
        d.rectangle([i, 0, i + 80, h], fill=(rng.randrange(40, 90), rng.randrange(40, 90), rng.randrange(60, 120), 255))
    return im
