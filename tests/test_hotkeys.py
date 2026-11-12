import ctypes as C
from ctypes import wintypes as W
import queue
import tkinter as tk
import unittest

from hotkeys import GlobalHotkey


class HotkeyTests(unittest.TestCase):
    def test_notification_survives_tk_event_processing(self):
        root = tk.Tk()
        root.withdraw()
        hotkey = GlobalHotkey(virtual_key=0x87, identifier=4199)  # F24 avoids production F8.
        user = C.WinDLL('user32', use_last_error=True)
        user.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]
        try:
            self.assertTrue(user.PostThreadMessageW(hotkey.thread_id, 0x312, 4199, 0x00870000))
            root.update()
            self.assertEqual(hotkey.events.get(timeout=2), 'toggle')
            root.update()
            with self.assertRaises(queue.Empty):
                hotkey.events.get_nowait()
        finally:
            hotkey.close()
            root.destroy()
        self.assertFalse(hotkey.thread.is_alive())

    def test_registration_is_released_on_close(self):
        first = GlobalHotkey(virtual_key=0x87, identifier=4198)
        first.close()
        second = GlobalHotkey(virtual_key=0x87, identifier=4198)
        second.close()
        self.assertFalse(second.thread.is_alive())

    def test_conflicting_registration_reports_error(self):
        first = GlobalHotkey(virtual_key=0x87, identifier=4197)
        try:
            with self.assertRaises(OSError):
                GlobalHotkey(virtual_key=0x87, identifier=4196)
        finally:
            first.close()


if __name__ == '__main__':
    unittest.main()
