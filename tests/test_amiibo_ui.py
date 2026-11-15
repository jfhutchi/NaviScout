import importlib.util
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock

from amiibo_catalog import PRESETS


class AmiiboPageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('amiibo_ui'))
        from amiibo_ui import AmiiboPage
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp = tempfile.TemporaryDirectory()
        self.page = AmiiboPage(self.root, Path(self.temp.name), Path(self.temp.name),
                               lambda: None, lambda: False, demo=True)

    def tearDown(self):
        if hasattr(self, 'root'):
            for job in self.root.tk.call('after', 'info'):
                self.root.after_cancel(job)
            self.root.destroy()
            self.temp.cleanup()

    def test_all_presets_are_individually_listed_and_searchable(self):
        self.assertEqual(len(self.page.tree.get_children()), 35)
        self.page.search.set('Sheik')
        self.assertEqual(len(self.page.tree.get_children()), 1)
        self.assertIn('Sheik', self.page.tree.item(self.page.tree.get_children()[0], 'text'))

    def test_a_click_sends_only_the_selected_preset_and_no_scan_all_control(self):
        choice = next(row for row in PRESETS if 'Sheik' in row.name)
        self.page.demo = False
        game = object()
        self.page.get_game = lambda: game
        self.page.reader = Mock(pending=False)
        self.page.tree.selection_set(choice.tag_id)
        self.page.send_selected()
        self.page.reader.begin_send.assert_called_once_with(game, choice)
        self.assertNotIn('Send all', [str(w.cget('text')) for w in self.page.winfo_children()
                                     if 'text' in w.keys()])

    def test_unknown_selection_and_demo_do_not_call_reader(self):
        self.page.reader = Mock(pending=False)
        self.page.send_selected()
        self.page.reader.begin_send.assert_not_called()

    def test_sending_does_not_claim_the_game_has_granted_a_reward(self):
        self.page.sent_name = 'Sheik'
        self.page.show_result('sent')
        self.assertIn('Sent', self.page.status.get())
        self.assertIn('game', self.page.status.get())
        self.assertNotIn('reward granted', self.page.status.get().lower())


if __name__ == '__main__':
    unittest.main()
