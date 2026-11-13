import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import collected, murmur3, nearby
from catalog import heart_condition, CATALOG_VERSION
from first_run import configure


class CatalogTests(unittest.TestCase):
    def test_chest_reward_uses_mapped_boolean_instead_of_actor_collection(self):
        actor = 12345678901234567890
        mapping = {murmur3(str(actor)): 100}
        condition = heart_condition(dict(Type=1, ActorHash=actor), mapping)
        self.assertEqual(condition, dict(flag=100))
        item = dict(kind='heart', id=1, area='Area_Child', xyz=[0, 0, 0], **condition)
        save = SimpleNamespace(ids=set(), values={100: 1})
        self.assertTrue(collected(item, save))
        self.assertEqual(nearby([item], item['area'], [0, 0, 0], save), [])
        save.values[100] = 0
        self.assertEqual(len(nearby([item], item['area'], [0, 0, 0], save)), 1)

    def test_loose_and_named_heart_rewards_keep_distinct_completion_conditions(self):
        self.assertEqual(heart_condition(dict(Type=0, ActorHash=42), {}), dict(actor=42))
        self.assertEqual(heart_condition(dict(Type=2, GameDataHashName='Reward'), {}),
                         dict(flag=murmur3('Reward')))
        with self.assertRaises(ValueError):
            heart_condition(dict(Type=1, ActorHash=42), {})
        with self.assertRaises(ValueError):
            heart_condition(dict(Type=3, ActorHash=42), {})

    def test_existing_connection_regenerates_old_catalog_without_touching_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            (data / 'config.json').write_text(json.dumps(dict(game_dir='game')))
            path = data / 'catalog.local.json'
            path.write_text(json.dumps(dict(game_build='E0F3CCFAF50065AE', items=[])))
            with patch('first_run.validate_game', return_value=Path('game')), \
                 patch('first_run.save_catalog') as regenerate, patch('first_run.backup_profile') as backup:
                self.assertEqual(configure(data), Path('game'))
                regenerate.assert_called_once_with(Path('game'), path)
                backup.assert_not_called()
            path.write_text(json.dumps(dict(game_build='E0F3CCFAF50065AE', catalog_version=CATALOG_VERSION)))
            with patch('first_run.validate_game', return_value=Path('game')), patch('first_run.save_catalog') as regenerate:
                configure(data)
                regenerate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
