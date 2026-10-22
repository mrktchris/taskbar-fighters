"""The UI's own pixel font, generated in code: small text looks the same on Windows, macOS and in a frozen bundle, with no
OS font involved (FreeType's hinting of Segoe UI at 9 px tore words apart, the macOS fallbacks spaced them differently, and a
machine without either fell back to Pillow's default bitmap).

One hand-drawn face, cap height 7, x-height 5, 2-row descenders, proportional widths (1 px between letters, 3 px spaces).
From it:
  regular           the face as drawn                                            sizes <= 10 (8-10 px of OS text)
  bold              every row OR-ed with itself shifted 1 px right (2 px stems)   bold at 9-10 px; never below 9 (too wide)
  tall / tall bold  one middle row of each glyph doubled (cap 8, x-height 6)      11-12 px: titles and names
Ink rows start DY (2) px below the pen y, where the OS fonts' cap tops used to be, so every layout keeps its place.
Glyphs are ASCII 32-126 plus the middle dot; a few typographic characters map onto them, anything else draws as '?'.
Only minis_core.render.text draws it (d.bitmap of an 'L' mask), and PIL's ImageDraw.textlength measures it through
getlength, so every caller that measured with an OS font measures the pixel font the same way.
"""
from __future__ import annotations
from PIL import Image

CAP, XH, DESC = 7, 5, 2
ROWS = CAP + DESC
DY = 2                                   # blank rows above the cap line in a mask (an OS font's internal leading)
SPACING = 1
NO_EMBOLDEN = frozenset('m')             # three 1 px stems with 1 px counters: emboldened it is a block, so bold m is the regular m
FALLBACK = {'…': '...', '—': '-', '–': '-', '‘': "'", '’': "'", '“': '"', '”': '"',
            '×': 'x', '−': '-', ' ': ' ', '•': '·', '·': '·'}

# The face.  Each block: the character (sp = space, dot = middle dot), an optional top-row offset (lowercase: 2 = the
# x-height line), then the rows, '#' = ink.  A block ends at a blank line.
FACE = r"""
sp
..

!
#
#
#
#
#
.
#

"
#.#
#.#

#
.#.#.
.#.#.
#####
.#.#.
#####
.#.#.
.#.#.

$
..#..
.####
#.#..
.###.
..#.#
####.
..#..

%
#.#
..#
.#.
.#.
.#.
#..
#.#

&
.##..
#..#.
#..#.
.##..
#.#.#
#..#.
.##.#

'
#
#

( 0
.#
#.
#.
#.
#.
#.
.#

) 0
#.
.#
.#
.#
.#
.#
#.

* 1
..#..
#.#.#
.###.
#.#.#
..#..

+ 1
..#..
..#..
#####
..#..
..#..

, 6
.#
#.

- 3
###

. 6
#

/
..#
..#
.#.
.#.
.#.
#..
#..

0
.##.
#..#
#..#
#..#
#..#
#..#
.##.

1
.#.
##.
.#.
.#.
.#.
.#.
###

2
.##.
#..#
...#
..#.
.#..
#...
####

3
###.
...#
...#
.##.
...#
...#
###.

4
..#.
.##.
#.#.
#..#
####
...#
...#

5
####
#...
###.
...#
...#
#..#
.##.

6
.##.
#...
#...
###.
#..#
#..#
.##.

7
####
...#
..#.
..#.
.#..
.#..
.#..

8
.##.
#..#
#..#
.##.
#..#
#..#
.##.

9
.##.
#..#
#..#
.###
...#
...#
.##.

: 2
#
.
.
.
#

; 2
.#
..
..
..
.#
#.

< 1
..#
.#.
#..
.#.
..#

= 2
####
....
####

> 1
#..
.#.
..#
.#.
#..

?
.###.
#...#
....#
...#.
..#..
.....
..#..

@
.###.
#...#
#.###
#.#.#
#.###
#....
.###.

A
.###.
#...#
#...#
#####
#...#
#...#
#...#

B
####.
#...#
#...#
####.
#...#
#...#
####.

C
.###.
#...#
#....
#....
#....
#...#
.###.

D
####.
#...#
#...#
#...#
#...#
#...#
####.

E
#####
#....
#....
####.
#....
#....
#####

F
#####
#....
#....
####.
#....
#....
#....

G
.###.
#...#
#....
#.###
#...#
#...#
.####

H
#...#
#...#
#...#
#####
#...#
#...#
#...#

I
###
.#.
.#.
.#.
.#.
.#.
###

J
.###
...#
...#
...#
...#
#..#
.##.

K
#...#
#..#.
#.#..
##...
#.#..
#..#.
#...#

L
#...
#...
#...
#...
#...
#...
####

M
#...#
##.##
#.#.#
#.#.#
#...#
#...#
#...#

N
#...#
##..#
##..#
#.#.#
#..##
#..##
#...#

O
.###.
#...#
#...#
#...#
#...#
#...#
.###.

P
####.
#...#
#...#
####.
#....
#....
#....

Q
.###.
#...#
#...#
#...#
#.#.#
#..#.
.##.#

R
####.
#...#
#...#
####.
#.#..
#..#.
#...#

S
.####
#....
#....
.###.
....#
....#
####.

T
#####
..#..
..#..
..#..
..#..
..#..
..#..

U
#...#
#...#
#...#
#...#
#...#
#...#
.###.

V
#...#
#...#
#...#
#...#
#...#
.#.#.
..#..

W
#...#
#...#
#...#
#.#.#
#.#.#
##.##
#...#

X
#...#
#...#
.#.#.
..#..
.#.#.
#...#
#...#

Y
#...#
#...#
.#.#.
..#..
..#..
..#..
..#..

Z
#####
....#
...#.
..#..
.#...
#....
#####

[
##
#.
#.
#.
#.
#.
##

\
#..
#..
.#.
.#.
.#.
..#
..#

]
##
.#
.#
.#
.#
.#
##

^
.#.
#.#

_ 7
####

`
#.
.#

a 2
.##.
...#
.###
#..#
.###

b
#...
#...
###.
#..#
#..#
#..#
###.

c 2
.##.
#..#
#...
#..#
.##.

d
...#
...#
.###
#..#
#..#
#..#
.###

e 2
.##.
#..#
####
#...
.###

f
.##
#..
###
#..
#..
#..
#..

g 2
.###
#..#
#..#
#..#
.###
...#
.##.

h
#...
#...
###.
#..#
#..#
#..#
#..#

i
#
.
#
#
#
#
#

j
.#
..
.#
.#
.#
.#
.#
.#
#.

k
#...
#...
#..#
#.#.
##..
#.#.
#..#

l
#
#
#
#
#
#
#

m 2
#####
#.#.#
#.#.#
#.#.#
#.#.#

n 2
###.
#..#
#..#
#..#
#..#

o 2
.##.
#..#
#..#
#..#
.##.

p 2
###.
#..#
#..#
#..#
###.
#...
#...

q 2
.###
#..#
#..#
#..#
.###
...#
...#

r 2
#.#
##.
#..
#..
#..

s 2
.###
#...
.##.
...#
###.

t 1
.#.
###
.#.
.#.
.#.
.##

u 2
#..#
#..#
#..#
#..#
.###

v 2
#...#
#...#
#...#
.#.#.
..#..

w 2
#...#
#...#
#.#.#
#.#.#
.#.#.

x 2
#...#
.#.#.
..#..
.#.#.
#...#

y 2
#..#
#..#
#..#
#..#
.###
...#
.##.

z 2
####
...#
.##.
#...
####

{
.##
.#.
.#.
#..
.#.
.#.
.##

|
#
#
#
#
#
#
#

}
##.
.#.
.#.
..#
.#.
.#.
##.

~ 3
.#..#
#..#.

dot 4
#
"""


def _parse(src):
    glyphs = {}
    for block in src.strip().split('\n\n'):
        lines = block.split('\n')
        head = lines[0].split(' ')
        ch = {'sp': ' ', 'dot': '·'}.get(head[0], head[0])
        top = int(head[1]) if len(head) > 1 else 0
        rows = lines[1:]
        w = max(len(r) for r in rows)
        bits = [[c == '#' for c in r.ljust(w, '.')] for r in rows]
        glyphs[ch] = (top, w, bits)
    return glyphs


GLYPHS = _parse(FACE)


def _embolden(w, bits):
    out = []
    for r in bits:
        row = [False] * (w + 1)
        for x, on in enumerate(r):
            if on:
                row[x] = row[x + 1] = True
        out.append(row)
    return w + 1, out


def _tall(top, bits):
    """Double one middle row: the one with the least ink (a stem, not a crossbar), nearest the middle on a tie."""
    n = len(bits)
    if n < 3:
        return top, bits
    lo, hi = 1, n - 2                                  # rows 1..n-2 of the glyph's own rows
    mid = (n - 1) / 2.0
    best = min(range(lo, hi + 1), key=lambda i: (sum(bits[i]), abs(i - mid)))
    return top, bits[:best + 1] + [list(bits[best])] + bits[best + 1:]


def normalize(text):
    out = []
    for ch in str(text):
        if ch in GLYPHS:
            out.append(ch)
        elif ch in FALLBACK:
            out.append(FALLBACK[ch])
        elif ch in '\t\n\r':
            out.append(' ')
        else:
            out.append('?')
    return ''.join(out)


class PixelFont:
    """One variant of the face.  Measures like a PIL font (getlength / getbbox, so ImageDraw.textlength works) and renders
    through mask(); never handed to ImageDraw.text."""

    _glyph_cache = {}
    _mask_cache = {}

    def __init__(self, bold=False, tall=False, size=9):
        self.bold, self.tall, self.size = bool(bold), bool(tall), int(size)
        self.rows = ROWS + (1 if tall else 0)
        self.height = DY + self.rows

    # ------------------------------------------------------------ glyphs
    def glyph(self, ch):
        """-> (advance, top row, width, rows of bools) for one character of the normalized text."""
        key = (ch, self.bold, self.tall)
        g = self._glyph_cache.get(key)
        if g is None:
            top, w, bits = GLYPHS.get(ch) or GLYPHS['?']
            bits = [list(r) for r in bits]
            if self.tall:
                top, bits = _tall(top, bits)
                if ch != ' ' and GLYPHS[ch][0] >= CAP:            # a mark below the baseline (, _) moves down with it
                    top += 1
            if self.bold and ch not in NO_EMBOLDEN:
                w, bits = _embolden(w, bits)
            if ch == ' ':
                bits = []
            g = self._glyph_cache[key] = (w + SPACING, top, w, bits)
        return g

    # ------------------------------------------------------------ PIL-like measuring
    def getlength(self, text, *args, **kwargs):
        s = normalize(text)
        if not s:
            return 0.0
        return float(sum(self.glyph(ch)[0] for ch in s) - SPACING)

    def getbbox(self, text, *args, **kwargs):
        return (0, 0, int(self.getlength(text)), self.height)

    @property
    def ascent(self):
        return DY + CAP + (1 if self.tall else 0)

    # ------------------------------------------------------------ rendering
    def mask(self, text, scale=1):
        """An 'L' image, 255 where there is ink, (length x height) at `scale` (whole pixels only)."""
        s = normalize(text)
        key = (s, self.bold, self.tall, int(scale))
        im = self._mask_cache.get(key)
        if im is not None:
            return im
        w = max(1, int(self.getlength(s)))
        im = Image.new('L', (w, self.height), 0)
        px = im.load()
        x = 0
        for ch in s:
            adv, top, gw, bits = self.glyph(ch)
            for ry, row in enumerate(bits):
                y = DY + top + ry
                if 0 <= y < self.height:
                    for rx, on in enumerate(row):
                        if on and x + rx < w:
                            px[x + rx, y] = 255
            x += adv
        if scale > 1:
            im = im.resize((im.width * int(scale), im.height * int(scale)), Image.NEAREST)
        if len(self._mask_cache) > 4096:
            self._mask_cache.clear()
        self._mask_cache[key] = im
        return im


_fonts = {}


def for_size(size, bold=True):
    """The variant that stands in for `size` px of OS text: <= 8 regular (bold would not fit the small tiles), 9-10 the
    face (bold emboldened), 11 and up tall."""
    size = int(size)
    bold = bool(bold) and size >= 9
    tall = size >= 11
    key = (bold, tall, size)
    f = _fonts.get(key)
    if f is None:
        f = _fonts[key] = PixelFont(bold=bold, tall=tall, size=size)
    return f


def specimen(scale=1):
    """A sheet of every variant (tools/ux_previews.py 'font')."""
    from PIL import ImageDraw
    lines = []
    for label, f in (('regular', for_size(9, False)), ('bold', for_size(9, True)), ('tall', for_size(11, False)),
                     ('tall bold', for_size(11, True))):
        lines += [(f, label + ':  The quick brown fox jumps over the lazy dog  0123456789'),
                  (f, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz'),
                  (f, '!"#$%&\'()*+,-./ :;<=>?@ [\\]^_`{|}~ ·  ctx 48% · wk 12% · 2d 4h  waiting? 1 min 37 s')]
    w = max(int(f.getlength(s)) for f, s in lines) + 16
    h = sum(f.height + 3 for f, _ in lines) + 12
    im = Image.new('RGBA', (w, h), (18, 18, 22, 255))
    d = ImageDraw.Draw(im)
    y = 6
    for f, s in lines:
        d.bitmap((8, y), f.mask(s), fill=(230, 230, 240, 255))
        y += f.height + 3
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    return im
