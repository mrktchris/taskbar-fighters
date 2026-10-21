"""Build a worked example skin pack from one of the built-in characters (docs/SKIN-PACKS.md).

    python tools/make_example_pack.py [--from claude] [--name shadow-ronin] [--display "Shadow Ronin"] [--hue 200]
                                      [--out qa/local/packs] [--no-hd]

Writes <out>/<name>/ (pack.json, 64/ and 128/ with anim.json + sheets, LICENSE.txt) and <out>/<name>.zip, recoloured
by rotating every saturated colour's hue, then runs the pack validator on the result.  The art is this repository's
own (MIT), so the example pack is MIT too.  Install it with `python minis.py packs install <out>/<name>.zip`.
"""
from __future__ import annotations
import argparse, colorsys, json, shutil, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402


def recolour(im, hue_deg, sat_min=0.22):
    """Rotate the hue of every colour saturated above sat_min (skin and greys mostly stay); the palette size is kept."""
    im = im.convert('RGBA')
    cols = im.getcolors(1 << 16) or []
    lut = {}
    for _, c in cols:
        r, g, b, a = c
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if a and s >= sat_min:
            h = (h + hue_deg / 360.0) % 1.0
            v = v * 0.92
        r2, g2, b2 = (int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s, v))
        lut[c] = (r2, g2, b2, a)
    pixels = im.get_flattened_data() if hasattr(im, 'get_flattened_data') else im.getdata()
    data = [lut.get(p, p) for p in pixels]
    out = Image.new('RGBA', im.size)
    out.putdata(data)
    return out


def build_size(src, dst, name, display, hue):
    meta = json.loads((src / 'anim.json').read_text(encoding='utf-8'))
    meta.pop('fx', None)                                  # per-pack effect sheets are not part of the format
    meta.pop('palette', None)
    meta.pop('colors', None)
    meta.update(character=f'pack-{name}', who=f'pack-{name}', display=display, tag=display.lower())
    acc = meta.get('accent')
    if isinstance(acc, str) and len(acc.lstrip('#')) == 6:
        s = acc.lstrip('#')
        px = recolour(Image.new('RGBA', (1, 1), tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) + (255,)), hue).getpixel((0, 0))
        meta['accent'] = '#%02X%02X%02X' % px[:3]
    meta['credits'] = f'Example pack recoloured from the built-in {src.name} fighter (MIT, Taskbar Fighters).'
    dst.mkdir(parents=True, exist_ok=True)
    files = list(meta['sheets'].values()) + list((meta.get('sheets_unarmed') or {}).values())
    if (meta.get('projectile') or {}).get('file'):
        files.append(meta['projectile']['file'])
    for f in files:
        recolour(Image.open(src / f), hue).save(dst / f, optimize=True)
    (dst / 'anim.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='src', default='claude')
    ap.add_argument('--name', default='shadow-ronin')
    ap.add_argument('--display', default='Shadow Ronin')
    ap.add_argument('--hue', type=float, default=200.0)
    ap.add_argument('--out', default=str(ROOT / 'qa' / 'local' / 'packs'))
    ap.add_argument('--no-hd', action='store_true', help='only the 64 px set (the engine scales it 2x)')
    a = ap.parse_args(argv)
    from minis_core import atlas, packs
    out = Path(a.out)
    d = out / a.name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    build_size(atlas.ASSETS / a.src, d / '64', a.name, a.display, a.hue)
    if not a.no_hd and (atlas.ASSETS_HD / a.src / 'anim.json').is_file():
        build_size(atlas.ASSETS_HD / a.src, d / '128', a.name, a.display, a.hue)
    (d / 'pack.json').write_text(json.dumps({'format': packs.FORMAT, 'name': a.name, 'display': a.display,
                                             'author': 'Taskbar Fighters (example)', 'license': 'MIT', 'version': '1.0',
                                             'description': f'The {a.src} fighter recoloured: a worked example of the pack format.'},
                                            indent=1), encoding='utf-8')
    lic = (ROOT / 'LICENSE').read_text(encoding='utf-8') if (ROOT / 'LICENSE').is_file() else 'MIT'
    (d / 'LICENSE.txt').write_text(lic, encoding='utf-8')
    info = packs.validate(d)
    zp = out / f'{a.name}.zip'
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.rglob('*')):
            if p.is_file():
                z.write(p, f'{a.name}/{p.relative_to(d).as_posix()}')
    print(f"{info['id']}: {d} ({info['bytes'] // 1024} KB, sizes {info['sizes']}) and {zp}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
