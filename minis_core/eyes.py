"""Pupils that follow the cursor (cheap).  The rig has no eye metadata, so the eye is found once per (character, frame,
facing) as the small darkest cluster at the front of the head band of the sprite, and then shifted by at most one pixel
per axis (res px) toward the cursor; the vacated pixels take the skin colour from just below the cluster.  If no
plausible cluster is found the frame is left alone.  Everything is cached; nothing is read from the screen."""
from __future__ import annotations

_cache = {}


def find_eye(frame, facing=1, res=1):
    """-> list of (x, y) pixels of the front eye in `frame` (RGBA), or [] when unsure."""
    bb = frame.getbbox()
    if not bb:
        return []
    px = frame.load()
    x0, y0, x1, y1 = bb
    band_y1 = y0 + max(3, int((y1 - y0) * 0.3))
    pts = [(x, y) for y in range(y0, band_y1) for x in range(x0, x1) if px[x, y][3] and sum(px[x, y][:3]) < 110]
    if not pts:
        return []
    darkest = min(sum(px[x, y][:3]) for x, y in pts)
    pts = [(x, y) for x, y in pts if sum(px[x, y][:3]) <= darkest + 18]
    # the front of the face: the cluster nearest the facing edge; take pixels within 2*res of the extreme column
    fx = max(p[0] for p in pts) if facing >= 0 else min(p[0] for p in pts)
    near = [p for p in pts if abs(p[0] - fx) <= 2 * res]
    if not near or len(near) > 6 * res * res:
        return []
    ys = sorted({p[1] for p in near})
    if ys[-1] - ys[0] > 3 * res:                                 # brow + eye stacked: keep the lower rows (the eye)
        keep = {y for y in ys if y >= ys[-1] - 2 * res}
        near = [p for p in near if p[1] in keep]
    return near


def eye_pixels(atlas, anim, i, facing):
    # id() is only unique among LIVE objects: once an atlas is freed, a new one (another character, a skin swap) can get
    # the same id and read the old one's eyes.  The entry keeps its atlas alive and is only used for that same object.
    key = (id(atlas), anim, i, facing >= 0)
    hit = _cache.get(key)
    if hit is None or hit[0] is not atlas:
        if len(_cache) > 512:
            _cache.clear()
        hit = _cache[key] = (atlas, find_eye(atlas.frame_image(anim, i, facing), facing, atlas.res))
    return hit[1]


def shift_eyes(frame, pts, dx, dy):
    """A copy of `frame` with the eye pixels moved by (dx, dy); the old spots take the colour just below the eye."""
    if not pts or (dx == 0 and dy == 0):
        return frame
    im = frame.copy()
    px = im.load()
    w, h = im.size
    cols = {p: px[p] for p in pts}
    below_y = max(p[1] for p in pts) + 1
    cx = int(sum(p[0] for p in pts) / len(pts))
    fill = px[cx, below_y] if below_y < h and px[cx, below_y][3] else None
    for (x, y) in pts:
        if fill:
            px[x, y] = fill
    for (x, y), c in cols.items():
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3]:
            px[nx, ny] = c
    return im


def look_at(fighter_x, fighter_y, cursor, dead=30):
    """(dx, dy) in {-1, 0, 1} toward the cursor (screen px), 0 within the dead zone; None when there is no cursor."""
    if cursor is None:
        return (0, 0)
    cx, cy = cursor
    dx = 0 if abs(cx - fighter_x) < dead else (1 if cx > fighter_x else -1)
    dy = 0 if abs(cy - fighter_y) < dead * 2 else (1 if cy > fighter_y else -1)
    return dx, dy
