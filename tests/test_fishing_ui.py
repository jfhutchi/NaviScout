from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from companion import Companion


class FishingUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Companion(Path(self.temp.name), Path(self.temp.name), demo=True)
        self.app.root.withdraw()

    def tearDown(self):
        for job in self.app.root.tk.call('after', 'info'):
            self.app.root.after_cancel(job)
        self.app.root.destroy()
        self.temp.cleanup()

    def test_fishing_has_its_own_tab_and_independent_saved_switches(self):
        titles = [self.app.controls.tab(tab, 'text') for tab in self.app.controls.tabs()]
        self.assertIn('Fishing', titles)
        self.assertEqual(set(self.app.fishing_enabled), {'hook_window', 'escape_window', 'quick_exhaust', 'reel_speed'})
        preferences = self.app.preference_vars()
        for name, value in self.app.fishing_enabled.items():
            self.assertFalse(value.get())
            self.assertIs(preferences[f'fishing_{name}'], value)

    def test_fishing_failure_does_not_disable_link_or_round_assists(self):
        self.app.game = SimpleNamespace(alive=lambda: True)
        self.app.fishing_assists = SimpleNamespace(update=Mock(side_effect=ValueError('Unsupported fishing layout')))
        self.app.run_speed.set(True)
        self.app.minigames.set(True)
        self.app.fishing_enabled['quick_exhaust'].set(True)
        with self.assertLogs(level='ERROR'):
            self.app.refresh_fishing()
        self.assertFalse(any(value.get() for value in self.app.fishing_enabled.values()))
        self.assertTrue(self.app.run_speed.get())
        self.assertTrue(self.app.minigames.get())
        self.assertIn('Unsupported fishing layout', self.app.fishing_text.get())

    def test_close_restores_fishing_even_if_a_link_override_fails(self):
        restore = Mock()
        self.app.game = SimpleNamespace(alive=lambda: True, close=lambda: None)
        self.app.run_modifier = SimpleNamespace(restore=Mock(side_effect=OSError('Run restore failed')))
        self.app.fishing_assists = SimpleNamespace(restore=restore)
        with patch('companion.messagebox.showwarning'), patch.object(self.app.root, 'destroy'), \
             self.assertLogs(level='ERROR'):
            self.app.close()
        restore.assert_called_once_with(self.app.game)


if __name__ == '__main__':
    unittest.main()
