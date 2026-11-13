"""Reversible, ownership-filtered damage boost at the shared hit-processing stage."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import struct

from assembly import Assembly
from memory import K, NotReady
from running import ModuleEntry, RunSpeed

FUNCTION_RVA, FUNCTION_SIZE = 0x137BB80, 13328
FUNCTION_SHA256 = '879cdbaaa97b4e4fd0718b3e77006ec1e8f3acbcb6411a37ff61c85cc5d95156'
PROLOGUE = bytes.fromhex('415741564155')


def damage_stub(control, trampoline):
    a = Assembly()
    # No external calls: preserve all host registers/flags and leave Cpu untouched.
    # The trampoline tail-jumps into the original function, which keeps immunity,
    # scripted forced-damage rules and enemy-specific callbacks in control.
    a.emit('9c 50 51 52 53 55 56 57 4150 4151 4152 4153 4154 4155 4156 4157 4989cc')
    a.address('48bb', control)
    a.emit('4d8b2c24 4d8b742410 4d85ed')  # Cpu.X0 calculator; X2 full DamageInfo.
    a.branch('0f84', 'done')
    a.emit('4d85f6')
    a.branch('0f84', 'done')
    a.emit('488b4318 488b00 4885c0')
    a.branch('0f84', 'done')
    a.emit('488bb080040000 4885f6')  # Current player, resolved on every hit.
    a.branch('0f84', 'done')
    a.emit('498b4508 4885c0')
    a.branch('0f84', 'done')
    a.emit('4839f0')
    a.branch('0f84', 'done')
    a.emit('488b9070020000 4885d2')
    a.branch('0f84', 'done')
    a.emit('488b8ab8020000 4885c9')  # Validate calculator's owning Life component.
    a.branch('0f84', 'done')
    a.emit('48394118')
    a.branch('0f85', 'done')
    a.emit('4881c110020000 4c39e9')
    a.branch('0f85', 'done')
    a.emit('488b8a30010000 4885c9')
    a.branch('0f84', 'done')
    a.emit('48394118')
    a.branch('0f85', 'done')
    a.emit('83792801')  # Current affiliation must be Enemy, not Neutral/Friendly.
    a.branch('0f85', 'done')
    a.emit('418b06 85c0')
    a.branch('0f8e', 'done')
    a.emit('3dffffff3f')
    a.branch('0f87', 'done')
    a.emit('498d4e20 41b808000000')  # Bounded ActorLink creator-chain traversal.
    a.labels['resolve'] = len(a.code)
    a.emit('448b4910 4183f9ff')
    a.branch('0f84', 'done')
    a.emit('488b5108 4885d2')
    a.branch('0f84', 'done')
    a.emit('44394a48')
    a.branch('0f85', 'done')
    a.emit('488b7a40 4885ff')
    a.branch('0f84', 'done')
    a.emit('8b472c 83e807 83f804')  # Native ActorLink rejects states 7 through 11.
    a.branch('0f86', 'done')
    a.emit('4839f7')
    a.branch('0f84', 'boost')
    a.emit('41ffc8')
    a.branch('0f84', 'done')
    a.emit('488b8770020000 4885c0')
    a.branch('0f84', 'done')
    a.emit('488b88d8010000 4885c9')
    a.branch('0f84', 'done')
    a.emit('48397918')
    a.branch('0f85', 'done')
    a.emit('4883c120')
    a.branch('e9', 'resolve')
    a.labels['boost'] = len(a.code)
    a.emit('418b06 8d1400 418916 48c1e220 4809d0 48894310 f048ff4308')
    a.labels['done'] = len(a.code)
    a.emit('415f 415e 415d 415c 415b 415a 4159 4158 5f 5e 5d 5b 5a 59 58 9d')
    a.address('ff2500000000', trampoline)
    return a.finish()


class EnemyDamage:
    def __init__(self):
        self.base = self.allocation = self.control = self.owner = self.patch = None
        self.guard = RunSpeed()

    def update(self, game, enabled):
        if self.owner is not None and self.owner is not game:
            if self.owner.alive():
                raise NotReady('Damage control still belongs to a different game process')
            self.__init__()
        if not enabled:
            self.restore(game)
            return 'Damage to enemies: normal'
        if self.allocation:
            current = game.read(self.base + FUNCTION_RVA, len(PROLOGUE))
            if current == PROLOGUE:
                self.restore(game)
                return self.update(game, enabled)
            if current != self.patch:
                raise NotReady('Damage-processing code changed outside Navi Scout')
        else:
            self.install(game)
        return 'Damage 2x: Link-owned attacks; enemy rules still apply'

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
        if hashlib.sha256(game.read(self.base + FUNCTION_RVA, FUNCTION_SIZE)).hexdigest() != FUNCTION_SHA256:
            raise ValueError('Damage 2x needs the supported NX2navi 0.9.2 Windows code signature')
        entry = self.base + FUNCTION_RVA
        start = (self.base + module.image_size + 65535) & ~65535
        for index in range(256):
            candidate = start + index * 65536
            if candidate - entry >= (1 << 31):
                break
            self.allocation = K.VirtualAllocEx(game.handle, candidate, 8192, 0x3000, 4)
            if self.allocation:
                break
        if not self.allocation:
            raise OSError('Could not allocate the temporary damage helper')
        self.owner, self.control = game, self.allocation + 4096
        trampoline = self.allocation + 2048
        code = damage_stub(self.control, trampoline)
        if len(code) >= 2048:
            raise ValueError('Damage helper exceeds its reserved code area')
        game.write_verified(self.allocation, code, 'Damage helper')
        game.write_verified(trampoline, PROLOGUE + b'\xff\x25\0\0\0\0' + struct.pack('<Q', entry + 6),
                            'Damage continuation')
        game.write_verified(self.control, struct.pack('<QQQQ', 0, 0, 0, game.BASE + 0x4E371D0), 'Damage helper state')
        old = W.DWORD()
        if not K.VirtualProtectEx(game.handle, self.allocation, 4096, 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        if not K.FlushInstructionCache(game.handle, self.allocation, 4096):
            raise C.WinError(C.get_last_error())
        self.patch = b'\xe9' + struct.pack('<i', self.allocation - entry - 5) + b'\x90'
        with self.guard.paused(game, [(entry, entry + 6)]):
            self.guard.code_write(game, entry, PROLOGUE, self.patch)

    def restore(self, game):
        if not self.allocation:
            return
        if self.owner is not game:
            if self.owner is not None and self.owner.alive():
                raise NotReady('Cannot restore damage controls through another game process')
            self.__init__()
            return
        entry = self.base + FUNCTION_RVA
        # The stub never calls outward: after it leaves the trampoline no stack
        # return address refers to this allocation. Checking all paused RIPs suffices.
        with self.guard.paused(game, [(entry, entry + 6), (self.allocation, self.allocation + 4096)]):
            current = game.read(entry, 6)
            if current == self.patch:
                self.guard.code_write(game, entry, self.patch, PROLOGUE)
            elif current != PROLOGUE:
                raise NotReady('Damage code changed outside Navi Scout; restore cancelled')
            if not K.VirtualFreeEx(game.handle, self.allocation, 0, 0x8000):
                raise C.WinError(C.get_last_error())
            self.__init__()
