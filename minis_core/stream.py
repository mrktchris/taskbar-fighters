r"""Streamer mode (growth): a normal, capturable window that shows the live fight for OBS - built from the fighters' OWN
frames, never from a screen capture.  docs/STREAMING.md is the setup guide.

    python minis.py stream on [--chroma #00FF00] [--scale N] [--fps F] [--transparent] [--no-plates]
    python minis.py stream off
    python minis.py stream status
    python minis.py stream snapshot <png>       one composited frame (the same pixels the window shows) to a file

How the pixels get here: the stream process writes a dump request (minis_core/dump.py) with its own id `stream`; while it
is active every fighter, plate and scoreboard process writes the image it hands to its own window into
<data dir>/dump/stream/.  The stream reads the newest image of each role, pastes it at that window's screen rect into a
strip (the union of every rect seen, so the framing holds still), scales the strip by a whole number to fit the window
and fills the rest with the key colour.  Consumed files are deleted as it goes; on exit the request and the folder go.
`tools/own_capture.py` uses the same mechanism; while it runs the stream reads its folder and leaves its files alone.

The window is an ordinary app window (title "Taskbar Fighters — Stream"): not layered, not topmost, not click-through,
resizable, in the taskbar / Dock, so OBS's Window Capture lists it.  Closing it ends the stream process.  Starting a
stream turns desktop weapons off (the arena's RAM screen grab) and `stream off` puts back what was there before.
Nothing here reads the screen, a window title or another program's window.
"""
from __future__ import annotations
import json, os, re, shutil, sys, time
from pathlib import Path
from PIL import Image

from . import config as cfgmod, dump
from .bus import write_json_atomic

TITLE = 'Taskbar Fighters — Stream'
REQ_ID = 'stream'
ROLES = ('scoreboard', 'a-plate', 'b-plate', 'a', 'b')        # paint order: fighters on top
PLATE_ROLES = ('a-plate', 'b-plate')
HUD_ROLES = PLATE_ROLES + ('scoreboard',)
HUD_BACK = (18, 18, 22, 255)                                     # the HUD panels' own dark, made solid
DEFAULT_CHROMA = (0, 255, 0)
DEFAULT_FPS = 15.0
REQ_SPAN_S = 30.0                                                # the request is refreshed long before it lapses
MARGIN = 6
HEARTBEAT_S = 1.0
FRESH_S = 4.0
MAX_DIM = 4096                                                   # window width / height (px) a stream may ask for
MAX_SCALE = 8                                                    # --scale
MAX_PIXELS = 4096 * 2304                                         # any frame fit() allocates (a 4K-ish RGBA frame, ~38 MB)
START_GRACE_S = 8.0                                              # `stream off` waits this long for a stream still starting


def state_path() -> Path:
    return cfgmod.data_dir() / 'stream.json'


def parse_color(s):
    """'#00FF00' / '00ff00' / 'magenta' / '255,0,255' -> (r, g, b); ValueError otherwise."""
    named = {'green': (0, 255, 0), 'blue': (0, 0, 255), 'magenta': (255, 0, 255), 'black': (0, 0, 0)}
    t = str(s or '').strip().lower()
    if t in named:
        return named[t]
    m = re.fullmatch(r'#?([0-9a-f]{6})', t)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    parts = [p.strip() for p in t.split(',')]
    if len(parts) == 3 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return tuple(int(p) for p in parts)
    raise ValueError(f'not a colour: {s!r} (use #RRGGBB)')


# ---------------------------------------------------------------- the feed (dump request + newest records)
class Feed:
    """Owns the `stream` dump request and reads the newest record of every role.  root: the dump root (tests)."""

    def __init__(self, root=None, every_ms=None, wall=time.time, roles=ROLES, req_id=REQ_ID):
        self.root = Path(root) if root else dump.dump_root()
        self.req_id = req_id                                      # 'stream' for the window, 'snapshot' for a one-off frame
        self.every_ms = int(every_ms or 1000 / DEFAULT_FPS)
        self.wall = wall
        self.roles = tuple(roles)
        self.req_until = 0.0
        self.foreign = None                                       # the id of somebody else's active request, if any
        self._img = {}                                            # png name -> image (decoded once)

    def _read_req(self):
        try:
            return json.loads(dump.request_path(self.root).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def ensure_request(self, now=None):
        """Write / refresh our request unless another one (own_capture) is active.  -> the id whose folder to read."""
        now = self.wall() if now is None else now
        cur = dump.parse_request(self._read_req(), now)
        if cur is not None and cur['id'] != self.req_id:
            self.foreign = cur['id']
            return cur['id']
        self.foreign = None
        if cur is None or cur['until'] - now < REQ_SPAN_S / 2:
            self.root.mkdir(parents=True, exist_ok=True)
            write_json_atomic(dump.request_path(self.root), {'id': self.req_id, 'until': now + REQ_SPAN_S, 'every_ms': self.every_ms})
            self.req_until = now + REQ_SPAN_S
        return self.req_id

    def release(self):
        """Drop our request (only ours) and our folder."""
        cur = self._read_req()
        if isinstance(cur, dict) and cur.get('id') == self.req_id:
            try:
                dump.request_path(self.root).unlink()
            except OSError:
                pass
        d = dump.safe_dir(self.root, self.req_id)
        if d is not None:
            shutil.rmtree(d, ignore_errors=True)

    def records(self, rid):
        """-> {role: newest record} in the folder of request `rid`; when it is ours, older files are deleted."""
        d = dump.safe_dir(self.root, rid)
        if d is None or not d.is_dir():
            return {}
        recs = {}
        olds = []
        for p in d.glob('*.json'):
            try:
                r = json.loads(p.read_text(encoding='utf-8'))
                if r.get('role') not in self.roles:
                    continue
                r['wall'] = float(r['wall'])
                for k in ('x', 'y', 'w', 'h'):
                    r[k] = int(r[k])
                r['_file'] = p
            except Exception:
                continue
            best = recs.get(r['role'])
            if best is None or r['wall'] > best['wall']:
                if best is not None:
                    olds.append(best)
                recs[r['role']] = r
            else:
                olds.append(r)
        if rid == self.req_id:                                         # our folder: keep only what the newest records need
            keep = {r.get('png') for r in recs.values()}
            for r in olds:
                for f in (r['_file'], d / str(r.get('png') or '')):
                    if f.name and f.name not in keep and f.suffix in ('.json', '.png') and f.parent == d:
                        try:
                            f.unlink()
                        except OSError:
                            pass
            self._img = {k: v for k, v in self._img.items() if k in keep}
        return recs

    def image(self, rid, rec):
        name = Path(str(rec.get('png') or '')).name                 # a bare name, never a path out of the folder
        if not name.endswith('.png'):
            return None
        key = (rid, name, rec['w'], rec['h'])
        im = self._img.get(key)
        if im is None:
            d = dump.safe_dir(self.root, rid)
            try:
                with Image.open(d / name) as f:
                    im = f.convert('RGBA')
            except Exception:
                return None
            if im.size != (rec['w'], rec['h']):                     # a Retina HUD image (density 2) or a scaled window
                down = im.width > rec['w']
                im = im.resize((rec['w'], rec['h']), Image.LANCZOS if down else Image.NEAREST)
            self._img[key] = im
        return im


# ---------------------------------------------------------------- composing the strip
class Strip:
    """Pastes the newest records at their screen rects into one strip.  The box is the union of every rect seen, so the
    framing does not jump when a fighter walks."""

    def __init__(self, roles=ROLES, opaque_hud=True):
        """opaque_hud: the plates' and scoreboard's see-through dark panels are made solid, so a chroma key never sees key
        colour bleeding through them (off for --transparent, which keeps their alpha)."""
        self.roles = tuple(roles)
        self.opaque_hud = bool(opaque_hud)
        self.box = None

    def grow(self, recs):
        for role in self.roles:
            r = recs.get(role)
            if not r or not r.get('visible', True) or r['w'] <= 0 or r['h'] <= 0:
                continue
            b = (r['x'] - MARGIN, r['y'] - MARGIN, r['x'] + r['w'] + MARGIN, r['y'] + r['h'] + MARGIN)
            self.box = b if self.box is None else (min(self.box[0], b[0]), min(self.box[1], b[1]), max(self.box[2], b[2]), max(self.box[3], b[3]))
        return self.box

    def compose(self, recs, image_of):
        """-> RGBA strip (transparent where nothing is drawn), or None before any window has shown itself."""
        box = self.grow(recs)
        if box is None:
            return None
        c = Image.new('RGBA', (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
        for role in self.roles:
            r = recs.get(role)
            if not r or not r.get('visible', True):
                continue
            im = image_of(r)
            if im is None:
                continue
            if self.opaque_hud and role in HUD_ROLES:
                solid = Image.new('RGBA', im.size, HUD_BACK)
                solid.putalpha(im.getchannel('A').point(lambda v: 255 if v else 0))
                solid.alpha_composite(im)
                im = solid
            layer = Image.new('RGBA', c.size, (0, 0, 0, 0))
            layer.paste(im, (r['x'] - box[0], r['y'] - box[1]))
            c.alpha_composite(layer)
        return c


def fit(strip, w, h, bg=DEFAULT_CHROMA, transparent=False, scale=None):
    """The strip scaled by a whole number (nearest) to fit w x h, centred on the key colour (alpha 0 when transparent).
    scale: a fixed factor instead of the largest that fits.  -> (RGBA image of w x h, factor used)."""
    w, h = max(1, min(MAX_DIM, int(w))), max(1, min(MAX_DIM, int(h)))
    while w * h > MAX_PIXELS:                                      # never allocate past the cap, whatever was asked
        w, h = max(1, w * 3 // 4), max(1, h * 3 // 4)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0) if transparent else tuple(bg) + (255,))
    if strip is None:
        return out, 0
    k = int(scale) if scale else max(1, min(w // max(1, strip.width), h // max(1, strip.height)))
    k = max(1, min(MAX_SCALE, k))
    while k > 1 and strip.width * strip.height * k * k > MAX_PIXELS:
        k -= 1
    big = strip.resize((strip.width * k, strip.height * k), Image.NEAREST) if k != 1 else strip
    x, y = (w - big.width) // 2, (h - big.height) // 2
    if transparent:
        out.paste(big, (x, y))
    elif x >= 0 and y >= 0:
        out.alpha_composite(big, (x, y))
    else:                                                          # a fixed scale larger than the window: cropped
        out.paste(big, (x, y), big)
    return out, k


def placeholder(w, h, bg=DEFAULT_CHROMA, transparent=False, text='waiting for the fighters...'):
    """What the window shows before any fighter has drawn (or after `stop`): the key colour and one dim line."""
    from PIL import ImageDraw
    from .render import font
    im, _ = fit(None, w, h, bg, transparent)
    d = ImageDraw.Draw(im)
    f = font(14, True)
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, h / 2 - 8), text, fill=(20, 20, 24, 255) if not transparent else (230, 230, 240, 255), font=f)
    return im


# ---------------------------------------------------------------- process state (stream.json)
def read_state(path=None):
    try:
        d = json.loads(Path(path or state_path()).read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def running(path=None, now=None, alive=None):
    """-> the stream's pid while its heartbeat is fresh (and, given `alive`, the pid is alive), else None."""
    d = read_state(path)
    now = time.time() if now is None else now
    try:
        if d.get('active') and 0 <= now - float(d.get('ts', 0)) <= FRESH_S and isinstance(d.get('pid'), int):
            if alive is None or alive(d['pid']):
                return d['pid']
    except (TypeError, ValueError):
        pass
    return None


def stop_path() -> Path:
    return cfgmod.data_dir() / 'stream-stop.json'


def request_stop(path=None, now=None):
    """`stream off`: a separate file, so the stream's own heartbeat writes can never overwrite the request."""
    return write_json_atomic(Path(path or stop_path()), {'stop': time.time() if now is None else now})


def stop_requested(since, path=None) -> bool:
    try:
        return float(json.loads(Path(path or stop_path()).read_text(encoding='utf-8')).get('stop', 0)) > float(since)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


# ---------------------------------------------------------------- one stream at a time (stream.lock)
def lock_path() -> Path:
    return cfgmod.data_dir() / 'stream.lock'


def lock_owner(path=None):
    try:
        return int(json.loads(Path(path or lock_path()).read_text(encoding='utf-8'))['pid'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def lock_since(path=None):
    """When the current `stream on` took the lock (wall s) - the threshold a stop request must be newer than."""
    try:
        return float(json.loads(Path(path or lock_path()).read_text(encoding='utf-8')).get('since') or 0.0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0


def _write_excl(lp, payload) -> bool:
    """O_CREAT | O_EXCL create with the payload written at once.  False when the file exists (on Windows also while a
    just-deleted one is still pending: PermissionError), so the caller re-reads instead of raising."""
    try:
        fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, PermissionError):
        return False
    data = json.dumps(payload).encode('utf-8')
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return True


def _unlink_retry(lp, tries=40, wait=time.sleep) -> bool:
    """Unlink a file another process may hold open for a moment (Windows: a reader without FILE_SHARE_DELETE makes the
    unlink fail with PermissionError); retried for ~0.2 s."""
    for _ in range(tries):
        try:
            lp.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            wait(0.005)
    return False


def _rename_away(lp) -> bool:
    """Atomically move a file out of the way (os.replace to a unique name) and delete it.  Exactly one of several callers
    wins the rename; the others see FileNotFoundError and return False."""
    gone = lp.with_name(f'.{lp.name}.{os.getpid()}.{time.monotonic_ns()}.gone')
    try:
        os.replace(lp, gone)
    except OSError:
        return False
    _unlink_retry(gone)
    return True


def _default_alive(pid):
    try:
        import minis_platform as plat
        return bool(plat.procs().alive(pid))
    except Exception:
        return True                                               # cannot tell: treat the lock as held (never steal it)


def acquire_lock(pid, alive=None, path=None, now=None, wait=time.sleep) -> bool:
    """Create stream.lock atomically (O_CREAT | O_EXCL) holding `pid` and the time it was taken.  A live owner keeps it.
    A lock whose pid is dead is stale and reclaimed under a second O_EXCL guard (stream.lock.reclaim), so only ONE of
    several starters that read the same dead pid removes it and creates the fresh lock; the guard holder re-reads the
    lock first, so a lock somebody else already renewed is never removed.  A guard left by a reclaimer that died is
    moved away atomically (one winner) and retried.  -> True when `pid` now owns the lock."""
    lp = Path(path or lock_path())
    guard = lp.with_name(lp.name + '.reclaim')
    alive = alive or _default_alive
    now = time.time() if now is None else now
    payload = {'pid': int(pid), 'since': float(now)}
    unreadable = 0
    for _ in range(12):
        if _write_excl(lp, payload):
            return True
        other = lock_owner(lp)
        if other == pid:
            return True
        if other is not None and alive(other):
            return False
        if other is None and lp.exists():                         # being written this instant, or truly garbage
            unreadable += 1
            if unreadable < 6:
                wait(0.01)                                        # give a live writer its microseconds; then it is stale
                continue
        # stale (dead owner, or unreadable for good): reclaim it under the guard
        if not _write_excl(guard, {'pid': int(pid)}):
            g = lock_owner(guard)
            if g is not None and g != pid and alive(g):
                return False                                      # another starter is reclaiming right now: it wins
            if g is None and guard.exists():
                wait(0.01)                                        # its holder is writing it; read again
                continue
            _rename_away(guard)                                   # a dead reclaimer's guard; one of us removes it
            continue
        try:
            again = lock_owner(lp)
            if again is not None and again != other and alive(again):
                return False                                      # renewed between our read and the guard: theirs
            if lp.exists() and not _rename_away(lp):
                continue
            if _write_excl(lp, payload):
                return True
        finally:
            _unlink_retry(guard)
    return False


def hand_lock(from_pid, to_pid, path=None) -> bool:
    """`stream on` acquires the lock, spawns `stream run`, then hands the lock to the child's pid (its `since` stays)."""
    lp = Path(path or lock_path())
    if lock_owner(lp) != from_pid:
        return False
    return write_json_atomic(lp, {'pid': int(to_pid), 'since': lock_since(lp)})


def release_lock(pid, path=None) -> bool:
    """Remove stream.lock only when `pid` owns it."""
    lp = Path(path or lock_path())
    if lock_owner(lp) != pid:
        return False
    return _unlink_retry(lp)


def claim_for_run(pid, parent, alive=None, wait=time.sleep, tries=20):
    """The `stream run` process: own the lock, or take it over from the parent `stream on` that is handing it over.
    -> True when this process may run."""
    alive = alive or _default_alive
    for _ in range(tries):
        owner = lock_owner()
        if owner is None:
            if acquire_lock(pid, alive):
                return True
        elif owner == pid:
            return True
        elif owner == parent:
            wait(0.1)                                             # the parent writes our pid in a moment
        elif not alive(owner):
            if acquire_lock(pid, alive):
                return True
        else:
            return False
    return lock_owner() == pid or (lock_owner() == parent and hand_lock(parent, pid))


# ---------------------------------------------------------------- the stream process
def run(opts, window_mod=None, wall=time.time, mono=time.monotonic, max_frames=None, log=None):
    """The `stream run` body: open the window, feed it frames until it is closed or `stream off` asks.  -> exit code."""
    import logging
    log = log or logging.getLogger('minis.null')
    if window_mod is None:
        import importlib
        import minis_platform as plat
        window_mod = importlib.import_module(plat.package() + '.stream_window')
    me = os.getpid()
    launched = wall()
    if not claim_for_run(me, os.getppid(), alive=opts.get('alive')):
        log.info('stream: another stream owns stream.lock (pid %s); not starting', lock_owner())
        return 1
    since = min(launched, lock_since() or launched)               # `stream on` took the lock: a stop after that counts
    sp = state_path()
    if stop_requested(since):                                     # `stream off` arrived before we got this far
        log.info('stream: stop requested during startup; not opening the window')
        write_json_atomic(sp, dict(pid=me, active=False, ts=wall(), ended='stop'))
        release_lock(me)
        _restore_forge(opts)
        return 0
    roles = tuple(r for r in ROLES if not (opts.get('no_plates') and r in PLATE_ROLES))
    fps = max(2.0, min(30.0, float(opts.get('fps') or DEFAULT_FPS)))
    feed = Feed(every_ms=int(1000 / fps), wall=wall, roles=roles)
    bg = tuple(opts.get('chroma') or DEFAULT_CHROMA)
    transparent = bool(opts.get('transparent'))
    strip = Strip(roles, opaque_hud=not transparent)
    scale = int(opts['scale']) if opts.get('scale') else None
    try:
        win = window_mod.StreamWindow(TITLE, opts.get('width') or 960, opts.get('height') or 300, transparent=transparent, bg=bg)
    except Exception:
        release_lock(me)
        raise
    started = wall()
    st = dict(pid=os.getpid(), active=True, started=started, ts=started, chroma='#%02X%02X%02X' % bg, transparent=transparent,
              forge_was=opts.get('forge_was'))
    write_json_atomic(sp, st)
    shutil.rmtree(dump.dump_root() / REQ_ID, ignore_errors=True)  # leftovers of a stream that died
    n = 0
    last_beat = -1e9
    ended = 'error'
    try:
        while True:
            t0 = mono()
            if not win.pump() or win.closed:
                ended = 'closed'
                break
            now = wall()
            if now - last_beat >= HEARTBEAT_S:
                last_beat = now
                if stop_requested(since):                         # also one that landed while the window was opening
                    log.info('stream: stop requested')
                    ended = 'stop'
                    break
                write_json_atomic(sp, dict(st, ts=now))
            rid = feed.ensure_request(now)
            recs = feed.records(rid)
            img = strip.compose(recs, lambda r: feed.image(rid, r))
            cw, ch = win.client_size()
            frame = fit(img, cw, ch, bg, transparent, scale)[0] if img is not None else placeholder(cw, ch, bg, transparent)
            win.present(frame)
            n += 1
            if max_frames is not None and n >= max_frames:
                ended = 'frames'
                break
            win.wait(max(0.0, 1.0 / fps - (mono() - t0)))
    finally:
        feed.release()
        try:
            win.close()
        except Exception:
            pass
        if read_state(sp).get('pid') == me:                         # only our own state is closed out
            write_json_atomic(sp, dict(read_state(sp), active=False, ts=wall(), ended=ended))
        release_lock(me)
        _restore_forge(opts)
    return 0


def _restore_forge(opts):
    """Desktop weapons come back when the stream ends, however it ended (its own close button included)."""
    if opts.get('forge_was') == 'on':
        try:
            from . import control
            if not control.forge_on():
                control.set_forge(True)
        except Exception:
            pass


SNAP_ID = 'snapshot'


def snapshot(out_path=None, seconds=2.0, opts=None, wall=time.time, sleep=time.sleep):
    """One composited frame to a PNG, at the strip's natural size x scale (default 2) on the key colour, from the fighters'
    own images (they must be running).  out_path follows exports.resolve (default <data dir>/exports/).  It uses its own
    dump request id, so it never touches a running stream's folder.  -> the Path, or None when no window answered."""
    from . import exports
    target = exports.resolve(out_path, 'taskbar-fighters-stream-' + time.strftime('%Y%m%d-%H%M%S') + '.png')
    opts = opts or {}
    roles = tuple(r for r in ROLES if not (opts.get('no_plates') and r in PLATE_ROLES))
    feed = Feed(wall=wall, roles=roles, req_id=SNAP_ID)
    strip = Strip(roles, opaque_hud=not opts.get('transparent'))
    bg = tuple(opts.get('chroma') or DEFAULT_CHROMA)
    img = None
    own = running() is None                                        # a running stream owns the request: just read it
    try:
        end = wall() + seconds
        while wall() < end:
            rid = feed.ensure_request() if own else REQ_ID
            recs = feed.records(rid) if own else Feed(roles=roles, req_id='-').records(rid)   # never prunes the stream's files
            got = strip.compose(recs, lambda r: feed.image(rid, r))
            if got is not None and len(recs) >= 2:
                img = got
            sleep(0.3)
    finally:
        if own:
            feed.release()
    if img is None:
        return None
    k = int(opts.get('scale') or 2)
    frame, _ = fit(img, img.width * k + 32, img.height * k + 32, bg, bool(opts.get('transparent')), k)
    frame.save(target)
    return target


# ---------------------------------------------------------------- `minis.py stream ...`
def options_from(args):
    o = {}
    if getattr(args, 'chroma', None):
        o['chroma'] = parse_color(args.chroma)
    for k in ('scale', 'fps', 'width', 'height'):
        v = getattr(args, k, None)
        if v is not None:                                             # 0 is an answer too: refused below, never ignored
            cap = MAX_SCALE if k == 'scale' else (30 if k == 'fps' else MAX_DIM)
            if k != 'fps' and (int(v) != v or v < 1):
                raise ValueError(f'--{k} must be a whole number of at least 1')
            if v > cap or v < (2 if k == 'fps' else 1):
                raise ValueError(f'--{k} {v} is out of range (1..{cap})' if k != 'fps' else f'--fps {v} is out of range (2..30)')
            o[k] = v
    o['transparent'] = bool(getattr(args, 'transparent', False))
    o['no_plates'] = bool(getattr(args, 'no_plates', False))
    return o


def option_argv(o):
    a = []
    if o.get('chroma'):
        a += ['--chroma', '#%02X%02X%02X' % tuple(o['chroma'])]
    for k in ('scale', 'fps', 'width', 'height'):
        if o.get(k):
            a += [f'--{k}', str(o[k])]
    if o.get('transparent'):
        a.append('--transparent')
    if o.get('no_plates'):
        a.append('--no-plates')
    return a


def cmd(args, spawn=None, self_argv=None, alive=None, out=print, sleep=time.sleep):
    from . import control
    act = getattr(args, 'action', None) or 'status'
    try:
        o = options_from(args)
    except ValueError as e:
        out(str(e))
        return 2
    pid = running(alive=alive)
    if act == 'status':
        d = read_state()
        out(f"stream: running (pid {pid}, key {d.get('chroma')}{', transparent' if d.get('transparent') else ''})" if pid
            else 'stream: off')
        return 0
    if act == 'on':
        if pid:
            out(f'stream: already running (pid {pid}); `stream off` first to change its options')
            return 1
        if os.environ.get('MINIS_TESTING'):
            out('stream: refused under tests (MINIS_TESTING)')
            return 1
        me = os.getpid()
        if not acquire_lock(me, alive):
            out(f'stream: another stream is starting or running (pid {lock_owner()}); `stream off` first')
            return 1
        try:
            was = control.forge_on()
            if was:
                control.set_forge(False)
            argv = self_argv('stream', 'run', '--forge-was', 'on' if was else 'off', *option_argv(o))
            child = spawn(argv)
        except Exception:
            release_lock(me)
            raise
        if getattr(child, 'pid', None):
            hand_lock(me, child.pid)                              # the child owns it from now on
        else:
            release_lock(me)
        out(f"stream: window \"{TITLE}\" opening; add it in OBS as a Window Capture with a Chroma Key filter "
            f"({'transparent background' if o.get('transparent') else '#%02X%02X%02X' % tuple(o.get('chroma') or DEFAULT_CHROMA)})."
            + ('  Desktop weapons are off while streaming.' if was else ''))
        return 0
    if act == 'off':
        owner = lock_owner()
        starting = owner is not None and owner != pid and (alive or _default_alive)(owner)   # locked, no heartbeat yet
        if not pid and not starting:
            out('stream: not running')
            return 0
        request_stop()                                            # newer than the lock's `since`: the child honours it

        def gone():
            o = lock_owner()
            return running(alive=alive) is None and (o is None or not (alive or _default_alive)(o))
        for _ in range(int(START_GRACE_S / 0.2)):
            if gone():
                break
            sleep(0.2)
        d = read_state()
        if d.get('forge_was') == 'on' and not control.forge_on():
            control.set_forge(True)
        out('stream: stopped' if gone() else f'stream: asked pid {pid or owner} to close; close the window if it stays')
        return 0
    if act == 'run':
        o['forge_was'] = getattr(args, 'forge_was', None)
        return run(o)
    if act == 'snapshot':
        from . import exports
        try:
            p = snapshot(getattr(args, 'path', None), opts=o)
        except exports.ExportPathError as e:
            out(f'stream snapshot: refused: {e}')
            return 2
        out(f'stream snapshot: {p}' if p else 'stream snapshot: no fighter window answered (is Taskbar Fighters running?)')
        return 0 if p else 1
    out('stream: on | off | status | snapshot [png | folder]')
    return 2
