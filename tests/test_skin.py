import tkinter as tk
import unittest

from skin import Switch, ChoiceStrip


class SkinTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_toggle_updates_shared_variable_and_tracks_external_changes(self):
        value = tk.BooleanVar(self.root, False)
        switch = Switch(self.root, 'Run / swim speed 2x', value)
        switch.invoke()
        self.assertTrue(value.get())
        value.set(False)
        self.assertEqual(switch.state_text(), 'Off')
        switch.invoke()
        self.assertEqual(switch.state_text(), 'On')

    def test_choice_strip_keeps_one_dive_mode_and_preserves_off(self):
        value = tk.StringVar(self.root, 'Off')
        strip = ChoiceStrip(self.root, value, ('Off', '2x', 'Unlimited'))
        strip.choose('Unlimited')
        self.assertEqual(value.get(), 'Unlimited')
        strip.choose('Off')
        self.assertEqual(value.get(), 'Off')
        with self.assertRaises(ValueError):
            strip.choose('unknown')


if __name__ == '__main__':
    unittest.main()
