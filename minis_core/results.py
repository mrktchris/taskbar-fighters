"""The results moment (UX item 5 in the brief, "a results beat after each match"): for 4 seconds after a match a strip
over the scoreboard says what happened - "CLAUDE WINS 2-1" and three numbers from the match itself ("23 hits · best
combo 5 · ultimate landed") - with the winner posing and the loser bowing.  On the taskbar the two fighters do the same:
the winner strikes its victory pose, the loser bows (existing moves only).

The numbers come from the planner's own summary of the match (replay.stats_of), stored with the match in replay.json; the
strip is drawn by the director, which hosts the scoreboard.  Settings / `minis.py results off` turns the strip off.
"""
from __future__ import annotations
from PIL import Image, ImageDraw

from .render import font, text

SHOW_S = 4.0
FRESH_S = 6.0                      # a match recorded longer ago than this is not announced any more (a restart, a sleep)
W, H = 286, 42
BG, EDGE, INK, DIM, GOLD = (16, 16, 22, 240), (120, 110, 70, 255), (236, 236, 244), (175, 175, 190), (255, 214, 92)
PORTRAIT = 38


def fresh(entry, wall, shown_id=None) -> bool:
    """A stored match worth announcing: recent, and not announced yet."""
    if not isinstance(entry, dict) or entry.get('id') in (None, shown_id):
        return False
    try:
        return 0 <= float(wall) - float(entry.get('ts', 0)) <= FRESH_S
    except (TypeError, ValueError):
        return False


def headline(entry) -> tuple:
    """-> ('CLAUDE WINS 2-1', '23 hits · best combo 5 · ultimate landed')."""
    from .replay import result_line
    full = result_line(entry)
    head, _, rest = full.partition(' · ')
    return head, rest


_pose_cache = {}


def pose(lib, character, anim, t, w=PORTRAIT, h=PORTRAIT, flip=False):
    """A whole-body frame of `anim` at time t from the character's 64 px sheet, bottom-aligned in w x h (whole pixels)."""
    atlas = lib[character]
    if anim not in atlas.anim:
        anim = 'idle'
    frames = atlas.anim[anim]['frames']
    total = sum(f['ms'] for f in frames) or 1
    ms = int(t * 1000)
    hold = not atlas.anim[anim].get('loop', False)
    if hold and ms >= total:
        i = len(frames) - 1
    else:
        ms %= total
        i = 0
        for j, f in enumerate(frames):
            ms -= f['ms']
            if ms < 0:
                i = j
                break
    key = (atlas.character, anim, i, w, h, flip)
    im = _pose_cache.get(key)
    if im is None:
        fr = atlas.frame_image(anim, i, -1 if flip else 1)
        bb = fr.getchannel('A').getbbox() or (0, 0, fr.width, fr.height)
        fr = fr.crop(bb)
        if fr.width > w or fr.height > h:
            k = min(w / fr.width, h / fr.height)
            fr = fr.resize((max(1, int(fr.width * k)), max(1, int(fr.height * k))), Image.NEAREST)
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        im.alpha_composite(fr, ((w - fr.width) // 2, h - fr.height))
        if len(_pose_cache) > 300:
            _pose_cache.clear()
        _pose_cache[key] = im
    return im


def render(entry, t, lib=None) -> Image.Image:
    """The strip `t` seconds into its 4 s: slides up in 0.2 s, fades out over the last 0.4 s."""
    head, rest = headline(entry)
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.fontmode = '1'
    d.rounded_rectangle([0, 0, W - 1, H - 1], 5, fill=BG, outline=EDGE)
    d.rectangle([4, 1, W - 5, 1], fill=(255, 214, 92, 90))
    chars = (entry.get('plan') or {}).get('chars') or {}
    win, lose = entry.get('winner'), entry.get('loser')
    if lib is not None and chars.get(win) and chars.get(lose):
        try:
            vic = 'victory2' if 'victory2' in lib[chars[win]].anim else 'victory'
            im.alpha_composite(pose(lib, chars[win], vic, t), (4, 2))
            lo = pose(lib, chars[lose], 'bow', max(0.0, t - 0.3), flip=True)
            lo = lo.copy()
            lo.putalpha(lo.getchannel('A').point(lambda v: int(v * 0.8)))
            im.alpha_composite(lo, (W - 4 - PORTRAIT, 2))
        except Exception:
            pass
    f11, f9 = font(11, True), font(9, False)
    x_mid = W // 2
    text(d, (x_mid - int(d.textlength(head, font=f11)) // 2 + 1, 6), head, (60, 40, 10), 11)
    text(d, (x_mid - int(d.textlength(head, font=f11)) // 2, 5), head, GOLD, 11)
    while len(rest) > 3 and d.textlength(rest, font=f9) > W - 2 * (PORTRAIT + 10):
        rest = rest.rsplit(' · ', 1)[0]
    text(d, (x_mid - int(d.textlength(rest, font=f9)) // 2, 24), rest, INK, 9, False)
    a = 1.0
    if t < 0.2:
        a = max(0.0, t / 0.2)
    elif t > SHOW_S - 0.4:
        a = max(0.0, (SHOW_S - t) / 0.4)
    if a < 1.0:
        im.putalpha(im.getchannel('A').point(lambda v, a=a: int(v * a)))
    return im


def slide_y(t, base_y, scale=1):
    """The strip rises 6 px into place during its first 0.2 s."""
    return int(base_y + max(0.0, 1.0 - t / 0.2) * 6 * scale) if t < 0.2 else int(base_y)


def taskbar_beat(entry, my_source, my_slot):
    """What this fighter plays on the taskbar after the match: the winner its victory pose, the loser a bow.  None if this
    side did not take part."""
    progs = entry.get('programs') or {}
    win, lose = entry.get('winner'), entry.get('loser')
    if my_source and progs.get(win) == my_source or (not progs and my_slot == win):
        return 'victory'
    if my_source and progs.get(lose) == my_source or (not progs and my_slot == lose):
        return 'bow'
    return None
