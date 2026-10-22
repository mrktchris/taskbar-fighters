"""Pure geometry for the macOS backend: no AppKit import, so every function is unit-tested on any OS with fake frames.

Coordinate systems
  Cocoa (NSScreen / NSWindow frames): points, origin at the BOTTOM-left of the primary screen, y grows upwards.
  App ("screen px" everywhere else in minis): points, origin at the TOP-left of the primary screen, y grows downwards -
  the same convention as Windows, so minis.py and minis_core need no mac-specific maths.  Quartz window bounds
  (CGWindowListCopyWindowInfo) already use this top-left convention.
A frame is (x, y, w, h) as Cocoa reports it.  A rect is (l, t, r, b) in app coordinates.

The "taskbar" on a Mac is a strip sitting on top of the Dock's top edge: fighters stand on the Dock, plates and the
scoreboard sit in the strip like they sit in the Windows taskbar.  A Dock on the left or right, or one that auto-hides,
falls back to a strip at the bottom of the visible frame.
"""
from __future__ import annotations

STRIP_PT = 48                   # height of the virtual taskbar band (the Windows taskbar is 48 px at 100 %)
DOCK_MIN_PT = 10                # a gap under the visible frame smaller than this is an auto-hidden Dock's sliver
EDGE_BOTTOM = 3                 # ABE_BOTTOM: what minis.py expects from taskbar_rect() when fighters may show


def to_app_rect(frame, primary_h):
    """Cocoa frame (x, y, w, h) -> app rect (l, t, r, b), relative to the primary screen of height `primary_h`."""
    x, y, w, h = frame
    top = primary_h - (y + h)
    return (int(round(x)), int(round(top)), int(round(x + w)), int(round(top + h)))


def to_cocoa_origin(x, y, h, primary_h):
    """App top-left (x, y) of a window `h` points tall -> Cocoa frame origin (x, y_bottom)."""
    return float(x), float(primary_h - y - h)


def point_to_app(px, py, primary_h):
    """Cocoa global point (NSEvent.mouseLocation) -> app point."""
    return int(round(px)), int(round(primary_h - py))


def dock_side(frame, visible):
    """Where the Dock is on this screen: 'bottom', 'left', 'right' or 'hidden' (auto-hide, or on another screen).
    Derived only from the screen frame vs its visible frame (the menu bar takes the top)."""
    fx, fy, fw, fh = frame
    vx, vy, vw, vh = visible
    bottom = vy - fy
    left = vx - fx
    right = (fx + fw) - (vx + vw)
    if bottom >= DOCK_MIN_PT:
        return 'bottom'
    if left >= DOCK_MIN_PT:
        return 'left'
    if right >= DOCK_MIN_PT:
        return 'right'
    return 'hidden'


def dock_strip(frame, visible, primary_h=None, strip=STRIP_PT):
    """-> dict(rect=(l, t, r, b), edge=3, dock=side, dock_top=y).  The rect is the band the fighters use, in app
    coordinates: its bottom is the Dock's top edge (bottom Dock) or the bottom of the visible frame (any other Dock).
    Always edge 3 (bottom) and never auto-hide, so the Windows-shaped code never hides the fighters on a Mac."""
    primary_h = frame[3] if primary_h is None else primary_h
    side = dock_side(frame, visible)
    vx, vy, vw, vh = visible
    # bottom of the visible frame, in app coordinates: the Dock's top edge for a bottom Dock, else (near) the screen bottom
    bottom = int(round(primary_h - vy))
    left, right = int(round(vx)), int(round(vx + vw))          # a side Dock narrows the visible frame: stay clear of it
    rect = (left, bottom - int(strip), right, bottom)
    return dict(rect=rect, edge=EDGE_BOTTOM, dock=side, dock_top=bottom)


def monitors_from_frames(screens):
    """screens: [(frame, visible_frame, backing_scale)] in NSScreen.screens() order (index 0 = the menu-bar screen).
    -> [{'index': 1-based, 'rect', 'work', 'primary', 'scale'}] in app coordinates, the shape shell.monitors() returns
    on Windows (plus 'scale': 2.0 on Retina)."""
    if not screens:
        return []
    primary_h = screens[0][0][3]
    out = []
    for i, (frame, visible, scale) in enumerate(screens):
        out.append(dict(index=i + 1, rect=to_app_rect(frame, primary_h), work=to_app_rect(visible, primary_h),
                        primary=i == 0, scale=float(scale or 1.0)))
    return out


# ------------------------------------------------------------------ click-through
def alpha_solid(alpha, lx, ly, radius=1):
    """True when the logical pixel (lx, ly) of a window's last frame, or one within `radius`, is not fully transparent.
    `alpha` is a PIL 'L' image (the frame's alpha channel) or None."""
    if alpha is None:
        return False
    w, h = alpha.size
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = int(lx) + dx, int(ly) + dy
            if 0 <= x < w and 0 <= y < h and alpha.getpixel((x, y)) > 0:
                return True
    return False


def window_solid_at(mouse, win_rect, scale, alpha=None, on_hittest=None):
    """Should the window take the mouse at app point `mouse`?  win_rect is the window's (l, t, r, b) in points, scale the
    integer sprite scale.  on_hittest (the scoreboard's buttons, the arena's EXIT) wins; otherwise opaque pixels do -
    the macOS stand-in for WM_NCHITTEST, applied with NSWindow.setIgnoresMouseEvents_."""
    if mouse is None:
        return False
    mx, my = mouse
    l, t, r, b = win_rect
    if not (l <= mx < r and t <= my < b):
        return False
    lx, ly = (mx - l) // max(1, scale), (my - t) // max(1, scale)
    if on_hittest is not None:
        try:
            return bool(on_hittest(lx, ly))
        except Exception:
            return False
    return alpha_solid(alpha, lx, ly)


# ------------------------------------------------------------------ keys
# macOS virtual key codes (Carbon kVK_*) -> the Windows VK codes minis_core.select.Model.key expects
MAC_KEYS = {123: 0x25, 126: 0x26, 124: 0x27, 125: 0x28,          # arrows: left up right down
            36: 0x0D, 76: 0x0D, 49: 0x20, 53: 0x1B, 51: 0x08, 117: 0x08, 48: 0x09,   # return, enter, space, esc, delete, fwd-del, tab
            116: 0x21, 121: 0x22, 115: 0x24}                                       # page up, page down, home (the move book)


def vk_from_mac(keycode):
    return MAC_KEYS.get(int(keycode))


# ------------------------------------------------------------------ arena platforms (Quartz window list)
# Only these keys of a CGWindowListCopyWindowInfo entry are ever read.  kCGWindowName and kCGWindowOwnerName are never
# touched (reading them is also what would need the Screen Recording permission); tests enforce it.
CG_KEYS = ('kCGWindowNumber', 'kCGWindowLayer', 'kCGWindowBounds', 'kCGWindowOwnerPID', 'kCGWindowAlpha')


def _bounds(d):
    b = d['kCGWindowBounds']
    return float(b['X']), float(b['Y']), float(b['Width']), float(b['Height'])


def platforms_from_cg(infos, own_pid, exclude=()):
    """[(number, l, t, r, b)] of normal (layer 0), visible windows of other processes, front to back, from the dicts
    CGWindowListCopyWindowInfo returns.  Bounds only: no title, no owner name."""
    out = []
    excl = {int(e) for e in exclude if e}
    for d in infos or ():
        try:
            if int(d['kCGWindowLayer']) != 0:
                continue
            if int(d['kCGWindowOwnerPID']) == int(own_pid):
                continue
            num = int(d['kCGWindowNumber'])
            if num in excl:
                continue
            if 'kCGWindowAlpha' in d and float(d['kCGWindowAlpha']) <= 0.0:
                continue
            x, y, w, h = _bounds(d)
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        out.append((num, int(x), int(y), int(x + w), int(y + h)))
    return out


def menubar_plate_origin(slot, frame, visible, notch_left, w, h, gap, margin=8):
    """App point (x, y) of HUD plate `slot` ('a' | 'b') in the menu bar.  frame / visible: the screen's Cocoa frame and
    visibleFrame (x, y, w, h); notch_left: Cocoa x where the camera notch starts, or None.  The pair sits right-aligned just
    left of the notch (MacBooks with one: the free stretch between the app menus and the notch), else centred; vertically
    centred in the menu bar (24 pt when it is hidden)."""
    fx, fy, fw, fh = frame
    vx, vy, vw, vh = visible
    bar = (fy + fh) - (vy + vh)
    if bar <= 0:
        bar = 24
    total = 2 * w + gap
    x0 = (notch_left - margin - total) if notch_left else fx + (fw - total) / 2.0
    x0 = max(fx + margin, x0)
    x = x0 if slot == 'a' else x0 + w + gap
    return int(round(x)), int(max(0, (bar - h) // 2))


STATUS_LAYER = 25                                       # kCGStatusWindowLevel: menu-bar status items (and our panels)


def status_item_shown(infos, pid, menubar_h=64):
    """Is process `pid`'s menu-bar icon on screen?  True / False (macOS hides icons that do not fit: a full menu bar, or
    the notch on a MacBook) / None (no status item found).  `infos` must come from kCGWindowListOptionAll, since a hidden
    item is missing from the on-screen list.  Bounds and flags only, never a name."""
    found = None
    for d in infos or ():
        try:
            if int(d['kCGWindowOwnerPID']) != int(pid) or int(d['kCGWindowLayer']) != STATUS_LAYER:
                continue
            x, y, w, h = _bounds(d)
        except (KeyError, TypeError, ValueError):
            continue
        if y > 1 or h > menubar_h or w > 4 * menubar_h:       # a fighter / plate / scoreboard panel, not the status item
            continue
        if d.get('kCGWindowIsOnscreen'):
            return True
        found = False
    return found


def fullscreen_from_cg(infos, own_pid, screen_rect):
    """True when another process has a normal window covering the whole of `screen_rect` (l, t, r, b) - a full-screen
    app, game or presentation (a zoomed window leaves the menu bar uncovered, so it does not count)."""
    l, t, r, b = screen_rect
    for num, wl, wt, wr, wb in platforms_from_cg(infos, own_pid):
        if wl <= l and wt <= t and wr >= r and wb >= b:
            return True
    return False


BADGE = 22                                              # the menu-bar fallback badge (points)


def menubar_badge_origin(frame, visible, notch_left, plates_in_menubar, plate_w, plate_h, gap, margin=8):
    """App point (x, y) of the fallback badge shown when macOS hides the status item (FOUND-3: a full menu bar, or the
    notch).  It sits in the free stretch just left of the notch (else centred), left of the HUD plates when they are in
    the menu bar too, vertically centred in the menu bar.  Pure."""
    fx, fy, fw, fh = frame
    vx, vy, vw, vh = visible
    bar = (fy + fh) - (vy + vh)
    if bar <= 0:
        bar = 24
    if plates_in_menubar:
        right = menubar_plate_origin('a', frame, visible, notch_left, plate_w, plate_h, gap, margin)[0] - gap
    else:
        right = (notch_left - margin) if notch_left else fx + (fw + BADGE) / 2.0
    x = max(fx + margin, right - BADGE)
    return int(round(x)), int(max(2, (bar - BADGE) // 2))      # y >= 2: status_item_shown never mistakes it for the icon
