"""Build-checked, reversible normal-running override for the Windows port."""
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import hashlib
import struct

from memory import K, NotReady


# Only this Move callback calls the shared velocity helper through this site.
# Hash the entire callback before using its host offsets; rebuilt ports can differ.
FUNCTION_RVA, FUNCTION_SIZE = 0x2682A30, 17568
FUNCTION_SHA256 = 'be3dc1415110fac323cd5d43804eb3b2cdb6923816d4c585fbf96b68425db2f5'
CALL_RVA, VELOCITY_RVA = 0x26860A1, 0x264F8E0
ORIGINAL_CALL = bytes.fromhex('e83a98fcff')


class ModuleEntry(C.Structure):
    _fields_ = [('size', W.DWORD), ('module', W.DWORD), ('pid', W.DWORD),
                ('global_usage', W.DWORD), ('usage', W.DWORD), ('base', C.c_void_p),
                ('image_size', W.DWORD), ('handle', W.HMODULE),
                ('name', W.WCHAR * 256), ('path', W.WCHAR * 260)]


class ThreadEntry(C.Structure):
    _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('tid', W.DWORD),
                ('pid', W.DWORD), ('priority', W.LONG), ('delta', W.LONG), ('flags', W.DWORD)]


K.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(ModuleEntry)]
K.Thread32First.argtypes = K.Thread32Next.argtypes = [W.HANDLE, C.POINTER(ThreadEntry)]
K.OpenThread.argtypes, K.OpenThread.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
K.SuspendThread.argtypes = K.ResumeThread.argtypes = [W.HANDLE]
K.SuspendThread.restype = K.ResumeThread.restype = W.DWORD
K.GetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
K.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
K.VirtualAllocEx.restype = C.c_void_p
K.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
K.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
K.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]


def run_stub(velocity_address):
    # Windows x64: RCX is Cpu*. Integer registers, metadata and padding precede
    # guest V[32] at 0x200. Tail-call the
    # original helper with twice the translation magnitude. XMM0/RAX are volatile.
    return (bytes.fromhex('f30f108100020000 f30f58c0 f30f118100020000 48b8')
            + struct.pack('<Q', velocity_address) + bytes.fromhex('ffe0'))


def relative_call(source, target):
    displacement = target - source - 5
    if not -(1 << 31) <= displacement < (1 << 31):
        raise ValueError('Run-speed helper is outside the relative-call range')
    return b'\xe8' + struct.pack('<i', displacement)


class RunSpeed:
    def __init__(self):
        self.base = self.stub = None
        self.replacement = None
        self.owner = None

    @contextmanager
    def paused(self, game, ranges):
        """Never replace instructions while a game thread is executing them."""
        handles, seen = [], set()
        try:
            for attempt in range(4):
                snapshot = K.CreateToolhelp32Snapshot(4, 0)
                if snapshot == C.c_void_p(-1).value:
                    raise C.WinError(C.get_last_error())
                new = []
                try:
                    entry = ThreadEntry()
                    entry.size = C.sizeof(entry)
                    found = K.Thread32First(snapshot, C.byref(entry))
                    while found:
                        if entry.pid == game.pid and entry.tid not in seen:
                            new.append(entry.tid)
                        found = K.Thread32Next(snapshot, C.byref(entry))
                finally:
                    K.CloseHandle(snapshot)
                if not new:
                    break
                for tid in new:
                    handle = K.OpenThread(0x5A, False, tid)
                    if not handle:
                        raise C.WinError(C.get_last_error())
                    if K.SuspendThread(handle) == 0xFFFFFFFF:
                        K.CloseHandle(handle)
                        raise C.WinError(C.get_last_error())
                    handles.append(handle)
                    seen.add(tid)
                    storage = C.create_string_buffer(1232 + 16)
                    aligned = (C.addressof(storage) + 15) & ~15
                    C.c_uint32.from_address(aligned + 48).value = 0x100001
                    if not K.GetThreadContext(handle, aligned):
                        raise C.WinError(C.get_last_error())
                    pc = C.c_uint64.from_address(aligned + 248).value
                    if any(start <= pc < end for start, end in ranges):
                        raise NotReady('Movement update is busy; try the switch again')
            else:
                raise NotReady('Game threads changed during the movement update')
            if not handles:
                raise NotReady('No active game threads are available')
            yield
        finally:
            failures = []
            for handle in reversed(handles):
                if K.ResumeThread(handle) == 0xFFFFFFFF:
                    failures.append(C.get_last_error())
                K.CloseHandle(handle)
            if failures:
                raise C.WinError(failures[0])

    def code_write(self, game, address, expected, replacement):
        if game.read(address, len(expected)) != expected:
            raise NotReady('Run-speed code changed outside Navi Scout; write cancelled')
        old, unused = W.DWORD(), W.DWORD()
        if not K.VirtualProtectEx(game.handle, address, len(replacement), 0x40, C.byref(old)):
            raise C.WinError(C.get_last_error())
        try:
            try:
                game.write_verified(address, replacement, 'Navi Scout movement/perception code')
                if not K.FlushInstructionCache(game.handle, address, len(replacement)):
                    raise C.WinError(C.get_last_error())
            except (NotReady, OSError):
                # This runs with all game threads suspended. Roll back before
                # they resume if writing or its verification did not complete.
                game.write_verified(address, expected, 'Restore interrupted Navi Scout code update')
                if not K.FlushInstructionCache(game.handle, address, len(expected)):
                    raise C.WinError(C.get_last_error())
                raise
        finally:
            if not K.VirtualProtectEx(game.handle, address, len(replacement), old.value, C.byref(unused)):
                raise C.WinError(C.get_last_error())

    def update(self, game, enabled):
        if self.owner is not None and self.owner is not game:
            if self.owner.alive():
                raise NotReady('Running control still belongs to a different game process')
            self.base = self.stub = self.replacement = self.owner = None
        if not enabled:
            self.restore(game)
            return
        if self.stub:
            current = game.read(self.base + CALL_RVA, 5)
            if current == ORIGINAL_CALL:
                self.restore(game)
                return self.update(game, enabled)
            if current != self.replacement:
                raise NotReady('Running override changed outside Navi Scout')
            return
        snapshot = K.CreateToolhelp32Snapshot(0x18, game.pid)
        if snapshot == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        try:
            module = ModuleEntry()
            module.size = C.sizeof(module)
            if not K.Module32FirstW(snapshot, C.byref(module)) or not module.base:
                raise NotReady('The Windows game module is unavailable')
            self.base = module.base
        finally:
            K.CloseHandle(snapshot)
        current = game.read(self.base + FUNCTION_RVA, FUNCTION_SIZE)
        if hashlib.sha256(current).hexdigest() != FUNCTION_SHA256:
            raise ValueError('Run / swim 2x needs the supported NX2navi 0.9.2 Windows build; code signature differs')
        address = self.base + CALL_RVA
        if game.read(address, 5) != ORIGINAL_CALL:
            raise NotReady('Normal-running call validation failed')
        # Allocate beyond the module, within the x64 relative-call range.
        start = (self.base + module.image_size + 65535) & ~65535
        for index in range(256):
            candidate = start + index * 65536
            if candidate - address >= (1 << 31):
                break
            self.stub = K.VirtualAllocEx(game.handle, candidate, 4096, 0x3000, 4)
            if self.stub:
                break
        if not self.stub:
            raise OSError('Could not allocate the temporary running-speed helper')
        self.owner = game
        self.replacement = relative_call(address, self.stub)
        game.write_verified(self.stub, run_stub(self.base + VELOCITY_RVA), 'Temporary running helper')
        old = W.DWORD()
        if not K.VirtualProtectEx(game.handle, self.stub, 4096, 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        if not K.FlushInstructionCache(game.handle, self.stub, 4096):
            raise C.WinError(C.get_last_error())
        with self.paused(game, [(address, address + 5)]):
            self.code_write(game, address, ORIGINAL_CALL, self.replacement)

    def restore(self, game):
        if not self.stub:
            return
        if self.owner is not game:
            if self.owner is not None and self.owner.alive():
                raise NotReady('Cannot restore running controls through another game process')
            self.base = self.stub = self.replacement = self.owner = None
            return
        address = self.base + CALL_RVA
        with self.paused(game, [(address, address + 5), (self.stub, self.stub + 4096)]):
            current = game.read(address, 5)
            if current == self.replacement:
                self.code_write(game, address, self.replacement, ORIGINAL_CALL)
            elif current != ORIGINAL_CALL:
                raise NotReady('Running code changed outside Navi Scout; restore cancelled')
            if not K.VirtualFreeEx(game.handle, self.stub, 0, 0x8000):
                raise C.WinError(C.get_last_error())
            self.stub = self.replacement = None
            self.owner = None
