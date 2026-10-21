"""Config: sensible defaults, optional overrides from minis.json next to minis.py."""
from __future__ import annotations
import json, os
from pathlib import Path

from . import paths as _paths
ROOT = _paths.settings_dir()                    # where minis.json is read: the clone, or next to a frozen executable

DEFAULTS = {
    # roam zone (logical px = screen px / sprite scale).  Windows finds the empty stretch of the taskbar itself (stage() below,
    # from the RECTS of the taskbar's buttons); this is only the fallback when that fails, measured on the author's PC (2560x1440,
    # 100% DPI, centred icons).  A "zone" in minis.json always wins (load() then turns zone_auto off).  Never walk over the icons.
    "zone": [40, 900],
    "zone_auto": True,                     # Windows: detect the zone from the taskbar's element rects (False = always use `zone`)
    "monitor": None,                       # Windows: monitor index (`minis.py monitors`) whose taskbar the fighters use; None = primary
    "claude_window": 1_000_000,            # context window of the current Claude model (reported by the app)
    "claude_dirs": ["~/.claude/projects"],
    "codex_dirs": ["~/.codex/sessions", "~/.codex-emdash/sessions"],
    "stale_session_hours": 24,
    "sleep_minutes": 30,
    "waiting_seconds": 45,
    "idle_guard_minutes": 10,
    "finished_min_work_s": 15,
    "done_show_s": 8,
    "plan_feed_max_age_min": 15,
    "limit_pct": 90,
    "fps_active": 10,
    "fps_fight": 30,                       # V6: redraw rate while a fight script runs (smears, hitstop and flashes need it)
    "fps_idle": 4,
    "topmost_tick_ms": 250,
    "bout_min_s": 45,                      # neither working: a spar / ranged duel this often
    "bout_max_s": 90,
    "console_min_s": 40,                   # partner knocked out (limit): visit and console it this often
    "console_max_s": 80,
    "shadowbox_min_s": 8,                  # a working fighter throws a shadow punch this often (V6: was 3-6 s)
    "shadowbox_max_s": 14,
    "walk_px_s": 40,
    "gap_px": 32,                          # hip-to-hip distance for close combat (V6: 24 overlapped the ~24 px wide bodies)
    "plate": True,
    "clash_min_s": 20,                     # both agents working: a short clash this often
    "clash_max_s": 40,
    "invite_window_s": 3.0,                # an invite can only be accepted this long after it was sent
    "event_max_age_s": 3.0,                # older partner events are ignored (restart replay)
    "director_poll_s": 2.0,
    "director_idle_s": 60,                 # a slot keeps its source until that source is idle this long and another is active
    "director_grace_s": 6,                 # a source missing for less than this keeps its slot (one bad poll)
    # V5.1: dormant partner, sparring bot, rival mode
    "dormant_hours": 24,                   # a program that went quiet keeps its slot (asleep, dimmed) this long after its last activity
    "sparring_bot": True,                  # one fighter alone and nothing else was used recently: a generic 'Sparring bot' takes the other slot
    "rival": True,                         # default for the control.json toggle (`minis.py rival on|off`): a sleeping partner still fights
    "rival_min": 8,                        # minutes between rival matches (best of 3) while the active fighter is not working
    "rival_max": 15,
    "rival_spar_min": 3,                   # minutes between short rival exchanges while the active fighter is working
    "rival_spar_max": 6,
    "ignore_sources": [],                  # source ids (see `minis.py detect`) that never get a fighter, e.g. ["grok"]
    "proc_working_cpu_pct": 15,            # process sources: tree CPU above this (% of one core) = working
    "proc_window_s": 6,                    # ... averaged over this many seconds
    "log_max_bytes": 65536,
    # V4: matches, scoreboard, arena
    "match_min_s": 180,                    # both awake: a best-of-3 match this often (on top of clashes / spars)
    "match_max_s": 360,
    "scoreboard": True,                    # the right-side widget (director process)
    "tray_icon": True,                     # the notification-area icon (director process): left click = select, right click = menu
    "scoreboard_x": None,                  # screen x of the widget; None = just left of the icon cluster (zone end + 36 - width)
    "arena_monitor": None,                 # monitor index for the Arena button / menu item; None = the one non-primary monitor
    "arena_fps": 30,
    "arena_cpu_budget_pct": 10.0,          # of one core; above it the arena drops to 20 fps
    "arena_min_window_px": [160, 100],     # smaller window rects are not platforms
    "fighter_size": 128,                   # taskbar fighter height in px: 64 (V1-V6 look), 96 or 128 (HD art). `minis.py size N`
}
FIGHTER_SIZES = (64, 96, 128)


def fighter_size_of(value, default=128) -> int:
    """A valid fighter size (64 | 96 | 128) from a config / control.json value; anything else falls back to `default`."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return v if v in FIGHTER_SIZES else default


def feet_drop(size) -> int:
    """How far (logical px) a size-`size` fighter window reaches below the taskbar bottom so its feet stay on the line the
    64 px fighter stands on: the HD art keeps 7 RES-1 px under the feet, which grows with the size."""
    return int(round(7 * (size / 64.0 - 1)))


JUMP_HEADROOM = 30                         # RES 1 px of window above the 64 px cell: a jump's `air` lift draws into it (x size/64)


def headroom_px(size) -> int:
    """Logical px a size-`size` fighter window reaches above its cell so an airborne fighter is never cut off."""
    return int(round(JUMP_HEADROOM * size / 64.0))


PLATE_W, PLATE_H, PLATE_SPACING = 128, 26, 4
PLATE_CLEAR_PX = 40                        # (64 px look) plate strip end -> lowest hip x; superseded by clearance_px(size)
SPRITE_REACH = 34                          # RES 1 px: no frame of any fighter reaches further than this from its hip
                                           # (the 64 px cell is 30 px behind / 34 px in front of the hip anchor)
HUD_GAP = 4                                # logical px between the fight's drawing band and a plate / the scoreboard


def clearance_px(size=64) -> int:
    """Logical px from a plate / the scoreboard to the nearest hip a size-`size` fighter may stand at: its whole sprite
    (SPRITE_REACH, scaled with the size) plus HUD_GAP.  64 px -> 38, 96 -> 55, 128 -> 72."""
    return int(round(SPRITE_REACH * size / 64.0)) + HUD_GAP


def plate_left(cfg, slot) -> int:
    """HUD plates do not travel with the fighters: both sit side by side, fixed, at the left end of the roam zone
    (slot a first, then slot b)."""
    return int(cfg['zone'][0]) + (0 if slot == 'a' else PLATE_W + PLATE_SPACING)


def fight_band(cfg) -> tuple:
    """(x0, x1) logical screen px the fight may draw into: from the end of the plate strip to the scoreboard's left edge
    (or the roam zone's end without one), HUD_GAP inside both.  Every fighter frame and effect is clipped to it, so a
    beam, a spark or a knocked-down body can never paint over a plate or the scoreboard at any fighter size."""
    z0, z1 = cfg['zone']
    x0 = z0 + 2 * PLATE_W + PLATE_SPACING
    if cfg.get('scoreboard', True):
        from . import scoreboard
        z1 = min(z1, scoreboard.left_x(cfg))
    return float(x0 + HUD_GAP), float(z1 - HUD_GAP)


def fight_zone(cfg, size=64) -> tuple:
    """Where fighters may stand (hip x, logical screen px) at fighter size `size`: the drawing band minus a whole sprite
    (clearance_px) at both ends, so a sprite never covers a plate or the scoreboard.  V7.1: the clearance scales with
    the size (at 128 px a sprite reaches twice as far as at 64 px; the old fixed 40 px let a knocked-down 128 px fighter
    reach over the right plate).  cfg['fight_zone'] (screen px) overrides it."""
    if cfg.get('fight_zone'):
        z0, z1 = cfg['fight_zone']
        return float(z0), float(z1)
    b0, b1 = fight_band(cfg)
    c = clearance_px(size) - HUD_GAP
    z0, z1 = b0 + c, b1 - c
    if z1 - z0 < 48 * size / 64.0:                                 # a tiny zone (odd minis.json): keep room for a bout
        mid = (z0 + z1) / 2.0
        z0, z1 = mid - 24 * size / 64.0, mid + 24 * size / 64.0
    return float(z0), float(z1)


def data_base(platform=None, environ=None, home=None) -> Path:
    """Where the data folder lives.  Windows: %LOCALAPPDATA% (unchanged); macOS: ~/Library/Application Support.
    MINIS_DATA_BASE overrides both (the process-level tests and harnesses set it to a temp dir on any OS)."""
    import sys
    env = os.environ if environ is None else environ
    home = Path(home) if home is not None else Path.home()
    if env.get("MINIS_DATA_BASE"):
        return Path(env["MINIS_DATA_BASE"])
    if (platform or sys.platform) == "darwin":
        return home / "Library" / "Application Support"
    return Path(env.get("LOCALAPPDATA") or str(home / "AppData" / "Local"))


def data_dir() -> Path:
    d = data_base() / "minis"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(path: str | os.PathLike | None = None) -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path) if path else ROOT / "minis.json"
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            cfg.update(user)
            if "zone" in user and "zone_auto" not in user:
                cfg["zone_auto"] = False           # the owner measured their own zone: never replace it with a detected one
        except Exception:
            pass
    return cfg


def expand(paths):
    return [Path(os.path.expanduser(p)) for p in paths]


def ui_scale(band_px: int) -> int:
    """Integer-only sprite scale (nearest neighbour, never blur): a 42 px fighter must fit the taskbar band."""
    return max(1, (int(band_px) - 4) // 42)


# ---------------------------------------------------------------- the stage: where the fighters stand (Windows geometry, pure)
# Every value is in PHYSICAL screen px (the Windows backend is per-monitor DPI aware), except `zone`, which is in the logical px
# the rest of the program uses (physical / sprite scale).  The backend gathers an `info` dict with rects only (never a name
# or title) and stage() turns it into the layout; tests feed it synthetic rect sets for every edge, DPI and icon layout.
EDGES = ('left', 'top', 'right', 'bottom')         # ABE_LEFT .. ABE_BOTTOM
BASE_BAND = 48                                      # a 100% Windows 11 taskbar
ZONE_MARGIN = 8                                     # logical px kept clear of any taskbar element (icons, tray, widgets)
ZONE_EDGE_MARGIN = 40                               # ... and of a monitor edge (the default zone's 40)
ZONE_GRID = 48                                      # an element-bounded zone end snaps to this grid (about one icon), so
                                                    # the fighter processes, which detect on their own, agree and a new icon
                                                    # does not re-layout every time
ZONE_MIN_W = 400                                    # logical px: a narrower gap is only taken when nothing wider exists
STRIP_ZONE_MAX = 900                                # a strip (no taskbar under it) is not roamed end to end
SCOREBOARD_TAIL = 36                                # scoreboard.left_x: the widget's right edge is zone end + 36


def band_for_dpi(dpi) -> int:
    """Height (physical px) of a fighter strip that is not a taskbar: a 48 px band at 100%, scaled with the monitor's DPI."""
    return max(24, int(round(BASE_BAND * float(dpi or 1.0))))


def edge_of(rect, monitor) -> int:
    """Which monitor edge (0 left, 1 top, 2 right, 3 bottom) a taskbar rect hugs: the side it is wider than tall along and
    nearest to.  Used for secondary taskbars, which ABM_GETTASKBARPOS does not describe."""
    l, t, r, b = rect
    ml, mt, mr, mb = monitor
    if (r - l) >= (b - t):
        return 1 if abs(t - mt) < abs(mb - b) else 3
    return 0 if abs(l - ml) < abs(mr - r) else 2


def autohide_shown(win_rect, monitor, edge, thickness=None) -> tuple:
    """(shown_rect, revealed) of an auto-hide taskbar from its window's CURRENT rect: hidden, Windows slides the window off the
    monitor so only ~2 px remain.  shown_rect is where it sits when revealed; revealed is True while at least half of its
    thickness is on the monitor."""
    l, t, r, b = win_rect
    ml, mt, mr, mb = monitor
    if edge in (1, 3):
        th = int(thickness or (b - t))
        on = min(b, mb) - max(t, mt)
        shown = (l, mt, r, mt + th) if edge == 1 else (l, mb - th, r, mb)
    else:
        th = int(thickness or (r - l))
        on = min(r, mr) - max(l, ml)
        shown = (ml, t, ml + th, b) if edge == 0 else (mr - th, t, mr, b)
    return shown, th > 0 and on * 2 >= th


def occupied_spans(rects, lo, hi, band, join=None) -> list:
    """x intervals of the taskbar covered by its elements.  Only LEAF rects count (a rect that contains another is a container:
    the whole bar, the icon list, the tray), rects outside the band (vertically) or of zero size are dropped, the rest is
    clipped to [lo, hi] and merged when closer than `join` (the padding between two icons)."""
    bt, bb = band
    join = (bb - bt) // 2 if join is None else join
    rs = [tuple(int(v) for v in r) for r in rects or () if r[2] > r[0] and r[3] > r[1] and r[3] > bt and r[1] < bb]
    rs = list(dict.fromkeys(rs))

    def inside(o, a):
        return o != a and a[0] <= o[0] and a[1] <= o[1] and o[2] <= a[2] and o[3] <= a[3]

    def merge(spans):
        out = []
        for a, b in sorted(spans):
            if out and a - out[-1][1] <= join:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out
    keep = []
    for a in sorted(rs, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])):     # inner rects first: a container is judged by
        if not any(inside(o, a) for o in rs):                              # what its KEPT children cover
            keep.append(a)
            continue
        kids = [o for o in keep if inside(o, a)]
        if not kids:
            keep.append(a)                                 # a leaf: a button, an icon, the clock
            continue
        # a container (the tray, the icon list) counts whole when its children fill it up to small paddings; one with a
        # wide uncovered stretch (the whole bar, Windows 10's task list that spans the free space) only through its children
        holes = free_gaps(a[0], a[2], merge((o[0], o[2]) for o in kids))
        if not holes or max(h[1] - h[0] for h in holes) <= 4 * (bb - bt):      # 4 bands: a tray with padding still counts
            keep.append(a)
    return merge((max(lo, a[0]), min(hi, a[2])) for a in keep if a[2] > lo and a[0] < hi)


def free_gaps(lo, hi, spans) -> list:
    """The uncovered x intervals of [lo, hi] between occupied spans."""
    gaps, x = [], lo
    for a, b in sorted(spans):
        if a > x:
            gaps.append((x, a))
        x = max(x, b)
    if hi > x:
        gaps.append((x, hi))
    return gaps


def pick_gap(gaps, min_w=0):
    """The gap the fighters use: the widest, except that the LEFTMOST wide gap wins when it is at least 3/4 as wide - with
    centred icons (Windows 11) that keeps the classic layout, zone left of the icon cluster; with left-aligned icons (Windows
    10, or 11 set to left) the only wide gap is the one between the icons and the tray.  None when no gap is min_w wide."""
    ok = [g for g in gaps if g[1] - g[0] >= min_w]
    if not ok:
        return None
    widest = max(g[1] - g[0] for g in ok)
    for g in ok:
        if (g[1] - g[0]) * 4 >= widest * 3:
            return g
    return None


def zone_from_span(a, b, sc, lo_edge, hi_edge, cap=None, min_w=2 * PLATE_W):
    """Logical zone for the physical x span [a, b): ZONE_EDGE_MARGIN from a monitor edge, ZONE_MARGIN (plus the scoreboard's
    36 px tail at the right) from a taskbar element, element-bounded ends snapped to ZONE_GRID.  `cap` limits the width
    (strips).  None when less than `min_w` is left."""
    import math
    sc = max(1, int(sc))
    if lo_edge:
        z0 = int(math.ceil(a / sc)) + ZONE_EDGE_MARGIN
    else:
        z0 = int(math.ceil((a / sc + ZONE_MARGIN) / ZONE_GRID)) * ZONE_GRID
    tail = SCOREBOARD_TAIL + (ZONE_EDGE_MARGIN if hi_edge else ZONE_MARGIN)
    if hi_edge:
        z1 = int(math.floor(b / sc)) - tail
    else:
        z1 = int(math.floor((b / sc - tail) / ZONE_GRID)) * ZONE_GRID
    if cap:
        z1 = min(z1, z0 + int(cap))
    if z1 - z0 < min_w:
        return None
    return (z0, z1)


def stage(info, cfg=None) -> dict:
    """Where and how big the fighters are drawn, from the backend's taskbar `info` (rects only):

      rect (l, t, r, b), edge (0-3), autohide, revealed, monitor and work (rects of the taskbar's monitor), dpi (1.0 = 100%),
      parts (rects of the taskbar's elements, or None), parts_src ('uia' | 'win32' | None).  legacy=True (fake shells, macOS):
      rect + edge + autohide + screen only, laid out exactly as before this module existed.

    Layouts:
      bottom taskbar  feet on the taskbar's bottom, plates and scoreboard inside its band, the zone in its empty stretch
                      (auto-hide: the same, shown only while the taskbar is revealed, so nothing ever covers the 2 px strip
                      that reveals it).
      top / left / right taskbar  a strip along the bottom of the work area, BASE_BAND x DPI high, beside the taskbar:
                      the fighters keep a horizontal floor (the art and the fight engine are horizontal), on the free edge.
    -> dict(edge, layout, usable, why, dpi, scale, band=(top, bottom), floor, span=(x0, x1), zone (logical) or None,
            zone_src, parts_src, autohide, revealed)."""
    cfg = cfg or {}
    edge = int(info.get('edge', 3))
    name = EDGES[edge] if 0 <= edge < 4 else 'bottom'
    autohide = bool(info.get('autohide'))
    l, t, r, b = info['rect']
    out = dict(edge=name, autohide=autohide, revealed=bool(info.get('revealed', True)), dpi=float(info.get('dpi') or 1.0),
               parts_src=info.get('parts_src'), parts_n=len(info.get('parts') or ()), zone=None, zone_src='default', why='')
    if info.get('legacy'):
        ok = edge == 3 and not autohide
        if edge != 3:
            sh = int(info.get('screen', (0, b))[1])
            b, t = sh, sh - 48
        band = max(24, b - t)
        out.update(layout='taskbar', usable=ok, band=(b - band, b), floor=b, span=(l, r), scale=ui_scale(band),
                   why='' if ok else ('the taskbar is not at the bottom' if edge != 3 else 'the taskbar auto-hides'))
        return out
    mon = tuple(info.get('monitor') or (l, t, r, b))
    work = tuple(info.get('work') or mon)
    out['monitor'] = mon                                   # popups clamp to THIS monitor (it may sit at negative x / y)
    if edge == 3:
        band = max(24, b - t)
        sc = ui_scale(band)
        usable = not autohide or out['revealed']
        out.update(layout='taskbar', usable=usable, band=(b - band, b), floor=b, span=(l, r), scale=sc,
                   why='' if usable else 'the taskbar auto-hides and is hidden right now')
        if info.get('parts'):
            spans = occupied_spans(info['parts'], l, r, (b - band, b))
            out['spans'] = spans                           # what `doctor` prints: the occupied x ranges (for bug reports)
            gap = pick_gap(free_gaps(l, r, spans), ZONE_MIN_W * sc) or pick_gap(free_gaps(l, r, spans))
            if gap:
                ends = (gap[0], gap[1], sc, gap[0] <= mon[0], gap[1] >= mon[2])
                z = zone_from_span(*ends)
                if z:
                    out.update(zone=z, zone_src='auto')
                else:                                      # a full / small taskbar (1024 px, 200% on 1080p): a narrow zone in
                    z = zone_from_span(*ends, min_w=ZONE_GRID)     # the gap - the HUD is crowded, but nobody walks on an icon
                    if z:
                        out.update(zone=z, zone_src='auto (cramped)')
        known = len(info.get('parts') or ()) >= 2         # the bar's elements were read (one rect alone says nothing)
        if out['zone'] is None and known and cfg.get('zone_auto', True):
            # the buttons are known and leave no safe gap: the default zone would stand the fighters on them - hide instead
            out.update(usable=False, zone_src='none',
                       why='no free taskbar space - set a "zone" in minis.json or use a smaller fighter size (minis.py size 64)')
        elif out['zone'] is None:                          # no element rects could be read: the default zone, kept on this bar
            import math
            d0, d1 = DEFAULTS['zone']
            base = int(math.ceil(l / sc))                  # measured from the bar's left end (a taskbar on another monitor)
            lo_z, hi_z = base + ZONE_EDGE_MARGIN, int(r // sc) - SCOREBOARD_TAIL - ZONE_EDGE_MARGIN
            z = (max(base + int(d0), lo_z), min(base + int(d1), hi_z))
            if z[1] > z[0]:
                out['zone'] = z
    else:
        band = band_for_dpi(out['dpi'])
        sc = ui_scale(band)
        floor = work[3]
        out.update(layout='strip', usable=True, band=(floor - band, floor), floor=floor, span=(work[0], work[2]), scale=sc)
        z = zone_from_span(work[0], work[2], sc, True, True, cap=STRIP_ZONE_MAX)
        if z:
            out.update(zone=z, zone_src='auto')
    if not cfg.get('zone_auto', True):
        out.update(zone=None, zone_src='config')
    return out


def apply_stage(cfg, st) -> bool:
    """Put a detected zone into cfg (every zone reader - plates, fight zone, scoreboard - follows).  -> True on a change."""
    z = st.get('zone')
    if not z or not cfg.get('zone_auto', True):
        return False
    z = [int(z[0]), int(z[1])]
    if list(cfg.get('zone') or ()) == z:
        return False
    cfg['zone'] = z
    return True
