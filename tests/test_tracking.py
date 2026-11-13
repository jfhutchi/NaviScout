from types import SimpleNamespace
import unittest

from tracking import decorate_catalog, height_text, target_caption, area_progress


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            dict(kind='skull', id=1, area='KokiriForest_Child', xyz=[0, 0, 0]),
            dict(kind='skull', id=1, area='KokiriForest_Child', floor=1, xyz=[0, 0, 0]),
            dict(kind='skull', id=2, area='KokiriForest_Child', xyz=[0, 0, 0]),
            dict(kind='skull', id=2, area='KokiriForest_Adult', xyz=[0, 0, 0]),
            dict(kind='heart', id=3, area='KakarikoVillage_Adult_Alternative', flag=100, xyz=[0, 0, 0]),
            dict(kind='skull', id=4, area='SpiritTemple', xyz=[0, 0, 0]),
        ]
        self.save = SimpleNamespace(ids={1, 2}, values={100: 1})

    def test_signed_height_is_shown_above_below_and_at_same_level(self):
        self.assertEqual(height_text(12.4), '+12 m up')
        self.assertEqual(height_text(-8.2), '-8 m down')
        self.assertEqual(height_text(-0.2), '0 m level')
        self.assertEqual(height_text(12.4, compact=True), '+12m')
        with self.assertRaises(ValueError):
            height_text(float('nan'))

    def test_age_metadata_combines_variants_without_guessing_unspecified_dungeons(self):
        result = decorate_catalog(self.items)
        self.assertEqual(result[0]['ages'], ['Child'])
        self.assertEqual(result[2]['ages'], ['Child', 'Adult'])
        self.assertEqual(result[3]['ages'], ['Child', 'Adult'])
        self.assertEqual(result[4]['ages'], ['Adult'])
        self.assertEqual(result[4]['region'], 'KakarikoVillage')
        self.assertEqual(result[5]['ages'], [])
        self.assertNotIn('ages', self.items[0])

    def test_nearest_caption_always_includes_signed_height_and_age(self):
        row = dict(kind='heart', distance=125, dy=-14, ages=['Child', 'Adult'])
        text = target_caption(row)
        self.assertIn('-14 m down', text)
        self.assertIn('Child / Adult', text)
        self.assertIn('125 m', text)
        self.assertIn('+6 m up', target_caption(dict(row, dy=6), near=True))

    def test_area_progress_deduplicates_floors_and_shared_age_locations(self):
        rows, totals = area_progress(decorate_catalog(self.items), self.save)
        forest = next(row for row in rows if row['region'] == 'KokiriForest')
        self.assertEqual(forest['skull'], (2, 2))
        self.assertEqual(totals['skull'], (2, 3))
        self.assertEqual(totals['heart'], (1, 1))
        child, child_totals = area_progress(decorate_catalog(self.items), self.save, 'Child')
        adult, adult_totals = area_progress(decorate_catalog(self.items), self.save, 'Adult')
        self.assertEqual(child_totals['skull'], (2, 2))
        self.assertEqual(adult_totals['skull'], (1, 1))
        self.assertEqual(adult_totals['heart'], (1, 1))
        unknown, unknown_totals = area_progress(decorate_catalog(self.items), self.save, 'Unknown')
        self.assertEqual(unknown_totals['skull'], (0, 1))
        self.assertEqual(unknown[0]['region'], 'SpiritTemple')


if __name__ == '__main__':
    unittest.main()
