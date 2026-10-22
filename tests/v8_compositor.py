"""The V8 arena compositor and dirty-rect merge, verbatim from v1.0.0 (minis_core/arena.py at 06e3241), kept ONLY so
tests/test_arena_perf.py can prove the V9 compositor shows the same pixels.  Not used by the app.  One change: the
letterbox bars are recognised by a mark on the image (V9 _is_bar) instead of by id, as in V9, because an id outlived the
_ART cache and was reused by unrelated images; with ids, which images then went unrepainted depended on allocation order."""
from PIL import Image
from minis_core.arena import _is_bar, _lens, _paste


def _merge_v8(rects, W, H, limit=10):
    rs = []
    for x0, y0, x1, y1 in rects:
        x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1))
        if x1 > x0 and y1 > y0:
            rs.append((x0, y0, x1, y1))
    changed = True
    while changed:
        changed = False
        out = []
        while rs:
            a = rs.pop()
            i = 0
            while i < len(rs):
                b = rs[i]
                if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                    a = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    rs.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(a)
        rs = out
    while len(rs) > limit:
        best = None
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                u = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                cost = (u[2] - u[0]) * (u[3] - u[1])
                if best is None or cost < best[0]:
                    best = (cost, i, j, u)
        _, i, j, u = best
        rs = [r for k, r in enumerate(rs) if k not in (i, j)] + [u]
    return rs




class CompositorV8:
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
        dirty = _merge_v8(rects, W, H, limit=20)
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
        base = self._compose(items, 0, 0, W, H)
        if flash > 0:                        # the whole overlay goes white for a frame (click-through stays: it is only paint)
            base.alpha_composite(Image.new('RGBA', (W, H), (255, 255, 255, int(255 * min(1.0, flash)))))
        elif cf is not None:                 # V7: a colour flash in the striker's accent
            base.alpha_composite(Image.new('RGBA', (W, H), cf[0] + (int(255 * min(1.0, cf[1])),)))
        self.surface.write(base, 0, 0)
        self.prev = items
        self.bar_h = next((im.height for im, x, y in items if _is_bar(im)), 0)
        self.zoomed = None
        self.flashed = flash > 0 or cf is not None
        self.surface.offset(*a.fxp.shake(now))
        self.surface.flush()
        self.frames += 1
        return [(0, 0, W, H)]


