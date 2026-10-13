"""The station promos' build side (ident/promos): every promo is 5 or 10 seconds, its voice
lines start inside it, the hits its picture and music share (beats.py, and the constants
music.py reads from each picture's source) hold together, the sports idents name real
leagues, and each picture draws a frame."""
import ast
import importlib
import json
import sys
import unittest
from pathlib import Path

PROMOS_DIR = Path(__file__).resolve().parent.parent / 'ident' / 'promos'
sys.path.insert(0, str(PROMOS_DIR))
sys.path.insert(1, str(PROMOS_DIR.parent))

import cairo  # noqa: E402

import beats  # noqa: E402
import common  # noqa: E402


def built_promos():
    """build.py's PROMOS, read without importing it (it would shadow ident/build.py)."""
    tree = ast.parse((PROMOS_DIR / 'build.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'PROMOS' for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('build.py has no PROMOS')


def picture(promo_id):
    return importlib.import_module(promo_id.replace('-', '_'))


NEW = ('watching', 'metro', 'dupont', 'meridian-hill', 'now-in-hd', 'cat-remote', 'cat-laser', 'seventy-six',
       'eighty-six', 'ninety-six', 'twenty-sixteen', 'the-cairo', 'cairo-1894', 'baseball', 'football')


def literal_constants(promo_id):
    """What music.hits() can read from a picture: its top-level constants that are literals."""
    tree = ast.parse((PROMOS_DIR / f"{promo_id.replace('-', '_')}.py").read_text())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name):
                found[target.id] = value
            elif isinstance(target, ast.Tuple):
                found.update({e.id: v for e, v in zip(target.elts, value)})
    return found


def music_hit_reads():
    """{promo id: the P.<NAME>s its cue in music.py reads}, for cues that call hits()."""
    tree = ast.parse((PROMOS_DIR / 'music.py').read_text())
    reads = {}
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        promo_id = None
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and getattr(node.value.func, 'id', None) == 'hits'):
                promo_id = node.value.args[0].value
        if promo_id:
            reads[promo_id] = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)
                               and isinstance(n.value, ast.Name) and n.value.id == 'P'}
    return reads


class PromoShapeTests(unittest.TestCase):
    def test_every_promo_is_five_or_ten_seconds(self):
        for promo_id in built_promos():
            with self.subTest(promo_id):
                module = picture(promo_id)
                self.assertEqual(module.ID, promo_id)
                self.assertIn(module.DURATION, (5.0, 10.0))
                self.assertLess(module.STILL_AT, module.DURATION)

    def test_voice_lines_start_inside_their_promo(self):
        script = json.loads((PROMOS_DIR / 'script.json').read_text())
        promos = set(built_promos())
        for promo_id, entry in script.items():
            with self.subTest(promo_id):
                self.assertIn(promo_id, promos)
                for line in entry['lines']:
                    self.assertTrue(line['id'].startswith('promo-'))
                    self.assertLess(line['at'], picture(promo_id).DURATION - 1.0)

    def test_new_pictures_draw_a_frame(self):
        for promo_id in NEW:
            module = picture(promo_id)
            for t in (0.5, module.STILL_AT):
                with self.subTest(promo_id, t=t):
                    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, common.W, common.H)
                    module.draw(cairo.Context(surface), t, int(t * common.FPS))
                    surface.flush()
                    self.assertGreater(max(surface.get_data()[::997]), 40)    # not a black frame


    def test_the_music_reads_each_hit_the_picture_uses(self):
        reads = music_hit_reads()
        self.assertTrue({'cat-remote', 'baseball', 'the-cairo', 'cairo-1894'} <= set(reads))
        for promo_id, names in reads.items():
            with self.subTest(promo_id):
                constants, module = literal_constants(promo_id), picture(promo_id)
                self.assertTrue(names <= set(constants), names - set(constants))
                for name in names:
                    self.assertEqual(constants[name], getattr(module, name))

    def test_sports_idents_name_real_leagues_and_the_rest_none(self):
        sys.path.insert(0, str(PROMOS_DIR.parent.parent))
        from roku_stream.sports import LEAGUES
        for promo_id in built_promos():
            with self.subTest(promo_id):
                leagues = getattr(picture(promo_id), 'LEAGUES', ())
                if promo_id in ('baseball', 'football'):
                    self.assertTrue(leagues and set(leagues) <= set(LEAGUES))
                else:
                    self.assertEqual(leagues, ())

    def test_voice_lines_say_vizzle_vision(self):
        """VizelVision is said VIZZLE-VISION; lines voiced since 7 October 2026 spell it so."""
        script = json.loads((PROMOS_DIR / 'script.json').read_text())
        for promo_id in NEW[5:]:
            for line in script.get(promo_id, {'lines': []})['lines']:
                self.assertNotIn('Vizel Vision', line['text'], line['id'])


class BeatsTests(unittest.TestCase):
    def test_drum_circle_hits_are_in_order_inside_the_promo(self):
        hits = beats.meridian_hits()
        times = [h[0] for h in hits]
        self.assertEqual(times, sorted(times))
        self.assertGreaterEqual(times[0], 0)
        self.assertLess(times[-1], picture('meridian-hill').FADE[0])
        self.assertTrue(all(0 <= drum < len(beats.DRUMS) for _, drum, _, _ in hits))

    def test_each_drums_hands_take_turns_and_play_together_on_the_logo(self):
        by_drum = {}
        for at, drum, hand, _ in beats.meridian_hits():
            by_drum.setdefault(drum, []).append((at, hand))
        for drum, hits in by_drum.items():
            single = [hand for _, hand in hits if hand != beats.BOTH]
            self.assertTrue(all(a != b for a, b in zip(single, single[1:])), drum)
            together = {at for at, hand in hits if hand == beats.BOTH}
            for start in (beats.CLAP, beats.CLOSED):
                self.assertTrue({start + b * beats.BEAT for b in beats.LOGO} <= together)

    def test_one_build_hit_for_each_basin(self):
        fills = beats.fill_times()
        self.assertEqual(len(fills), beats.BASINS)
        hits = {round(h[0], 6) for h in beats.meridian_hits()}
        self.assertTrue({round(f, 6) for f in fills} <= hits)

    def test_train_stops_with_its_middle_door_centred_and_leaves_the_frame(self):
        stopped = beats.train_x(beats.TRAIN_ARRIVE[1])
        self.assertAlmostEqual(stopped + beats.CAR + beats.GAP + beats.DOORS[1], beats.FRAME_W / 2)
        end = beats.train_x(beats.TRAIN_DEPART[1] - 1e-6)
        self.assertLess(end + 2 * beats.CAR + beats.GAP, 0)
        self.assertIsNone(beats.train_x(0.0))
        self.assertIsNone(beats.train_x(beats.TRAIN_DEPART[1]))

    def test_wheels_clack_only_while_the_train_moves(self):
        clacks = beats.clacks()
        self.assertTrue(clacks)
        for at, joint, speed in clacks:
            self.assertIn(joint, beats.JOINTS)
            self.assertGreater(speed, 0)
            self.assertTrue(any(a <= at < b for a, b in (beats.TRAIN_ARRIVE, beats.TRAIN_DEPART)), at)


if __name__ == '__main__':
    unittest.main()
