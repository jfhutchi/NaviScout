import importlib.util
from pathlib import Path
import tempfile
import unittest

from core import murmur3


class AmiiboCatalogTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('amiibo_catalog'))
        import amiibo_catalog
        return amiibo_catalog

    def rules(self):
        return {'AmiiboDropActorSettingSet': [
            {'NumberingID': murmur3('NumberingID_1277'), 'DropActorInfoList':
             {'DropActorInfo': [{'ActorNameShort': 'Obj_Mask_Amiibo0'}]}},
            {'NumberingID': murmur3('NumberingID_1279'), 'DropActorInfoList':
             {'DropActorInfo': [{'ActorNameShort': 'Obj_Mask_Amiibo1'}]}},
            {'AmiiboSetType': murmur3('SeriesID'), 'SeriesIDType': murmur3('AmiiboSeriesID09')},
            *[{'AmiiboSetType': murmur3('CharacterBaseID'),
               'CharacterBaseIDType': murmur3(name)} for name in ('Link', 'Zelda', 'Ganon')]]}

    def test_catalog_has_all_verified_zelda_presets_and_two_upcoming_masks(self):
        api = self.api()
        rows = api.compatible_presets(self.rules())
        self.assertEqual(len(rows), 35)
        self.assertEqual(len({row.tag_id for row in rows}), 35)
        self.assertTrue(any("Mineru" in row.name for row in rows))
        self.assertTrue(any('Sheik' in row.name for row in rows))
        self.assertEqual(sum(row.upcoming for row in rows), 2)
        self.assertEqual({row.reward for row in rows if row.upcoming},
                         {'Retro Link mask', 'Retro Zelda mask'})

    def test_game_rules_filter_out_presets_without_a_matching_rule(self):
        api = self.api()
        rows = api.compatible_presets({'AmiiboDropActorSettingSet': [
            {'AmiiboSetType': murmur3('CharacterBaseID'),
             'CharacterBaseIDType': murmur3('Zelda')}]})
        self.assertTrue(rows)
        self.assertTrue(all(row.tag_id.startswith('0101') for row in rows))
        self.assertEqual(api.compatible_presets({'AmiiboDropActorSettingSet': []}), [])

    def test_virtual_tag_has_valid_reader_structure_and_stable_identity(self):
        api = self.api()
        first, second = api.compatible_presets(self.rules())[:2]
        raw = api.virtual_tag(first)
        self.assertEqual(len(raw), 540)
        self.assertEqual(raw[12:16], bytes.fromhex('f110ffee'))
        self.assertEqual(raw[3], 0x88 ^ raw[0] ^ raw[1] ^ raw[2])
        self.assertEqual(raw[8], raw[4] ^ raw[5] ^ raw[6] ^ raw[7])
        self.assertEqual(raw[0x54:0x5c], bytes.fromhex(first.tag_id))
        self.assertEqual(raw, api.virtual_tag(first))
        self.assertNotEqual(raw[:9], api.virtual_tag(second)[:9])
        self.assertEqual(raw[0xdc:0x1b4], bytes(216))

    def test_virtual_tag_rejects_an_unlisted_identity(self):
        api = self.api()
        with self.assertRaises(ValueError):
            api.virtual_tag(api.AmiiboPreset('Unknown', '0000000000000000'))

    def test_local_cache_uses_one_token_per_preset_and_repairs_changed_content(self):
        api = self.api()
        row = api.compatible_presets(self.rules())[0]
        with tempfile.TemporaryDirectory() as temp:
            path = api.cache_tag(row, Path(temp))
            self.assertEqual(path.parent, Path(temp) / 'amiibo/NaviScout')
            self.assertEqual(path.read_bytes(), api.virtual_tag(row))
            path.write_bytes(b'changed')
            self.assertEqual(api.cache_tag(row, Path(temp)), path)
            self.assertEqual(path.read_bytes(), api.virtual_tag(row))


if __name__ == '__main__':
    unittest.main()
