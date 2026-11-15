from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import tracking
from core import nearby, murmur3
from memory import Game, NotReady


class RadarLocationTests(unittest.TestCase):
    def resolve(self, banc, location, child, areas):
        self.assertTrue(hasattr(tracking, 'radar_area'),
                        'Radar must resolve the live location instead of the entry scene')
        return tracking.radar_area(banc, location, child, areas)

    def test_seamless_lake_skull_is_visible_despite_field_entry_scene(self):
        rows = [dict(kind='skull', id=1, area='LakeHylia_Child',
                     xyz=[-289.1369, 130.9377, 590.8506])]
        area = self.resolve('HyruleField_Child', 'LakeHylia', True,
                            {row['area'] for row in rows})
        found = nearby(rows, area, [-294.9289, 130.9429, 597.0101],
                       SimpleNamespace(ids=set(), values={}))
        self.assertEqual([row['id'] for row in found], [1])
        self.assertAlmostEqual(found[0]['distance'], 8.455, places=2)

    def test_current_age_selects_only_the_matching_lake_catalog(self):
        areas = {'LakeHylia_Child', 'LakeHylia_Adult'}
        self.assertEqual(self.resolve('HyruleField_Child', 'LakeHylia', False, areas),
                         'LakeHylia_Adult')

    def test_current_dungeon_does_not_show_nearby_overworld_markers(self):
        areas = {'LakeHylia_Child', 'WaterTemple'}
        self.assertEqual(self.resolve('HyruleField_Child', 'WaterTemple', True, areas),
                         'WaterTemple')

    def test_current_matching_alternative_scene_is_preserved(self):
        areas = {'KakarikoVillage_Adult', 'KakarikoVillage_Adult_Alternative'}
        self.assertEqual(self.resolve('KakarikoVillage_Adult_Alternative',
                                      'KakarikoVillage', False, areas),
                         'KakarikoVillage_Adult_Alternative')

    def test_unmapped_location_does_not_reuse_stale_entry_scene(self):
        self.assertEqual(self.resolve('HyruleField_Child', 'UnknownInterior', True,
                                      {'HyruleField_Child'}), 'UnknownInterior')

    def test_blank_location_waits_instead_of_showing_stale_markers(self):
        self.assertTrue(hasattr(Game, 'radar_location'))
        game = Mock(spec=Game)
        game.entry.return_value = 0x1000
        game.pointer.return_value = 0x2000
        game.read.return_value = bytes(64)
        with self.assertRaises(NotReady):
            Game.radar_location(game, 0x3000)

    def test_location_reader_validates_the_location_entry_and_current_age(self):
        self.assertTrue(hasattr(Game, 'radar_location'))
        game = Mock(spec=Game)
        game.entry.return_value = 0x1000
        game.pointer.return_value = 0x2000
        game.read.return_value = b'LakeHylia\0'.ljust(64, b'\0')
        game.boolean.return_value = True
        self.assertEqual(Game.radar_location(game, 0x3000), ('LakeHylia', True))
        game.entry.assert_called_once_with(0x3000, 0xF74E0E8E, 16, 0x108, 1)
        game.boolean.assert_called_once_with(0x3000, murmur3('Sequence_IsChildhood'))


if __name__ == '__main__':
    unittest.main()
