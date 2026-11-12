"""Global hotkeys with a message queue independent of Tk's event loop."""
import ctypes as C
from ctypes import wintypes as W
import queue
import threading


USER = C.WinDLL('user32', use_last_error=True)
KERNEL = C.WinDLL('kernel32', use_last_error=True)
USER.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
USER.UnregisterHotKey.argtypes = [W.HWND, C.c_int]
USER.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
USER.GetMessageW.restype = W.BOOL
USER.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]
KERNEL.GetCurrentThreadId.restype = W.DWORD


class GlobalHotkey:
    def __init__(self, virtual_key=0x77, identifier=4107):
        self.virtual_key = virtual_key
        self.identifier = identifier
        self.events = queue.Queue()
        self.ready = threading.Event()
        self.thread_id = 0
        self.start_error = None
        self.thread = threading.Thread(target=self._run, name='Navi Scout hotkey', daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout=2):
            raise TimeoutError('Hotkey listener did not start')
        if self.start_error is not None:
            self.thread.join(timeout=2)
            raise self.start_error

    def _run(self):
        self.thread_id = KERNEL.GetCurrentThreadId()
        if not USER.RegisterHotKey(None, self.identifier, 0x4000, self.virtual_key):
            self.start_error = C.WinError(C.get_last_error())
            self.ready.set()
            return
        self.ready.set()
        try:
            message = W.MSG()
            while True:
                result = USER.GetMessageW(C.byref(message), None, 0, 0)
                if result == 0:
                    return
                if result == -1:
                    self.events.put(C.WinError(C.get_last_error()))
                    return
                if message.message == 0x0312 and message.wParam == self.identifier:
                    self.events.put('toggle')
        finally:
            if not USER.UnregisterHotKey(None, self.identifier):
                self.events.put(C.WinError(C.get_last_error()))

    def close(self):
        if not self.thread.is_alive():
            return
        if not USER.PostThreadMessageW(self.thread_id, 0x0012, 0, 0):
            raise C.WinError(C.get_last_error())
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('Hotkey listener did not stop')
