import tkinter as tk
import unittest

from core import RESOURCES
from skin import Switch


class ItemIconTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_every_refill_item_has_a_visible_original_icon(self):
        from item_icons import ItemIcon
        for name in RESOURCES:
            with self.subTest(name=name):
                icon = ItemIcon(self.root, name)
                self.assertTrue(icon.find_all())
                self.assertEqual(int(icon.cget('width')), 24)
                icon.destroy()

    def test_item_icon_click_toggles_the_same_control_once(self):
        value = tk.BooleanVar(self.root, False)
        switch = Switch(self.root, 'Rupees\n500/500', value, width=196, compact=True, icon='rupees')
        switch.pack()
        self.root.deiconify()
        self.root.update()
        switch.item_icon.event_generate('<Button-1>')
        self.assertTrue(value.get())
        switch.item_icon.event_generate('<Button-1>')
        self.assertFalse(value.get())

    def test_unknown_icon_is_reported(self):
        from item_icons import ItemIcon
        with self.assertRaises(ValueError):
            ItemIcon(self.root, 'unknown')


if __name__ == '__main__':
    unittest.main()
