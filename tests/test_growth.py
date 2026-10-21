"""Growth: achievements / careers / head-to-head / replay plans, the stats card, skin packs and streamer mode.
Synthetic data in a temp data folder only; no window, no screen, no network."""
import json, os, shutil, stat, sys, tempfile, unittest, zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, Isolated  # noqa: E402
from minis_core import achievements as ACH, records  # noqa: E402

PRIVATE = ('secret-project', 'C:\\', '/Users/', 'prompt', '.py')


def facts(**kw):
    base = dict(ko=False, flawless=0, perfect=False, comeback=False, ult=[], boost=[], pieces=[], moves={}, replay=None)
    base.update(kw)
    return base


class Records(Isolated):
    def test_record_keeps_wl_and_folds_facts_log_totals_h2h(self):
        records.record('claude', 'codex', now=100.0, score=(2, 0), facts=facts(ko=True, flawless=2, perfect=True, ult=['claude'],
                                                                                moves={'claude': {'spin_kick': 3}}))
        records.record('codex', 'claude', now=200.0, score=(2, 1), facts=facts(comeback=True, boost=['codex'], pieces=['blade_lock']))
        records.record('claude', 'codex', now=300.0, score=(2, 1))                       # no facts: the W-L line still lands
        rec = records.read()
        self.assertEqual(rec['programs'], {'claude': {'w': 2, 'l': 1}, 'codex': {'w': 1, 'l': 2}})
        self.assertEqual([e['w'] for e in rec['log']], ['claude', 'codex', 'claude'])
        self.assertEqual(rec['totals']['claude']['ko'], 1)
        self.assertEqual(rec['totals']['claude']['perfects'], 1)
        self.assertEqual(rec['totals']['codex']['comebacks'], 1)
        self.assertEqual(rec['totals']['codex']['boosts'], 1)
        self.assertEqual(rec['totals']['claude']['moves'], {'spin_kick': 3})
        self.assertEqual(rec['h2h'], {'claude|codex': {'claude': 2, 'codex': 1}})
        self.assertEqual(rec['seen'], {'pieces': ['blade_lock']})

    def test_log_is_capped_and_lifetime_numbers_survive_the_cap(self):
        rec = {'programs': {}}
        for i in range(ACH.LOG_MAX + 20):
            ACH.fold(rec, {'winner': 'claude', 'loser': 'codex', 'ts': i}, facts(ko=True))
        self.assertEqual(len(rec['log']), ACH.LOG_MAX)
        self.assertEqual(rec['totals']['claude']['ko'], ACH.LOG_MAX + 20)
        self.assertEqual(rec['h2h']['claude|codex']['claude'], ACH.LOG_MAX + 20)
        self.assertEqual(rec['totals']['claude']['best_streak'], ACH.LOG_MAX)       # the log's streak; lifetime is kept

    def test_only_ids_numbers_and_move_names_are_stored(self):
        records.record('claude', 'codex', now=1.0, score=(2, 0), facts=facts(ult=['claude'], moves={'claude': {'jab': 1}}))
        from minis_core import rounds
        text = rounds.record_path().read_text(encoding='utf-8')
        for bad in PRIVATE:
            self.assertNotIn(bad, text)


class MatchFacts(unittest.TestCase):
    def _match(self, seed):
        from minis_core import rounds, fx as fxmod
        from minis_core.atlas import Library
        lib = Library()
        plan = dict(kind='match', left='a', right='b', pos={'a': 500.0, 'b': 532.0}, t0=1000.0, seed=seed,
                    chars={'a': 'claude', 'b': 'codex'}, mode='decided', scores={'a': 80.0, 'b': 60.0}, id='t', deadline=1003.0,
                    span=120.0, boost=['a'])
        tl, t_end, s = rounds.make_match(plan, {'claude': lib['claude'], 'codex': lib['codex']}, fxmod.default())
        return plan, s, lib

    def test_facts_from_a_real_summary_and_the_replay_rebuilds_the_same_match(self):
        from minis_core import rounds, fx as fxmod
        plan, s, lib = self._match(3)
        f = ACH.match_facts(s, {'a': 'claude', 'b': 'codex'}, plan=plan)
        self.assertIsNotNone(f)
        champ = s['winner']
        self.assertEqual(f['comeback'], s['rounds'][0]['winner'] != champ)
        self.assertEqual(f['flawless'], sum(1 for r in s['rounds'] if r['winner'] == champ and r['hp'][champ] >= 100))
        self.assertEqual(f['replay']['seed'], 3)
        self.assertEqual(set(f['replay']), {'v', 'seed', 'kind', 'left', 'right', 'chars', 'pos', 'span', 'mode', 'scores', 'boost'})
        again = ACH.replay_plan({'replay': f['replay']}, t0=50.0)
        tl2, _, s2 = rounds.make_match(again, {'claude': lib['claude'], 'codex': lib['codex']}, fxmod.default())
        self.assertEqual((s2['winner'], s2['wins']), (s['winner'], s['wins']))
        self.assertEqual([r['hp'] for r in s2['rounds']], [r['hp'] for r in s['rounds']])

    def test_bad_summaries_give_none(self):
        self.assertIsNone(ACH.match_facts(None, {'a': 'x'}))
        self.assertIsNone(ACH.match_facts({'winner': 'z'}, {'a': 'x'}))
        self.assertIsNone(ACH.replay_plan({'replay': {'v': 99}}))

    def test_arena_facts_from_its_own_counters(self):
        f = SimpleNamespace
        arena = f(chars={'a': 'claude', 'b': 'gemini'}, f={'a': f(hp=100, down=False), 'b': f(hp=0, down=True)},
                  used_ult={'a': True, 'b': False}, forge=f(state=lambda: {'forges': 3}))
        got = ACH.arena_facts(arena, 'a')
        self.assertEqual((got['ko'], got['flawless'], got['ult'], got['forges']), (True, 1, ['claude'], 3))


class Badges(Isolated):
    def _rec(self, n=12, **kw):
        for i in range(n):
            records.record('claude' if i % 4 else 'codex', 'codex' if i % 4 else 'claude', now=1000.0 + i, score=(2, 1), facts=facts(**kw))
        return records.read()

    def test_every_badge_is_open_and_none_rewards_usage_hours_or_time_of_day(self):
        self.assertTrue(15 <= len(ACH.ACHIEVEMENTS) <= 25)
        for a in ACH.ACHIEVEMENTS:
            self.assertIn(a.family, ACH.FAMILIES)
            self.assertTrue(a.desc and a.name)
            low = (a.name + ' ' + a.desc).lower()
            for word in ('token', 'hour', 'night', 'context', 'late', 'midnight', 'usage'):
                self.assertNotIn(word, low, a.id)
        self.assertEqual(len(set(ACH.IDS)), len(ACH.IDS))
        self.assertNotIn('history', ACH.stats.__code__.co_names)                      # badges never read usage history

    def test_evaluate_progress_and_first_run_is_silent(self):
        rec = self._rec(12, ko=True)
        met = ACH.evaluate(rec)
        for aid in ('first_blood', 'first_ko', 'regular', 'hat_trick'):
            self.assertIn(aid, met)
        self.assertNotIn('centurion', met)
        self.assertEqual(ACH.progress(rec)['centurion'], (12, 100))
        self.assertEqual(ACH.update(rec), [])                                             # seeded silently on a new machine
        self.assertIn('first_ko', ACH.read()['unlocked'])
        records.record('claude', 'codex', now=5000.0, score=(2, 0), facts=facts(ult=['claude']))
        new = ACH.update(records.read())
        self.assertIn('ultimate', new)
        self.assertIn('clean_sweep', new)
        self.assertEqual(ACH.read()['unlocked']['ultimate']['by'], 'claude')

    def test_toaster_shows_each_new_badge_for_three_seconds(self):
        self._rec(1)
        t = ACH.Toaster(every_s=0.0)
        self.assertIsNone(t.poll(100.0))                                                  # first look: seeded, no toast
        records.record('claude', 'codex', now=10.0, score=(2, 0), facts=facts(ko=True, ult=['claude']))
        names = []
        for now in (101.0, 102.0, 104.5, 107.6, 110.7, 113.8):
            names.append(t.poll(now))
        self.assertIn('First KO', names)
        self.assertEqual(names[0], names[1])                                              # the same toast for 3 s
        self.assertIsNone(names[-1])

    def test_ranks_never_demote_and_head_to_head(self):
        self.assertEqual(ACH.rank_of(0)[0], 'Bronze')
        self.assertEqual(ACH.rank_of(10)[:2], ('Silver', 10))
        self.assertEqual(ACH.rank_of(10_000)[0], 'Legend')
        names = [ACH.rank_of(w)[0] for w in range(0, 200)]
        order = [r[0] for r in ACH.RANKS]
        self.assertEqual(names, sorted(names, key=order.index))                           # wins only grow: ranks only climb
        rec = self._rec(8)
        h = ACH.head_to_head(rec, 'claude', 'codex')
        self.assertEqual(h['wins'], {'claude': 6, 'codex': 2})
        self.assertEqual(h['meetings'], 8)
        car = ACH.careers(rec)
        self.assertEqual((car['claude']['w'], car['claude']['l'], car['claude']['rival']), (6, 2, 'codex'))
        lines = ACH.career_lines(rec)
        self.assertTrue(any('Claude vs Codex 6-2' in ln for ln in lines), lines)

    def test_cli_lists_every_criterion(self):
        out = []
        self._rec(2)
        ACH.cmd(out=out.append)
        text = '\n'.join(out)
        for a in ACH.ACHIEVEMENTS:
            self.assertIn(a.desc, text)
        self.assertIn('none are secret', text)


class Card(Isolated):
    def test_card_renders_1200x675_from_numbers_and_names_only(self):
        from minis_core import stats_card
        for i in range(9):
            records.record('claude' if i % 3 else 'gemini', 'gemini' if i % 3 else 'claude', now=100.0 + i, score=(2, 1),
                           facts=facts(moves={'claude': {'spin_kick': 2}}))
        seen = []

        def label(sid):
            seen.append(sid)
            return {'claude': 'Claude', 'gemini': 'Gemini'}.get(sid, sid)
        im = stats_card.render(records.read(), label=label, now=1_761_000_000.0)
        self.assertEqual(im.size, (1200, 675))
        self.assertTrue(set(seen) <= {'claude', 'gemini'})
        rows = stats_card.rows(records.read(), label=label)
        self.assertEqual(rows[0]['favourite'], 'spin_kick')
        self.assertEqual(rows[0]['rival'], ('Gemini', 6, 3))
        self.assertIn('Your main: CLAUDE', stats_card.identity(rows, records.read()))
        empty = stats_card.render({}, now=1_761_000_000.0)
        self.assertEqual(empty.size, (1200, 675))

    def test_build_writes_where_asked_and_badges_cover_every_icon(self):
        from minis_core import stats_card
        records.record('claude', 'codex', now=1.0, score=(2, 0))
        out = self.data / 'cards' / 'mine.png'
        self.assertEqual(stats_card.build(out), out)
        self.assertTrue(out.is_file())
        for a in ACH.ACHIEVEMENTS:
            self.assertEqual(stats_card.badge(a.id, True, 40).size, (40, 40))
        self.assertFalse(stats_card.share_async(lambda argv: None, lambda *a: list(a)))     # never under tests
        self.assertFalse(stats_card.reveal(out))


# ---------------------------------------------------------------- skin packs
def make_pack(dest, name='robo', src='claude', hd=False, mutate=None):
    """A pack copied from a built-in character (fast: no recolour)."""
    from minis_core import atlas, packs
    d = Path(dest) / name
    for size, root in (('64', atlas.ASSETS),) + ((('128', atlas.ASSETS_HD),) if hd else ()):
        (d / size).mkdir(parents=True)
        meta = json.loads((root / src / 'anim.json').read_text(encoding='utf-8'))
        meta.pop('fx', None)
        for f in list(meta['sheets'].values()) + list((meta.get('sheets_unarmed') or {}).values()) + [meta['projectile']['file']]:
            shutil.copyfile(root / src / f, d / size / f)
        if mutate:
            mutate(meta, d / size)
        (d / size / 'anim.json').write_text(json.dumps(meta), encoding='utf-8')
    (d / 'pack.json').write_text(json.dumps({'format': packs.FORMAT, 'name': name, 'display': 'Robo', 'author': 'Tester',
                                             'license': 'CC0-1.0'}), encoding='utf-8')
    return d


class Packs(Isolated):
    def setUp(self):
        super().setUp()
        from minis_core import packs
        self.P = packs
        packs._cache.clear()
        self.src = Path(tempfile.mkdtemp(prefix='minis-pack-src-'))
        self.addCleanup(shutil.rmtree, self.src, True)

    def test_valid_pack_installs_shows_in_select_and_loads_as_an_atlas(self):
        from minis_core import atlas, lineup
        d = make_pack(self.src)
        info = self.P.validate(d)
        self.assertEqual((info['id'], info['sizes']), ('pack-robo', [64]))
        self.P.install(d)
        self.assertIn({'id': 'pack-robo', 'display': 'Robo'}, lineup.characters())
        self.assertEqual(lineup.resolve_character('robo'), 'pack-robo')
        self.assertEqual(atlas.resolve('pack-robo'), 'pack-robo')
        lib = atlas.Library(hd=True)
        a = lib['pack-robo']
        self.assertEqual((a.res, a.upscaled, a.cell), (2, True, (128, 128)))           # the 64 px set scaled for HD
        self.assertNotIn('pack-robo', atlas.available())                                 # the built-in list is unchanged
        self.assertTrue(self.P.remove('robo'))
        self.P._cache.clear()
        self.assertNotIn('pack-robo', [c['id'] for c in lineup.characters()])

    def test_zip_install_with_a_top_folder_and_hd_set(self):
        d = make_pack(self.src, 'hdbot', hd=True)
        zp = self.src / 'hdbot.zip'
        with zipfile.ZipFile(zp, 'w') as z:
            for p in d.rglob('*'):
                if p.is_file():
                    z.write(p, 'hdbot/' + p.relative_to(d).as_posix())
        info = self.P.install(zp)
        self.assertEqual(info['sizes'], [64, 128])
        with self.assertRaises(self.P.PackError):
            self.P.install(zp)                                                           # already installed
        self.P.install(zp, replace=True)

    def _zip(self, entries, name='bad.zip', link=None):
        zp = self.src / name
        with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
            for n, data in entries:
                z.writestr(n, data)
            if link:
                zi = zipfile.ZipInfo(link)
                zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(zi, '/etc/passwd')
        return zp

    def test_zip_traversal_absolute_paths_links_and_bombs_are_refused(self):
        for entries, link in ((([('../evil.txt', 'x')]), None), ([('/abs/pack.json', 'x')], None), ([('C:/x/pack.json', 'x')], None),
                              ([('a\\..\\b', 'x')], None), ([('pack.json', '{}')], 'robo/64/sheet.png'),
                              ([('pack.json', 'x'), ('PACK.JSON', 'y')], None)):
            with self.assertRaises(self.P.PackError, msg=str(entries)):
                self.P.install(self._zip(entries, link=link))
        bomb = self._zip([('robo/pack.json', 'x' * 3_000_000)], 'bomb.zip')
        with zipfile.ZipFile(bomb) as z:
            self.assertGreater(z.infolist()[0].file_size / z.infolist()[0].compress_size, self.P.MAX_RATIO)
        with self.assertRaises(self.P.PackError):
            self.P.install(bomb)
        self.assertEqual([p.name for p in self.P.packs_dir().iterdir()], [])           # nothing left behind
        self.assertFalse((self.data / 'evil.txt').exists())

    def test_strict_validation(self):
        cases = {
            'extra file': lambda d: (d / 'run.py').write_text('print(1)'),
            'sub folder': lambda d: (d / '64' / 'more').mkdir(),
            'bad name': lambda d: (d / 'pack.json').write_text(json.dumps({'format': 1, 'name': '../x', 'display': 'x', 'author': 'a',
                                                                             'license': 'MIT'})),
            'built-in name': lambda d: (d / 'pack.json').write_text(json.dumps({'format': 1, 'name': 'claude', 'display': 'x',
                                                                                  'author': 'a', 'license': 'MIT'})),
            'no license': lambda d: (d / 'pack.json').write_text(json.dumps({'format': 1, 'name': 'robo', 'display': 'x', 'author': 'a'})),
            'not a png': lambda d: (d / '64' / 'sheet.png').write_bytes(b'GIF89a' + b'0' * 100),
            'wrong size': lambda d: __import__('PIL.Image', fromlist=['Image']).new('RGBA', (64, 64)).save(d / '64' / 'sheet_l.png'),
        }
        for why, breaker in cases.items():
            d = make_pack(self.src / why.replace(' ', '_'))
            breaker(d)
            with self.assertRaises(self.P.PackError, msg=why):
                self.P.validate(d)

    def test_anim_json_rules(self):
        def no_idle(meta, d):
            meta['anims'].pop('jab')

        def fx_key(meta, d):
            meta['fx'] = {'file': 'fx.json'}

        def path_sheet(meta, d):
            meta['sheets']['R'] = '../../evil.png'

        def colours(meta, d):
            from PIL import Image
            im = Image.open(d / 'sheet.png').convert('RGBA')
            for i in range(80):
                im.putpixel((i, 0), (i * 3 % 256, i, 200, 255))
            im.save(d / 'sheet.png')
        for why, m in (('missing move', no_idle), ('fx', fx_key), ('path', path_sheet), ('palette', colours)):
            d = make_pack(self.src / why.replace(' ', '_'), mutate=m)
            with self.assertRaises(self.P.PackError, msg=why):
                self.P.validate(d)

    def test_invalid_installed_folder_is_listed_but_never_offered(self):
        from minis_core import lineup
        d = make_pack(self.P.packs_dir())
        (d / 'notes.exe').write_bytes(b'MZ')
        rows = self.P.installed()
        self.assertFalse(rows[0]['ok'])
        self.assertNotIn('pack-robo', [c['id'] for c in lineup.characters()])
        out = []
        self.P.cmd(SimpleNamespace(action='list', path=None), out=out.append)
        self.assertIn('INVALID', '\n'.join(out))

    def test_remove_only_touches_pack_folders_and_codex_import_is_documented_not_guessed(self):
        (self.P.packs_dir()).mkdir(parents=True, exist_ok=True)
        (self.P.packs_dir() / 'notapack').mkdir()
        self.assertFalse(self.P.remove('notapack'))
        with self.assertRaises(self.P.PackError):
            self.P.remove('../x')
        out = []
        self.assertEqual(self.P.cmd(SimpleNamespace(action='import-codex', path='x'), out=out.append), 2)
        self.assertIn('not documented', out[0])

    def test_example_pack_tool_output_validates(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import make_example_pack as M
        from PIL import Image
        im = Image.open(ROOT / 'assets' / 'claude' / 'proj.png')
        rc = M.recolour(im, 180)
        self.assertEqual(rc.size, im.size)
        self.assertLessEqual(len(rc.getcolors(1 << 16)), len(im.convert('RGBA').getcolors(1 << 16)))


# ---------------------------------------------------------------- streamer mode
class Stream(Isolated):
    def setUp(self):
        super().setUp()
        from minis_core import stream, dump
        self.S, self.D = stream, dump
        dump.reset()

    def _rec(self, folder, role, ms, x=10, y=20, w=8, h=6, png=None, color=(255, 0, 0, 255)):
        from PIL import Image
        folder.mkdir(parents=True, exist_ok=True)
        name = png or f'{role}-{ms}.png'
        if png is None:
            Image.new('RGBA', (w, h), color).save(folder / name)
        (folder / f'{role}-{ms}.json').write_text(json.dumps({'role': role, 'id': 'stream', 'wall': ms / 1000.0, 'x': x, 'y': y,
                                                              'w': w, 'h': h, 'scale': 1, 'density': 1, 'visible': True, 'png': name}))

    def test_feed_writes_its_request_reads_newest_and_cleans_up(self):
        feed = self.S.Feed(wall=lambda: 1000.0)
        rid = feed.ensure_request()
        self.assertEqual(rid, 'stream')
        req = json.loads(self.D.request_path().read_text())
        self.assertEqual((req['id'], req['until']), ('stream', 1000.0 + self.S.REQ_SPAN_S))
        folder = self.D.dump_root() / 'stream'
        self._rec(folder, 'a', 1000)
        self._rec(folder, 'a', 2000, color=(0, 0, 255, 255))
        self._rec(folder, 'b', 1500)
        self._rec(folder, 'b', 2500, png='b-1500.png')                     # a moved window reuses the last image
        recs = feed.records('stream')
        self.assertEqual((recs['a']['wall'], recs['b']['wall']), (2.0, 2.5))
        left = sorted(p.name for p in folder.iterdir())
        self.assertEqual(left, ['a-2000.json', 'a-2000.png', 'b-1500.png', 'b-2500.json'])
        self.assertEqual(feed.image('stream', recs['a']).getpixel((0, 0)), (0, 0, 255, 255))
        feed.release()
        self.assertFalse(self.D.request_path().exists())
        self.assertFalse(folder.exists())

    def test_a_foreign_request_is_read_never_overwritten_or_cleaned(self):
        from minis_core.bus import write_json_atomic
        write_json_atomic(self.D.request_path(), {'id': 'cap1', 'until': 1100.0, 'every_ms': 50})
        feed = self.S.Feed(wall=lambda: 1000.0)
        self.assertEqual(feed.ensure_request(), 'cap1')
        folder = self.D.dump_root() / 'cap1'
        self._rec(folder, 'a', 1000)
        self._rec(folder, 'a', 2000)
        feed.records('cap1')
        self.assertEqual(len(list(folder.iterdir())), 4)                       # own_capture's files are left alone
        feed.release()
        self.assertEqual(json.loads(self.D.request_path().read_text())['id'], 'cap1')

    def test_strip_framing_holds_still_and_fit_scales_by_whole_numbers(self):
        strip = self.S.Strip(roles=('a', 'b'))
        from PIL import Image
        red = Image.new('RGBA', (8, 6), (255, 0, 0, 255))
        recs = {'a': {'role': 'a', 'x': 100, 'y': 50, 'w': 8, 'h': 6, 'visible': True},
                'b': {'role': 'b', 'x': 140, 'y': 50, 'w': 8, 'h': 6, 'visible': True}}
        s1 = strip.compose(recs, lambda r: red)
        recs['a']['x'] = 120                                                    # a fighter walks: the box does not shrink
        s2 = strip.compose(recs, lambda r: red)
        self.assertEqual(s1.size, s2.size)
        frame, k = self.S.fit(s1, s1.width * 3 + 7, s1.height * 3 + 5, (0, 255, 0))
        self.assertEqual(k, 3)
        self.assertEqual(frame.getpixel((0, 0)), (0, 255, 0, 255))              # the key colour around it
        tr, _ = self.S.fit(s1, 200, 100, transparent=True)
        self.assertEqual(tr.getpixel((0, 0))[3], 0)
        self.assertEqual(self.S.fit(None, 50, 20)[1], 0)

    def test_hud_panels_are_made_solid_for_a_chroma_key(self):
        from PIL import Image
        glass = Image.new('RGBA', (4, 4), (18, 18, 22, 120))
        recs = {'scoreboard': {'role': 'scoreboard', 'x': 0, 'y': 0, 'w': 4, 'h': 4, 'visible': True}}
        solid = self.S.Strip(('scoreboard',)).compose(recs, lambda r: glass)
        self.assertEqual(solid.getpixel((self.S.MARGIN, self.S.MARGIN))[3], 255)
        kept = self.S.Strip(('scoreboard',), opaque_hud=False).compose(recs, lambda r: glass)
        self.assertEqual(kept.getpixel((self.S.MARGIN, self.S.MARGIN))[3], 120)

    def test_colours_and_the_cli_under_tests(self):
        self.assertEqual(self.S.parse_color('#00ff00'), (0, 255, 0))
        self.assertEqual(self.S.parse_color('magenta'), (255, 0, 255))
        self.assertEqual(self.S.parse_color('1,2,3'), (1, 2, 3))
        with self.assertRaises(ValueError):
            self.S.parse_color('nope')
        out = []
        a = SimpleNamespace(action='on', chroma=None, scale=None, fps=None, width=None, height=None, transparent=False, no_plates=False)
        with mock.patch.dict(os.environ, {'MINIS_TESTING': '1'}):
            self.assertEqual(self.S.cmd(a, spawn=lambda argv: self.fail('spawned'), self_argv=lambda *t: list(t), out=out.append), 1)
        self.assertIn('refused under tests', out[0])
        self.assertEqual(self.S.cmd(SimpleNamespace(action='status'), out=out.append), 0)
        self.assertEqual(out[-1], 'stream: off')

    def test_run_loop_with_a_fake_window_stops_on_request_and_releases(self):
        frames = []

        class FakeWin:
            def __init__(self, title, w, h, transparent=False, bg=None):
                self.closed, self.title = False, title

            def pump(self):
                return True

            def client_size(self):
                return 320, 120

            def present(self, img):
                frames.append(img.size)

            def wait(self, s):
                pass

            def close(self):
                self.closed = True
        folder = self.D.dump_root() / 'stream'
        self._rec(folder, 'a', 1)
        rc = self.S.run({'fps': 30}, window_mod=SimpleNamespace(StreamWindow=FakeWin), max_frames=3)
        self.assertEqual(rc, 0)
        self.assertEqual(frames, [(320, 120)] * 3)
        st = self.S.read_state()
        self.assertFalse(st['active'])
        self.assertFalse(self.D.request_path().exists())
        self.assertEqual(self.S.TITLE, 'Taskbar Fighters — Stream')
        self.S.request_stop(now=1e12)
        self.assertTrue(self.S.stop_requested(1.0))

    def test_option_argv_round_trips_through_the_cli_parser(self):
        import minis
        o = {'chroma': (255, 0, 255), 'scale': 3, 'fps': 20.0, 'transparent': True, 'no_plates': True}
        argv = ['stream', 'run'] + self.S.option_argv(o)
        ns = {}
        with mock.patch.object(self.S, 'run', lambda opts: ns.update(opts) or 0):
            self.assertEqual(minis.main(argv), 0)
        self.assertEqual((ns['chroma'], ns['scale'], ns['transparent'], ns['no_plates']), ((255, 0, 255), 3, True, True))


class Scoreboard(unittest.TestCase):
    def test_toast_takes_row_two_and_yields_to_hp_bars(self):
        from minis_core import scoreboard as SB
        assign = {'a': {'source': 'claude'}, 'b': {'source': 'codex'}}
        st = SB.Model.state(assign, {}, {}, False, False, 'decided', now=1.0, toast='First KO')
        self.assertEqual(st['toast'], 'First KO')
        self.assertNotEqual(SB.render(st).tobytes(), SB.render(dict(st, toast=None)).tobytes())
        busy = SB.Model.state(assign, {'a': {'hp': 50}}, {}, False, False, 'decided', now=1.0, toast='First KO')
        self.assertIsNone(busy['toast'])
        self.assertEqual(SB.render(st, k=2).size, (SB.W * 2, SB.H * 2))                   # Retina HUD draws it too


class Menus(unittest.TestCase):
    def test_tray_and_fighter_menus_offer_the_card_and_streamer_mode(self):
        from minis_win import tray as T
        from minis_core import lineup as L
        items = T.tray_menu({'stream': True})
        self.assertEqual(L.find_item(items, 'Share my stats card')[0], T.CARD)
        self.assertTrue(L.find_item(items, 'Streamer mode')[2]['checked'])
        f_items, _ = L.fighter_menu('a', {'a': {'source': 'claude'}}, {'a': 'auto', 'b': 'auto', 'skins': {}}, {}, [])
        self.assertEqual(L.find_item(f_items, 'Share my stats card')[0], L.CARD)

    def test_tray_choices_never_spawn_under_tests(self):
        import minis
        from minis_win import tray as T
        with mock.patch.dict(os.environ, {'MINIS_TESTING': '1'}), mock.patch.object(minis, 'spawn_detached', lambda a: self.fail(a)):
            minis.tray_choice(T.CARD, {}, None)
            minis.tray_choice(T.STREAM, {'stream': False}, None)

    def test_new_commands_parse(self):
        import minis
        for argv in (['achievements', '--help'], ['card', '--help'], ['packs', '--help'], ['stream', '--help']):
            with self.assertRaises(SystemExit) as cm, mock.patch('sys.stdout'):
                minis.main(argv)
            self.assertEqual(cm.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
