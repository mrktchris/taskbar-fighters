"""Build the optional sound effects: python art/build_sfx.py [--out assets/sfx]

Every sound is original and synthesized here from math with the Python standard library (wave, math, struct, random with a
fixed seed): no recordings, no third-party audio, no samples.  The output is deterministic, so a rebuild on the same
platform reproduces the committed .wav files byte for byte (tests/test_sfx.py checks it).

22050 Hz, mono, 16-bit, short (40-950 ms) and quiet (peak about -12 dBFS): the taskbar is a place people work.

  hit_light   a short, dry knock: a pitch-dropping thump under a burst of filtered noise
  hit_heavy   the same, lower and longer, with a second body thump
  clash       two blades meeting: inharmonic metal partials ringing out over a click
  whoosh      a swing: noise swept through a resonant band that rises and falls
  ko          the deciding blow: a heavy thump, then a falling tone that rings away
  forge       desktop weapons: crackling sparks over a low electric hum
  shatter     glass: a crack, then a spray of tiny high pings
  bell        round bell: bell partials (1, 2.76, 5.40, 8.93 x the strike tone) decaying slowly
"""
from __future__ import annotations
import argparse, math, os, random, struct, wave

RATE = 22050
PEAK = 0.25                       # about -12 dBFS
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'assets', 'sfx')
TAU = 2.0 * math.pi


def n_of(sec):
    return int(round(sec * RATE))


def env_exp(i, n, k):
    return math.exp(-k * i / float(n))


class Noise:
    """Seeded white noise with a one-pole low pass and a high pass, so a band can be swept without numpy."""

    def __init__(self, seed):
        self.r = random.Random(seed)
        self.lp = 0.0
        self.hp_prev = 0.0
        self.hp = 0.0

    def white(self):
        return self.r.uniform(-1.0, 1.0)

    def band(self, lo_hz, hi_hz):
        x = self.white()
        a = 1.0 - math.exp(-TAU * hi_hz / RATE)                       # low pass at hi_hz
        self.lp += a * (x - self.lp)
        c = math.exp(-TAU * lo_hz / RATE)                             # high pass at lo_hz
        self.hp = c * (self.hp + self.lp - self.hp_prev)
        self.hp_prev = self.lp
        return self.hp


def thump(n, f0, f1, k, seed=0):
    """A body hit: a sine falling in pitch from f0 to f1, decaying with rate k."""
    out, ph = [], 0.0
    for i in range(n):
        u = i / float(n)
        f = f1 + (f0 - f1) * math.exp(-6.0 * u)
        ph += TAU * f / RATE
        out.append(math.sin(ph) * env_exp(i, n, k))
    return out


def mix(*tracks, gains=None):
    n = max(len(t) for t in tracks)
    gains = gains or [1.0] * len(tracks)
    out = [0.0] * n
    for t, g in zip(tracks, gains):
        for i, v in enumerate(t):
            out[i] += v * g
    return out


def pad(t, n):
    return t + [0.0] * max(0, n - len(t))


def delay(t, sec, gain):
    d = n_of(sec)
    return [0.0] * d + [v * gain for v in t]


def fade(t, ms=6):
    m = min(len(t), n_of(ms / 1000.0))
    t = list(t)
    for i in range(m):
        t[i] *= i / float(m)
        t[-1 - i] *= i / float(m)
    return t


def normalize(t, peak=PEAK):
    p = max(1e-9, max(abs(v) for v in t))
    return [v * peak / p for v in t]


# ---------------------------------------------------------------- the sounds
def hit_light():
    n = n_of(0.09)
    nz = Noise(11)
    body = thump(n, 220, 90, 9.0)
    crack = [nz.band(900, 4200) * env_exp(i, n, 30.0) for i in range(n)]
    return mix(body, crack, gains=[0.9, 0.7])


def hit_heavy():
    n = n_of(0.22)
    nz = Noise(12)
    body = thump(n, 150, 48, 6.0)
    body2 = delay(thump(n_of(0.12), 120, 55, 7.0), 0.035, 0.6)
    crack = [nz.band(500, 3000) * env_exp(i, n, 18.0) for i in range(n)]
    return mix(body, body2, crack, gains=[1.0, 0.8, 0.6])


def clash():
    n = n_of(0.42)
    nz = Noise(13)
    parts = ((1240, 1.0, 9.0), (1873, 0.7, 11.0), (2651, 0.55, 13.0), (3417, 0.4, 16.0), (4730, 0.25, 22.0))
    ring = [sum(a * math.sin(TAU * f * i / RATE + f) * env_exp(i, n, k) for f, a, k in parts) for i in range(n)]
    click = [nz.band(2000, 9000) * env_exp(i, n, 60.0) for i in range(n)]
    return mix(ring, click, gains=[0.6, 1.0])


def whoosh():
    n = n_of(0.2)
    nz = Noise(14)
    out = []
    for i in range(n):
        u = i / float(n)
        e = math.sin(math.pi * u) ** 1.6
        hi = 900 + 2600 * math.sin(math.pi * u)
        out.append(nz.band(hi * 0.35, hi) * e)
    return out


def ko():
    n = n_of(0.95)
    nz = Noise(15)
    hit = pad(hit_heavy(), n)
    tone, ph = [], 0.0
    for i in range(n):
        u = i / float(n)
        f = 330 * (1.0 - 0.55 * u)
        ph += TAU * f / RATE
        tone.append((math.sin(ph) + 0.35 * math.sin(2.0 * ph)) * env_exp(i, n, 4.0) * min(1.0, i / n_of(0.06)))
    air = [nz.band(200, 1200) * env_exp(i, n, 8.0) for i in range(n)]
    return mix(hit, tone, air, gains=[1.0, 0.45, 0.25])


def forge():
    n = n_of(0.55)
    nz = Noise(16)
    r = random.Random(16)
    hum = [(math.sin(TAU * 110 * i / RATE) + 0.5 * math.sin(TAU * 220 * i / RATE)) * 0.25 * math.sin(math.pi * i / n) for i in range(n)]
    crack = [0.0] * n
    for _ in range(26):
        at = r.randrange(0, n - n_of(0.02))
        ln = n_of(r.uniform(0.003, 0.012))
        g = r.uniform(0.4, 1.0)
        for j in range(ln):
            crack[at + j] += nz.band(1500, 7000) * g * (1.0 - j / float(ln))
    return mix(hum, crack, gains=[0.7, 1.0])


def shatter():
    n = n_of(0.5)
    nz = Noise(17)
    r = random.Random(17)
    crack = [nz.band(1200, 8000) * env_exp(i, n, 25.0) for i in range(n)]
    pings = [0.0] * n
    for _ in range(22):
        at = r.randrange(n_of(0.02), n - n_of(0.08))
        f = r.uniform(2800, 6200)
        ln = n_of(r.uniform(0.03, 0.08))
        g = r.uniform(0.25, 0.7)
        for j in range(ln):
            pings[at + j] += math.sin(TAU * f * j / RATE) * g * env_exp(j, ln, 5.0)
    return mix(crack, pings, gains=[0.8, 0.6])


def bell():
    n = n_of(0.9)
    f0 = 740.0
    parts = ((1.0, 1.0, 4.0), (2.76, 0.55, 6.0), (5.40, 0.3, 9.0), (8.93, 0.18, 13.0))
    return [sum(a * math.sin(TAU * f0 * m * i / RATE) * env_exp(i, n, k) for m, a, k in parts) * min(1.0, i / 40.0) for i in range(n)]


SOUNDS = {'hit_light': hit_light, 'hit_heavy': hit_heavy, 'clash': clash, 'whoosh': whoosh, 'ko': ko, 'forge': forge,
          'shatter': shatter, 'bell': bell}


def render(name):
    return normalize(fade(SOUNDS[name]()))


def write_wav(path, samples):
    data = b''.join(struct.pack('<h', max(-32767, min(32767, int(round(v * 32767))))) for v in samples)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.setcomptype('NONE', 'not compressed')
        w.writeframes(data)


def build(out=OUT):
    os.makedirs(out, exist_ok=True)
    paths = []
    for name in SOUNDS:
        p = os.path.join(out, f'{name}.wav')
        write_wav(p, render(name))
        paths.append(p)
    return paths


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()
    for p in build(a.out):
        print(p, os.path.getsize(p), 'bytes')
