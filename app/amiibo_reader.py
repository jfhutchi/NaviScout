"""Build-checked calls to NX2navi's native, thread-safe amiibo reader."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import hashlib
from pathlib import Path

from amiibo_catalog import cache_tag
from memory import K, NotReady
from running import ModuleEntry

CODE_RVA, CODE_SIZE = 0x102A6A90, 0xC7C
CODE_SHA256 = 'ccc11aa8b53df45da52da34ff11ef2116e9d33f7ab2f9c1bb9f4bc45b526778c'

K.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p,
                                C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
K.CreateRemoteThread.restype = W.HANDLE
K.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
K.WaitForSingleObject.restype = W.DWORD
K.GetExitCodeThread.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]


@dataclass(frozen=True)
class ReaderLayout:
    reader: int
    scan: int
    remove: int


def reader_layout(game):
    snapshot = K.CreateToolhelp32Snapshot(0x18, game.pid)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        module = ModuleEntry()
        module.size = C.sizeof(module)
        if not K.Module32FirstW(snapshot, C.byref(module)) or not module.base:
            raise NotReady('NX2navi native reader module is unavailable')
        if Path(module.path).resolve() != game.executable.resolve():
            raise ValueError('The amiibo reader belongs to another executable')
    finally:
        K.CloseHandle(snapshot)
    if (CODE_RVA + CODE_SIZE > module.image_size
            or hashlib.sha256(game.read(module.base + CODE_RVA, CODE_SIZE)).hexdigest() != CODE_SHA256):
        raise ValueError('This NX2navi amiibo reader is not recognized; a verified compatibility layout is needed')
    return ReaderLayout(module.base + 0x102A6DE0, module.base + 0x102A71C0, module.base + 0x102A7230)


class NativeCalls:
    """Call existing host functions; no instruction patches or executable allocations."""
    def __init__(self):
        self.process = self.thread = self.argument = None
        self.game = None

    @property
    def pending(self):
        return self.thread is not None

    def begin(self, game, address, argument=b''):
        if self.pending:
            raise NotReady('An amiibo reader request is already running')
        self.game = game
        self.process = K.OpenProcess(0x43A, False, game.pid)
        if not self.process:
            raise C.WinError(C.get_last_error())
        try:
            if argument:
                if len(argument) > 32768 or not argument.endswith(b'\0'):
                    raise ValueError('The amiibo reader path is invalid')
                self.argument = K.VirtualAllocEx(self.process, None, len(argument), 0x3000, 0x04)
                if not self.argument:
                    raise C.WinError(C.get_last_error())
                game.write_verified(self.argument, argument, 'amiibo reader path')
            self.thread = K.CreateRemoteThread(self.process, None, 0, address, self.argument, 0, None)
            if not self.thread:
                self.thread = None
                raise C.WinError(C.get_last_error())
        except (OSError, ValueError, NotReady):
            self._release()
            raise

    def poll(self):
        if not self.pending:
            raise ValueError('No amiibo reader request is running')
        status = K.WaitForSingleObject(self.thread, 0)
        if status == 258:
            return None
        if status != 0:
            raise C.WinError(C.get_last_error())
        result = W.DWORD()
        if not K.GetExitCodeThread(self.thread, C.byref(result)):
            raise C.WinError(C.get_last_error())
        self._release()
        return result.value

    def _release(self):
        if self.argument and self.game.alive():
            if not K.VirtualFreeEx(self.process, self.argument, 0, 0x8000):
                raise C.WinError(C.get_last_error())
        self.argument = None
        for handle in (self.thread, self.process):
            if handle:
                K.CloseHandle(handle)
        self.thread = self.process = None
        self.game = None


class AmiiboReader:
    def __init__(self, presets, calls=None):
        self.presets = tuple(presets)
        self.calls = calls if calls is not None else NativeCalls()
        self.phase = self.game = self.choice = self.layout = None

    @property
    def pending(self):
        return self.phase is not None or self.calls.pending

    def _begin(self, game):
        if self.pending:
            raise NotReady('Wait for the current amiibo request to finish')
        game.state()
        layout = reader_layout(game)
        self.game, self.layout = game, layout

    def begin_send(self, game, choice):
        if choice not in self.presets:
            raise ValueError('Select an amiibo supported by this game')
        self._begin(game)
        self.calls.begin(game, self.layout.reader)
        self.choice, self.phase = choice, 'query'

    def begin_remove(self, game):
        self._begin(game)
        self.calls.begin(game, self.layout.remove)
        self.phase = 'remove'

    def poll(self):
        result = self.calls.poll()
        if result is None:
            return None
        phase, self.phase = self.phase, None
        if phase == 'query':
            if result != 1:
                return 'not-ready'
            self.game.state()
            self.layout = reader_layout(self.game)
            # The native game's file access must resolve the token too. Use its
            # standard amiibo folder rather than another process's AppData cache.
            path = cache_tag(self.choice, self.game.executable.parent)
            self.calls.begin(self.game, self.layout.scan, str(path).encode('utf-8') + b'\0')
            self.phase = 'scan'
            return None
        if phase == 'scan':
            # The native function returns bool in AL; upper return bits are unspecified.
            return 'sent' if result & 0xFF else 'load-failed'
        if phase == 'remove':
            return 'removed'
        raise ValueError('The amiibo reader request has an invalid phase')

    def restore(self, _game):
        if self.calls.pending and self.calls.poll() is None:
            raise NotReady('Waiting for the amiibo reader request to finish')
        self.phase = self.game = self.choice = self.layout = None
