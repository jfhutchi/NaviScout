"""Reversible enemy-only perception filters that preserve Navi's player signal."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import hashlib
import struct

from assembly import Assembly
from memory import K, NotReady
from running import ModuleEntry, RunSpeed


@dataclass(frozen=True)
class StealthLayout:
    candidate_rva: int
    copy_rva: int
    signatures: tuple


# Hash the collector as well as its two entry points: the copied-record filter
# depends on the collector's guest call sites and X19 query-context convention.
STEALTH_LAYOUTS = (
    StealthLayout(0xBF96940, 0xBF88330,
                  ((0xBF96940, 4035, 'abfe16db1ddfa9a8b28f97f79c03edf027c046ca04f8d54147985f5158d4c88f'),
                   (0xBF88330, 1188, 'ec1fd3d6095ef9bbe08f8020a43ddfdd7e1c9d2a524fc1f086fef8bb04620bf3'),
                   (0x2D6760, 10250, '4d8211ca28af06fb2c3f2b43b27849fb29ed9ffa24668b9a2faf358d5659c5bb'))),
)
PROLOGUES = (bytes.fromhex('415741564155'), bytes.fromhex('415741565657'))


def select_stealth_layout(game, base, image_size):
    for layout in STEALTH_LAYOUTS:
        if any(rva + size > image_size for rva, size, _ in layout.signatures):
            continue
        if all(hashlib.sha256(game.read(base + rva, size)).hexdigest() == expected
               for rva, size, expected in layout.signatures):
            return layout
    raise ValueError('Enemy-only perception code is not recognized by this Navi Scout build; a verified compatibility layout is needed')


def enemy_filter_stub(control, trampoline, copied=False):
    a = Assembly()
    saved = '9c 50 51 52 53 55 56 57 4150 4151 4152 4153 4154 4155 4156 4157'
    restored = '415f 415e 415d 415c 415b 415a 4159 4158 5f 5e 5d 5b 5a 59 58 9d'
    a.emit(saved + ' 4989cc')
    a.address('48bb', control)
    if copied:
        # Only the collector's two copy/retention calls carry this query context.
        a.emit('498b8424f0000000')
        a.address('48ba', 0x70000DA5CC)
        a.emit('4839d0')
        a.branch('0f84', 'copy')
        a.address('48ba', 0x70000DA6C8)
        a.emit('4839d0')
        a.branch('0f85', 'pass')
        a.labels['copy'] = len(a.code)
        a.emit('4d8bac2498000000 4d8b742408 4d85f6')
        a.branch('0f84', 'pass')
        a.emit('4d8bb6d0000000')
    else:
        a.emit('4d8b6c2408 4d8b742410')
    a.emit('4d85ed')
    a.branch('0f84', 'pass')
    a.emit('4d85f6')
    a.branch('0f84', 'pass')
    a.emit('488b03 488b00 4885c0')
    a.branch('0f84', 'pass')
    a.emit('488bb080040000 4885f6')
    a.branch('0f84', 'pass')
    a.emit('488b8670020000 4885c0')
    a.branch('0f84', 'pass')
    a.emit('488b8028030000 4885c0')
    a.branch('0f84', 'pass')
    a.emit('488b5308 483910')  # Current Player emitter type, owner and SDK object.
    a.branch('0f85', 'pass')
    a.emit('48397018')
    a.branch('0f85', 'pass')
    a.emit('4c397030')
    a.branch('0f85', 'pass')
    a.emit('498bbdb0000000 4885ff')
    a.branch('0f84', 'pass')
    a.emit('4839f7')
    a.branch('0f84', 'pass')
    a.emit('488b8770020000 4885c0')
    a.branch('0f84', 'pass')
    a.emit('488b8030010000 4885c0')
    a.branch('0f84', 'pass')
    a.emit('48397818')
    a.branch('0f85', 'pass')
    a.emit('83782801')
    a.branch('0f85', 'friendly')
    # Return the collector's ordinary "rejected" result. Do not change emitters,
    # reason lists, actor visibility, other signals, or any other guest CPU state.
    a.emit('49c7042400000000 f048ff4310 48897b18')
    a.emit(restored + ' c3')
    a.labels['friendly'] = len(a.code)
    a.emit('f048ff4320')
    a.labels['pass'] = len(a.code)
    a.emit(restored)
    a.address('ff2500000000', trampoline)
    return a.finish()


class EnemyStealth:
    def __init__(self):
        self.owner = self.base = self.allocation = self.control = self.layout = None
        self.patches = ()
        self.installed = False
        self.guard = RunSpeed()

    def update(self, game, enabled):
        if self.owner is not None and self.owner is not game:
            if self.owner.alive():
                raise NotReady('Enemy stealth still belongs to a different game process')
            self.__init__()
        if not enabled:
            self.restore(game)
            return 'Enemies: normal detection'
        if self.allocation:
            current = tuple(game.read(entry, len(original)) for entry, original, patch in self.patches)
            if not self.installed or any(raw == original for raw, (_, original, _) in zip(current, self.patches)):
                self.restore(game)
                return self.update(game, enabled)
            if any(raw != patch for raw, (_, _, patch) in zip(current, self.patches)):
                raise NotReady('Enemy-perception code changed outside Navi Scout')
        else:
            self.install(game)
        return 'Enemy-only stealth: Navi and friendly NPCs keep normal perception. Existing aggro may remain.'

    def install(self, game):
        snapshot = K.CreateToolhelp32Snapshot(0x18, game.pid)
        if snapshot == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        try:
            module = ModuleEntry()
            module.size = C.sizeof(module)
            if not K.Module32FirstW(snapshot, C.byref(module)) or not module.base:
                raise NotReady('The Windows game module is unavailable')
        finally:
            K.CloseHandle(snapshot)
        self.base = module.base
        self.layout = select_stealth_layout(game, self.base, module.image_size)
        entries = tuple(self.base + rva for rva in (self.layout.candidate_rva, self.layout.copy_rva))
        start = (self.base + module.image_size + 65535) & ~65535
        for index in range(256):
            candidate = start + index * 65536
            if candidate - min(entries) >= (1 << 31):
                break
            self.allocation = K.VirtualAllocEx(game.handle, candidate, 8192, 0x3000, 4)
            if self.allocation:
                break
        if not self.allocation:
            raise OSError('Could not allocate the temporary enemy-stealth filters')
        self.owner, self.control = game, self.allocation + 4096
        self.patches = tuple((entry, original,
                              b'\xe9' + struct.pack('<i', self.allocation + index * 1024 - entry - 5) + b'\x90')
                             for index, (entry, original) in enumerate(zip(entries, PROLOGUES)))
        for index, (entry, original, _) in enumerate(self.patches):
            trampoline = self.allocation + 2048 + index * 256
            code = enemy_filter_stub(self.control, trampoline, copied=bool(index))
            if len(code) >= 1024:
                raise ValueError('Enemy-stealth filter exceeds its reserved code area')
            game.write_verified(self.allocation + index * 1024, code, 'Enemy stealth filter')
            game.write_verified(trampoline, original + b'\xff\x25\0\0\0\0' + struct.pack('<Q', entry + len(original)),
                                'Enemy stealth continuation')
        game.write_verified(self.control, struct.pack('<8Q', game.BASE + 0x4E371D0,
                                                     game.BASE + 0x4B4D578, 0, 0, 0, 0, 0, 0),
                            'Enemy stealth filter state')
        old = W.DWORD()
        if not K.VirtualProtectEx(game.handle, self.allocation, 4096, 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        if not K.FlushInstructionCache(game.handle, self.allocation, 4096):
            raise C.WinError(C.get_last_error())
        with self.guard.paused(game, [(entry, entry + len(original)) for entry, original, _ in self.patches]):
            for entry, original, patch in self.patches:
                self.guard.code_write(game, entry, original, patch)
            self.installed = True

    def restore(self, game):
        if not self.allocation:
            return
        if self.owner is not game:
            if self.owner is not None and self.owner.alive():
                raise NotReady('Cannot restore enemy stealth through another game process')
            self.__init__()
            return
        # Neither filter calls outward. Once its RIP leaves the allocation there
        # is no pending return into it; suspend/check all threads before removal.
        ranges = [(entry, entry + len(original)) for entry, original, _ in self.patches]
        ranges.append((self.allocation, self.allocation + 4096))
        with self.guard.paused(game, ranges):
            current = tuple(game.read(entry, len(original)) for entry, original, _ in self.patches)
            if any(raw not in (original, patch) for raw, (_, original, patch) in zip(current, self.patches)):
                raise NotReady('Enemy-stealth code changed outside Navi Scout; restore cancelled')
            for raw, (entry, original, patch) in zip(current, self.patches):
                if raw == patch:
                    self.guard.code_write(game, entry, patch, original)
            if not K.VirtualFreeEx(game.handle, self.allocation, 0, 0x8000):
                raise C.WinError(C.get_last_error())
            self.__init__()
