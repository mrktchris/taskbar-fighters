r"""Community skin packs (growth): new looks any program can wear, loaded as data only.  docs/SKIN-PACKS.md is the format.

Where packs live: <data dir>/packs/<name>/ (%LOCALAPPDATA%\minis\packs on Windows, ~/Library/Application Support/minis/packs
on macOS).  A pack is drawn as the character id `pack-<name>`: it appears in fighter select's LOOK grid, in the fighter
menu's Look submenu and works with `minis.py skin <program> pack-<name>` (or its display name).

    <name>/pack.json          {"format": 1, "name", "display", "author", "license", "version"?, "description"?}
    <name>/64/anim.json       the atlas schema (minis_core/atlas.py) at RES 1: 64 px cells        (required)
    <name>/64/sheet.png, sheet_l.png [, sheet_unarmed.png, sheet_unarmed_l.png] [, proj.png]
    <name>/128/...            the same at RES 2: 128 px cells (optional; without it the 64 px art is scaled 2x)
    <name>/LICENSE[.txt|.md], README.md, preview.png        (optional)

Safety: nothing from a pack is ever executed or imported - packs are JSON and PNG files read with json and Pillow.
`validate()` is strict: only the file names above (no other file, no sub-folder, no symlink), size caps per file and per
pack, PNG only, exact sheet geometry, a palette cap, every move the engine plays, and file names in anim.json fixed to the ones above.
`install()` takes a .zip or a folder: every zip entry is checked (no absolute path, no `..`, no drive letter, no symlink,
caps on count / size / compression ratio) and unpacked into a temp folder inside packs/, validated, then moved in place.
No network: installing is copying a file you already have.
"""
from __future__ import annotations
import json, os, re, shutil, stat, tempfile, zipfile
from pathlib import Path, PurePosixPath

from . import config as cfgmod

FORMAT = 1
PREFIX = 'pack-'
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,31}$')
SIZES = {'64': 1, '128': 2}                       # sub-folder -> atlas res
SHEET_FILES = ('sheet.png', 'sheet_l.png', 'sheet_unarmed.png', 'sheet_unarmed_l.png', 'proj.png')
SIZE_FILES = ('anim.json',) + SHEET_FILES
TOP_FILES = ('pack.json', 'LICENSE', 'LICENSE.txt', 'LICENSE.md', 'README.md', 'preview.png')
MAX_FILES = 24
MAX_PACK_BYTES = 16 * 1024 * 1024
MAX_PNG_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024
MAX_COLORS = 64                                   # per sheet (RGBA): pixel art; the built-in sheets use 24-42
MAX_COLS, MAX_ROWS = 12, 80                       # built-ins: 8 columns, 68-69 rows
MAX_SHEET_PIXELS = MAX_COLS * 128 * MAX_ROWS * 128  # one sheet at 128 px: at most 1536 x 10240 (60 MiB decoded as RGBA)
MAX_DECODED_BYTES = 256 * 1024 * 1024             # every PNG in a pack, decoded as RGBA (a built-in-sized pack: ~180 MiB)
MAX_PREVIEW = (1200, 1200)
MAX_RATIO = 200                                   # zip: uncompressed / compressed per entry (a zip bomb is refused)
TEXT_MAX = {'name': 32, 'display': 24, 'author': 64, 'license': 64, 'version': 16, 'description': 200}


class PackError(ValueError):
    pass


def packs_dir() -> Path:
    return cfgmod.data_dir() / 'packs'


def char_id(name) -> str:
    return PREFIX + str(name)


def is_pack_id(cid) -> bool:
    return isinstance(cid, str) and cid.startswith(PREFIX) and bool(NAME_RE.match(cid[len(PREFIX):]))


# A fighter (character) id as it appears in record.json, assign.json and fight codes: a built-in character
# (`claude`, `lmstudio`: letters, digits, underscores) or an installed pack (`pack-<name>`, NAME_RE).  The one hyphen
# in a pack id is the one after `pack`; the name may hold more.  Stable: the `ux` branch's fight codes import this.
FIGHTER_ID_RE = re.compile(r'^(?:[a-z][a-z0-9_]{0,31}|pack-[a-z0-9][a-z0-9_-]{1,31})$')


def is_fighter_id(cid) -> bool:
    """True for any id a fighter can carry (built-in or pack).  Never a path, a slash, a dot or upper case."""
    return isinstance(cid, str) and bool(FIGHTER_ID_RE.match(cid))


def split_fighter_id(cid):
    """'claude' -> ('builtin', 'claude'); 'pack-shadow-ronin' -> ('pack', 'shadow-ronin'); anything else -> None."""
    if not is_fighter_id(cid):
        return None
    return ('pack', cid[len(PREFIX):]) if cid.startswith(PREFIX) else ('builtin', cid)


# ---------------------------------------------------------------- what the engine needs
_required = None


def required_anims():
    """The moves every built-in character has (the shared move set: the choreography may ask any fighter for these)."""
    global _required
    if _required is None:
        from . import atlas
        sets = []
        for c in atlas.available():
            try:
                sets.append(set(json.loads((atlas.ASSETS / c / 'anim.json').read_text(encoding='utf-8'))['anims']))
            except (OSError, ValueError, KeyError):
                continue
        _required = sorted(set.intersection(*sets)) if sets else ['idle']
    return list(_required)


def builtin_ids():
    from . import atlas
    return set(atlas.available())


# ---------------------------------------------------------------- validation
def _text_ok(v, key):
    return isinstance(v, str) and 0 < len(v.strip()) <= TEXT_MAX[key] and all(c.isprintable() for c in v)


def read_manifest(d) -> dict:
    p = Path(d) / 'pack.json'
    if not p.is_file() or p.stat().st_size > MAX_TEXT_BYTES:
        raise PackError('pack.json missing or too large')
    try:
        m = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise PackError(f'pack.json is not valid JSON ({type(e).__name__})')
    if not isinstance(m, dict):
        raise PackError('pack.json must be an object')
    if m.get('format') != FORMAT:
        raise PackError(f'pack.json "format" must be {FORMAT}')
    for k in ('name', 'display', 'author', 'license'):
        if not _text_ok(m.get(k), k):
            raise PackError(f'pack.json "{k}" missing or not a short line of text')
    for k in ('version', 'description'):
        if k in m and not _text_ok(m[k], k):
            raise PackError(f'pack.json "{k}" is not a short line of text')
    if not NAME_RE.match(m['name']):
        raise PackError('pack.json "name" must be 2-32 of a-z 0-9 _ - (lower case, starting with a letter or digit)')
    if m['name'] in builtin_ids() or char_id(m['name']) in builtin_ids():
        raise PackError(f"pack name {m['name']!r} is a built-in character")
    return m


def png_size(p):
    """(width, height) from a PNG's IHDR chunk - read from the first 24 bytes, nothing decoded.  PackError when the file
    is not a PNG."""
    try:
        with open(p, 'rb') as fh:
            head = fh.read(24)
    except OSError as e:
        raise PackError(f'{Path(p).name}: unreadable ({type(e).__name__})')
    if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        raise PackError(f'{Path(p).name}: not a PNG')
    return int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')


def check_decoded_budget(d):
    """Before any PNG of the pack is decoded: every PNG's header size within its cap, and all of them together within
    MAX_DECODED_BYTES as RGBA.  -> the total decoded bytes."""
    total = 0
    for f in sorted(Path(d).rglob('*.png')):
        w, h = png_size(f)
        cap = (MAX_PREVIEW[0] * MAX_PREVIEW[1]) if f.name == 'preview.png' else MAX_SHEET_PIXELS
        if w <= 0 or h <= 0 or w * h > cap or w > MAX_COLS * 128 or h > MAX_ROWS * 128:
            raise PackError(f'{f.relative_to(d).as_posix()}: {w}x{h} is larger than a pack sheet may be')
        total += w * h * 4
    if total > MAX_DECODED_BYTES:
        raise PackError(f'the pack would take {total // 2 ** 20} MiB of memory decoded (limit {MAX_DECODED_BYTES // 2 ** 20} MiB)')
    return total


def _png(p, max_colors=MAX_COLORS, want=None):
    """Open one PNG safely -> RGBA image.  The size comes from the header first (`want`: the exact size the anim.json
    grid demands); only a file that passes is decoded."""
    from PIL import Image
    if p.stat().st_size > MAX_PNG_BYTES:
        raise PackError(f'{p.name}: over {MAX_PNG_BYTES // (1024 * 1024)} MB')
    w, h = png_size(p)
    if want is not None and (w, h) != tuple(want):
        raise PackError(f'{p.name}: is {w}x{h}, must be {want[0]}x{want[1]}')
    if w <= 0 or h <= 0 or w * h > MAX_SHEET_PIXELS or w > MAX_COLS * 128 or h > MAX_ROWS * 128:
        raise PackError(f'{p.name}: {w}x{h} is outside the allowed size')
    try:
        with Image.open(p) as im:
            if im.format != 'PNG' or im.size != (w, h):
                raise PackError(f'{p.name}: not a PNG')
            im.verify()
        with Image.open(p) as im:
            rgba = im.convert('RGBA')
    except PackError:
        raise
    except Exception as e:                                         # truncated, bomb, unsupported: refused, never crashes
        raise PackError(f'{p.name}: unreadable PNG ({type(e).__name__})')
    if max_colors and rgba.getcolors(max_colors) is None:
        raise PackError(f'{p.name}: more than {max_colors} colours (pixel art packs keep a small palette)')
    return rgba


def validate_size(d, size) -> dict:
    """Check one <pack>/<size>/ folder -> its anim.json metadata."""
    from . import atlas
    d = Path(d)
    res = SIZES[size]
    cell = 64 * res
    p = d / 'anim.json'
    if not p.is_file() or p.stat().st_size > MAX_JSON_BYTES:
        raise PackError(f'{size}/anim.json missing or too large')
    try:
        meta = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise PackError(f'{size}/anim.json is not valid JSON ({type(e).__name__})')
    if not isinstance(meta, dict):
        raise PackError(f'{size}/anim.json must be an object')
    anims = meta.get('anims')
    if not isinstance(anims, dict) or not anims:
        raise PackError(f'{size}/anim.json: "anims" must be an object of moves')
    for n, a in anims.items():
        if not isinstance(a, dict):
            raise PackError(f'{size}/anim.json: move {str(n)[:40]!r} must be an object')
        if not isinstance(a.get('frames'), list) or not all(isinstance(f, dict) for f in a['frames']):
            raise PackError(f'{size}/anim.json: move {str(n)[:40]!r} needs a "frames" list of objects')
    for key in ('signature', 'projectile', 'anchor', 'sheets', 'sheets_unarmed'):
        if key in meta and meta[key] is not None and not isinstance(meta[key], dict):
            raise PackError(f'{size}/anim.json: "{key}" must be an object')
    try:
        atlas.validate(meta)
    except atlas.AtlasError as e:
        raise PackError(f'{size}/anim.json: {e}')
    if int(meta.get('res') or 1) != res:
        raise PackError(f'{size}/anim.json: "res" must be {res}')
    if list(meta.get('cell') or []) != [cell, cell]:
        raise PackError(f'{size}/anim.json: "cell" must be [{cell}, {cell}]')
    cols = meta.get('cols')
    if not isinstance(cols, int) or not 1 <= cols <= MAX_COLS:
        raise PackError(f'{size}/anim.json: "cols" must be 1..{MAX_COLS}')
    anch = meta.get('anchor')
    if not (isinstance(anch, dict) and all(isinstance(anch.get(s), int) and 0 <= anch[s] < cell for s in 'RL')):
        raise PackError(f'{size}/anim.json: "anchor" needs R and L inside the cell')
    gy = meta.get('ground_y', cell - 7 * res)
    if not isinstance(gy, int) or not 0 < gy <= cell:
        raise PackError(f'{size}/anim.json: "ground_y" must be inside the cell')
    missing = [n for n in required_anims() if n not in meta['anims']]
    if missing:
        raise PackError(f'{size}/anim.json: missing moves the engine plays: {", ".join(missing[:8])}' + (' ...' if len(missing) > 8 else ''))
    rows = 0
    for n, a in meta['anims'].items():
        if not isinstance(n, str) or not re.match(r'^[a-z0-9_]{1,40}$', n):
            raise PackError(f'{size}/anim.json: bad move name {str(n)[:40]!r}')
        r = a.get('row')
        if not isinstance(r, int) or not 0 <= r < MAX_ROWS:
            raise PackError(f'{size}/anim.json: {n}: "row" must be 0..{MAX_ROWS - 1}')
        if len(a['frames']) > cols:
            raise PackError(f'{size}/anim.json: {n}: more frames than "cols"')
        for f in a['frames']:
            if not isinstance(f, dict) or not isinstance(f.get('ms'), int) or not 0 < f['ms'] <= 5000:
                raise PackError(f'{size}/anim.json: {n}: every frame needs "ms" 1..5000')
        rows = max(rows, r + 1)
    sig = meta.get('signature')
    if sig is not None:
        if not isinstance(sig, dict) or any(v is not None and v not in meta['anims'] for v in sig.values()):
            raise PackError(f'{size}/anim.json: "signature" names a move the pack does not have')
    sheets = meta.get('sheets')
    if not (isinstance(sheets, dict) and sheets.get('R') == 'sheet.png' and sheets.get('L') == 'sheet_l.png'):
        raise PackError(f'{size}/anim.json: "sheets" must be {{"R": "sheet.png", "L": "sheet_l.png"}}')
    want = (cols * cell, rows * cell)
    for f in ('sheet.png', 'sheet_l.png'):
        if not (d / f).is_file():
            raise PackError(f'{size}/{f} missing')
        _png(d / f, want=want)                                     # exact grid size from the header, then decoded
    su = meta.get('sheets_unarmed')
    if su is not None:
        if su != {'R': 'sheet_unarmed.png', 'L': 'sheet_unarmed_l.png'}:
            raise PackError(f'{size}/anim.json: "sheets_unarmed" must name sheet_unarmed.png / sheet_unarmed_l.png')
        for f in su.values():
            if not (d / f).is_file():
                raise PackError(f'{size}/{f}: missing')
            _png(d / f, want=want)
    pj = meta.get('projectile')
    if pj:
        if pj.get('file') not in (None, 'proj.png'):
            raise PackError(f'{size}/anim.json: projectile "file" must be proj.png')
        if pj.get('file'):
            pw, ph, nf = pj.get('w'), pj.get('h'), pj.get('frames', 3)
            if not all(isinstance(v, int) and 0 < v <= 4 * cell for v in (pw, ph)) or not isinstance(nf, int) or not 1 <= nf <= 16:
                raise PackError(f'{size}/anim.json: projectile w / h / frames out of range')
            if not (d / 'proj.png').is_file():
                raise PackError(f'{size}/proj.png: missing')
            _png(d / 'proj.png', 32, want=(pw * nf, ph))
    if 'fx' in meta:
        raise PackError(f'{size}/anim.json: per-pack effect sheets ("fx") are not supported; remove the key')
    return meta


def _listing(d):
    """Every entry under a pack folder, checked against the allow-list -> total bytes."""
    d = Path(d)
    total, n = 0, 0
    for p in d.rglob('*'):
        rel = p.relative_to(d).as_posix()
        n += 1
        if n > MAX_FILES + len(SIZES):
            raise PackError(f'more than {MAX_FILES} files')
        if p.is_symlink():
            raise PackError(f'{rel}: links are not allowed')
        if p.is_dir():
            if rel not in SIZES:
                raise PackError(f'{rel}/: only the folders 64/ and 128/ are allowed')
            continue
        parts = rel.split('/')
        ok = (len(parts) == 1 and parts[0] in TOP_FILES) or (len(parts) == 2 and parts[0] in SIZES and parts[1] in SIZE_FILES)
        if not ok:
            raise PackError(f'{rel}: not a pack file (allowed: pack.json, 64/ and 128/ with anim.json and sheet PNGs, '
                            'LICENSE, README.md, preview.png)')
        sz = p.stat().st_size
        if p.suffix in ('.md', '.txt', '') and sz > MAX_TEXT_BYTES:
            raise PackError(f'{rel}: over {MAX_TEXT_BYTES // 1024} KB')
        total += sz
    if total > MAX_PACK_BYTES:
        raise PackError(f'pack is over {MAX_PACK_BYTES // (1024 * 1024)} MB')
    return total


def validate(d) -> dict:
    """Validate an unpacked pack folder -> {'name', 'id', 'display', 'author', 'license', 'sizes', 'bytes', 'manifest'}.
    Raises PackError with one plain reason - for anything malformed too, never another exception."""
    try:
        return _validate(d)
    except PackError:
        raise
    except Exception as e:                                          # a shape nobody anticipated: still a plain refusal
        raise PackError(f'malformed pack ({type(e).__name__})')


def _validate(d) -> dict:
    d = Path(d)
    if not d.is_dir() or d.is_symlink():
        raise PackError('not a folder')
    total = _listing(d)
    m = read_manifest(d)
    check_decoded_budget(d)
    if not (d / '64').is_dir():
        raise PackError('64/ is required (the 128/ set is optional)')
    sizes = []
    metas = {}
    for s in SIZES:
        if (d / s).is_dir():
            metas[s] = validate_size(d / s, s)
            sizes.append(int(s))
    if '128' in metas and set(metas['128']['anims']) != set(metas['64']['anims']):
        raise PackError('64/ and 128/ must have the same moves')
    if (d / 'preview.png').is_file():
        _png(d / 'preview.png', 0)                                 # its header was capped by check_decoded_budget
    return dict(name=m['name'], id=char_id(m['name']), display=m['display'].strip(), author=m['author'].strip(),
                license=m['license'].strip(), version=str(m.get('version') or ''), sizes=sizes, bytes=total, manifest=m)


# ---------------------------------------------------------------- installed packs (cached by file signature)
_cache = {}


def _sig(d):
    try:
        return tuple(sorted((p.relative_to(d).as_posix(), p.stat().st_mtime_ns, p.stat().st_size) for p in Path(d).rglob('*')))
    except OSError:
        return None


def installed(root=None) -> list:
    """-> [{'name', 'id', 'display', ..., 'ok': bool, 'error': str|None, 'path'}] for every folder in packs/."""
    base = Path(root) if root else packs_dir()
    out = []
    try:
        dirs = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.'))
    except OSError:
        return out
    for d in dirs:
        sig = _sig(d)
        hit = _cache.get(str(d))
        if hit and hit[0] == sig:
            out.append(hit[1])
            continue
        try:
            info = validate(d)
            if info['name'] != d.name:
                raise PackError(f'folder name {d.name!r} differs from pack.json name {info["name"]!r}')
            info.update(ok=True, error=None, path=str(d))
        except PackError as e:
            info = dict(name=d.name, id=char_id(d.name), display=d.name, ok=False, error=str(e), path=str(d), sizes=[])
        _cache[str(d)] = (sig, info)
        out.append(info)
    return out


def characters(root=None) -> list:
    """[{'id': 'pack-<name>', 'display'}] for every VALID installed pack (lineup.characters adds these)."""
    return [{'id': p['id'], 'display': p['display']} for p in installed(root) if p['ok']]


def character_ids(root=None) -> list:
    return [c['id'] for c in characters(root)]


def char_dir(cid, hd=False, root=None):
    """The atlas folder for a pack character: <pack>/128 when hd and present, else <pack>/64.  None if not a valid pack."""
    if not is_pack_id(cid):
        return None
    name = cid[len(PREFIX):]
    info = next((p for p in installed(root) if p['name'] == name and p['ok']), None)
    if info is None:
        return None
    d = Path(info['path'])
    return d / '128' if hd and 128 in info['sizes'] else d / '64'


# ---------------------------------------------------------------- install / remove
def _safe_member(name):
    """A zip entry name -> its relative parts, or PackError."""
    if not name or '\\' in name or name.startswith('/') or re.match(r'^[A-Za-z]:', name) or '\x00' in name:
        raise PackError(f'zip entry {name[:60]!r}: absolute or odd path')
    parts = [p for p in PurePosixPath(name).parts]
    if any(p in ('..', '.') or p.strip() != p or ':' in p for p in parts):
        raise PackError(f'zip entry {name[:60]!r}: path traversal')
    return parts


def unpack_zip(zp, dest):
    """Extract a pack zip into the empty folder `dest`, entry by entry, after checking every entry.  -> dest/<pack root>."""
    zp, dest = Path(zp), Path(dest)
    if zp.stat().st_size > MAX_PACK_BYTES:
        raise PackError('zip is over the pack size limit')
    try:
        zf = zipfile.ZipFile(zp)
    except (zipfile.BadZipFile, OSError) as e:
        raise PackError(f'not a zip file ({type(e).__name__})')
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES * 2:
            raise PackError('zip has too many entries')
        names, total, files = set(), 0, []
        for zi in infos:
            parts = _safe_member(zi.filename)
            mode = (zi.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise PackError(f'zip entry {zi.filename[:60]!r}: links are not allowed')
            key = '/'.join(parts).lower()
            if key in names:
                raise PackError(f'zip entry {zi.filename[:60]!r} appears twice')
            names.add(key)
            if zi.is_dir():
                continue
            if zi.flag_bits & 0x1:
                raise PackError('encrypted zip entries are not supported')
            total += zi.file_size
            if total > MAX_PACK_BYTES or zi.file_size > MAX_PNG_BYTES:
                raise PackError('zip content is over the pack size limit')
            if zi.compress_size and zi.file_size / zi.compress_size > MAX_RATIO:
                raise PackError(f'zip entry {zi.filename[:60]!r}: suspicious compression ratio')
            files.append((zi, parts))
        tops = {p[0] for _, p in files}
        strip = 1 if len(tops) == 1 and all(len(p) > 1 for _, p in files) else 0     # a zip of the <name>/ folder
        base = dest.resolve()
        for zi, parts in files:
            rel = parts[strip:]
            if not rel:
                continue
            target = (base.joinpath(*rel)).resolve()
            if base not in target.parents:
                raise PackError(f'zip entry {zi.filename[:60]!r}: path traversal')
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(zi) as src, open(target, 'wb') as out:
                left = zi.file_size + 1
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    left -= len(chunk)
                    if left < 0:                                        # the header lied about the size
                        raise PackError(f'zip entry {zi.filename[:60]!r}: bigger than it says')
                    out.write(chunk)
    return dest


def install(src, root=None, replace=False) -> dict:
    """Install a pack from a .zip or a folder -> its validate() info.  Refuses (PackError) anything invalid; an existing
    pack of the same name is replaced only with replace=True."""
    src = Path(src)
    base = Path(root) if root else packs_dir()
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.incoming-', dir=base))
    try:
        stage = tmp / 'pack'
        stage.mkdir()
        if src.is_file() and src.suffix.lower() == '.zip':
            unpack_zip(src, stage)
        elif src.is_dir() and not src.is_symlink():
            _listing(src)                                              # refuse before copying anything odd
            for p in src.rglob('*'):
                rel = p.relative_to(src)
                if p.is_dir():
                    (stage / rel).mkdir(parents=True, exist_ok=True)
                else:
                    (stage / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, stage / rel)
        else:
            raise PackError('give a .zip file or a pack folder')
        info = validate(stage)
        final = base / info['name']
        if final.exists():
            if not replace:
                raise PackError(f"a pack named {info['name']!r} is installed already (packs remove {info['name']}, or --replace)")
            remove(info['name'], base)
        os.replace(stage, final)
        _cache.pop(str(final), None)
        return dict(info, path=str(final))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove(name, root=None) -> bool:
    """Delete packs/<name> - only a direct child of packs/ that holds a pack.json, never anything else."""
    if not NAME_RE.match(str(name or '')):
        raise PackError(f'{name!r} is not a pack name')
    base = (Path(root) if root else packs_dir()).resolve()
    d = (base / name)
    if not d.is_dir() or d.is_symlink() or d.resolve().parent != base or not (d / 'pack.json').is_file():
        return False
    shutil.rmtree(d)
    _cache.pop(str(d), None)
    return True


# ---------------------------------------------------------------- `minis.py packs ...`
def cmd(args, out=print):
    act = getattr(args, 'action', None) or 'list'
    try:
        if act == 'list':
            rows = installed()
            if not rows:
                out(f'no skin packs installed (folder: {packs_dir()})')
                return 0
            for p in rows:
                if p['ok']:
                    out(f"  {p['id']:22s} {p['display']:16s} by {p['author']}, {p['license']}, {'+'.join(str(s) for s in p['sizes'])} px")
                else:
                    out(f"  {p['id']:22s} INVALID: {p['error']}")
            out('use one: python minis.py skin <program> <pack id or display name>')
            return 0
        if act == 'install':
            if not getattr(args, 'path', None):
                out('usage: packs install <pack.zip | folder> [--replace]')
                return 2
            info = install(args.path, replace=bool(getattr(args, 'replace', False)))
            out(f"installed {info['id']} ({info['display']} by {info['author']}, {info['license']})")
            return 0
        if act == 'remove':
            if not getattr(args, 'path', None):
                out('usage: packs remove <name>')
                return 2
            name = args.path[len(PREFIX):] if args.path.startswith(PREFIX) else args.path
            ok = remove(name)
            out(f'removed {name}' if ok else f'no installed pack named {name!r}')
            return 0 if ok else 1
        if act == 'check':
            if not getattr(args, 'path', None):
                out('usage: packs check <folder>')
                return 2
            info = validate(args.path)
            out(f"ok: {info['id']} ({info['display']}), sizes {info['sizes']}, {info['bytes'] // 1024} KB")
            return 0
        if act == 'import-codex':
            out('Codex pet import is not available: the Codex pet pack format is not documented anywhere this app can read '
                'offline, and guessing it could mis-read your files. See docs/SKIN-PACKS.md ("Codex pets").')
            return 2
    except PackError as e:
        out(f'refused: {e}')
        return 1
    except Exception as e:                                          # never a traceback: say what failed and stop
        out(f'refused: {type(e).__name__}: {e}')
        return 1
    out('packs: list | install <zip|folder> [--replace] | remove <name> | check <folder> | import-codex <path>')
    return 2
