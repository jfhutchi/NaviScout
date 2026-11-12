import struct
import unittest

import core


def save_bytes():
    fields = [(0xA3DB7114, 72), (0x12345678, 1), (0xA77921D7, 17), (0xE0010A50, 200)]
    b = bytearray(96)
    struct.pack_into('<III', b, 0, 0x01020304, 0x002D80EB, 72)
    for i, (key, value) in enumerate(fields):
        struct.pack_into('<II', b, 40 + 8 * i, key, value)
    struct.pack_into('<QQQ', b, 72, 123, 456, 0)
    return bytes(b)


class CoreTests(unittest.TestCase):
    def test_save_collections_and_named_flags(self):
        s = core.Save(save_bytes())
        self.assertEqual(s.ids, {123, 456})
        self.assertTrue(core.collected({'id': 123, 'kind': 'skull'}, s))
        self.assertFalse(core.collected({'id': 124, 'kind': 'skull'}, s))
        self.assertTrue(core.collected({'id': 1, 'kind': 'heart', 'actor': 456}, s))
        self.assertTrue(core.collected({'id': 2, 'kind': 'heart', 'flag': 0x12345678}, s))

    def test_bad_save_fails_closed(self):
        with self.assertRaises(ValueError):
            core.Save(b'bad')
        b = bytearray(save_bytes())
        struct.pack_into('<I', b, 44, 999999)
        with self.assertRaises(ValueError):
            core.Save(b)

    def test_refill_respects_owned_capacity(self):
        self.assertEqual(core.refill_target('rupees', 17, 200), 200)
        self.assertEqual(core.refill_target('seeds', 2, 50), 50)
        self.assertIsNone(core.refill_target('bombs', 0, 0))
        self.assertIsNone(core.refill_target('arrows', 0, 999))
        self.assertIsNone(core.refill_target('nuts', -1, 20))
        self.assertIsNone(core.refill_target('nuts', 30, 20))

    def test_radar_filters_area_collected_and_vertical_distance(self):
        rows = [
            {'id': 123, 'kind': 'skull', 'area': 'A', 'xyz': [3, 0, 4]},
            {'id': 124, 'kind': 'skull', 'area': 'A', 'xyz': [3, 0, 4]},
            {'id': 125, 'kind': 'heart', 'actor': 789, 'area': 'B', 'xyz': [0, 0, 0]},
            {'id': 126, 'kind': 'heart', 'actor': 790, 'area': 'A', 'xyz': [0, 20, 0]},
        ]
        found = core.nearby(rows, 'A', [0, 0, 0], core.Save(save_bytes()), 10)
        self.assertEqual([x['id'] for x in found], [124])
        self.assertEqual(found[0]['distance'], 5)

    def test_named_hash_matches_murmur3_reference_vector(self):
        self.assertEqual(core.murmur3(''), 0)
        self.assertEqual(core.murmur3('foo'), 0xF6A5C420)

    def test_camera_relative_radar_cardinal_directions(self):
        for forward in [(0, -1), (1, 0), (0, 1), (-1, 0)]:
            with self.subTest(forward=forward):
                fx, fz = forward
                self.assertEqual(core.radar_offset(10 * fx, 10 * fz, forward), (0, -10))
                self.assertEqual(core.radar_offset(-10 * fz, 10 * fx, forward), (10, 0))

    def test_camera_east_places_world_north_to_left(self):
        self.assertEqual(core.radar_offset(0, -10, (1, 0)), (-10, 0))

    def test_camera_radar_preserves_distance(self):
        x, y = core.radar_offset(3, 4, (3, -4))
        self.assertAlmostEqual(x * x + y * y, 25)

    def test_invalid_camera_direction_is_rejected(self):
        for direction in [(0, 0), (float('nan'), 1), (1, float('inf'))]:
            with self.assertRaises(ValueError):
                core.radar_offset(3, 4, direction)

    def test_edge_arrow_tracks_camera_direction(self):
        target = dict(id=1, dx=200, dz=0, distance=200)
        for forward, expected in [((0, -1), (1, 0)), ((1, 0), (0, -1)),
                                   ((0, 1), (-1, 0)), ((-1, 0), (0, 1))]:
            item, x, y = core.radar_edge_target([target], 100, forward)
            self.assertIs(item, target)
            self.assertAlmostEqual(x, expected[0])
            self.assertAlmostEqual(y, expected[1])

    def test_edge_arrow_disappears_at_range_boundary_and_inside(self):
        for dx in (0, 99, 100):
            target = dict(dx=dx, dz=0, distance=dx)
            self.assertIsNone(core.radar_edge_target([target], 100, (0, -1)))
        self.assertIsNone(core.radar_edge_target([], 100, (0, -1)))

    def test_edge_arrow_uses_nearest_collectible_only(self):
        far = dict(id=2, dx=200, dz=0, distance=200)
        near = dict(id=1, dx=0, dz=-150, distance=150)
        item, x, y = core.radar_edge_target([far, near], 100, (0, -1))
        self.assertIs(item, near)
        self.assertEqual((x, y), (0, -1))
        inside = dict(id=3, dx=10, dz=0, distance=10)
        self.assertIsNone(core.radar_edge_target([far, inside], 100, (0, -1)))

    def test_diagonal_edge_arrow_stays_on_circle(self):
        target = dict(dx=300, dz=-400, distance=500)
        _, x, y = core.radar_edge_target([target], 100, (0, -1))
        self.assertAlmostEqual(x, 0.6)
        self.assertAlmostEqual(y, -0.8)
        self.assertAlmostEqual(x * x + y * y, 1)


if __name__ == '__main__':
    unittest.main()
