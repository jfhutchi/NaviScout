"""Apply an independently owned perception-disable reason on the game thread."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import struct

from memory import Game, K, NotReady
from running import ModuleEntry, RunSpeed

EMITTER_RVA, SETTER_RVA = 0xB7FFE40, 0x4132E0
SIGNATURES = ((EMITTER_RVA, 9600, '61f78ee08ac0ea0b2338fa73d8cd545185524eb1ca824ed69d8cd01ea0482e77'),
              (SETTER_RVA, 1088, 'd24ca997b95f137aebbb739d22eefe4ab975be122b01c1ece1f6fb6c796ffd59'))
PROLOGUE = bytes.fromhex('415741564155')
REASON = 0x4E534354


class Assembly:
    def __init__(self):
        self.code, self.fixups, self.labels = bytearray(), [], {}

    def emit(self, raw):
        self.code.extend(bytes.fromhex(raw))

    def address(self, opcode, address):
        self.emit(opcode)
        self.code.extend(struct.pack('<Q', address))

    def branch(self, opcode, label):
        self.emit(opcode)
        self.fixups.append((len(self.code), label))
        self.code.extend(bytes(4))

    def finish(self):
        for offset, label in self.fixups:
            struct.pack_into('<i', self.code, offset, self.labels[label] - offset - 4)
        return bytes(self.code)


def stealth_stub(control, setter, trampoline):
    a = Assembly()
    # Preserve Windows nonvolatile registers, align RSP, reserve shadow space and
    # a complete 1024-byte Cpu snapshot. Calls below execute on the game's thread.
    a.emit('53 56 57 4154 4881ec28040000 4989cc')
    a.address('48bb', control)
    a.emit('498b0424 483b03')  # Cpu.X0 must be the selected emitter.
    a.branch('0f85', 'done')
    a.emit('488b5328 483910')  # Component type and owner.
    a.branch('0f85', 'done')
    a.emit('488b5018 483b5308')
    a.branch('0f85', 'done')
    a.emit('488b4320 488b00 4885c0')
    a.branch('0f84', 'done')
    a.emit('483b9080040000')  # Owner is still the current Player.
    a.branch('0f85', 'done')
    a.emit('488b8270020000 4885c0')
    a.branch('0f84', 'done')
    a.emit('488b8028030000 483b03')
    a.branch('0f85', 'done')
    a.emit('8b4310 3b4314')  # Requested state already acknowledged.
    a.branch('0f84', 'done')
    a.emit('31c0 ba01000000 f00fb15318')  # One executor per command.
    a.branch('0f85', 'done')
    a.emit('8b4310 89842420040000')
    # The native full-ring path evicts an unrelated reason. Never enter it when
    # adding ours: validate capacity/indices on the executing game thread.
    a.emit('488b03 8b5040 83fa01')
    a.branch('0f82', 'full')
    a.emit('81fa80000000')
    a.branch('0f87', 'full')
    a.emit('8b4844 39d1')
    a.branch('0f83', 'full')
    a.emit('8b4848 39d1')
    a.branch('0f87', 'full')
    a.emit('83bc242004000000')
    a.branch('0f84', 'save')
    a.emit('39d1')
    a.branch('0f83', 'full')
    a.labels['save'] = len(a.code)
    a.emit('c7433000000000 488d7c2420 4c89e6 b980000000 f348a5')
    # Native setter(emitter reason-list, &our uint32 reason, !invisible).
    a.emit('488b03 4883c020 49890424 488d431c 4989442408')
    a.emit('8b842420040000 83f001 4989442410 4c89e1')
    a.address('48b8', setter)
    a.emit('ffd0')
    a.emit('488d742420 4c89e7 b980000000 f348a5')  # Restore all guest state.
    a.emit('8b842420040000 894314 c7431800000000')
    a.branch('e9', 'done')
    a.labels['full'] = len(a.code)
    a.emit('c7433001000000 c7431800000000')
    a.labels['done'] = len(a.code)
    a.emit('4c89e1 4881c428040000 415c 5f 5e 5b')
    a.address('48b8', trampoline)
    a.emit('ffe0')
    return a.finish()


def emitter_context(game):
    actor = game.pointer(game.pointer(game.BASE + 0x4E371D0) + 0x480)
    if not actor or game.read(game.pointer(actor + 0x20), 7) != b'Player\0':
        raise NotReady('Link is not available for enemy stealth')
    table = game.pointer(actor + 0x270)
    emitter = game.pointer(table + 0x328)
    if (game.pointer(emitter) != game.BASE + 0x4B4D578
            or game.pointer(emitter + 0x18) != actor
            or game.pointer(emitter + 0x20) != game.BASE + 0x4B4D6D8):
        raise NotReady('Link perception emitter validation failed')
    capacity, first, count = game.unpack(emitter + 0x40, '<iii')
    if not 1 <= capacity <= 128 or not 0 <= first < capacity or not 0 <= count <= capacity:
        raise NotReady('Link perception reason list is invalid')
    entries = game.pointer(emitter + 0x38)
    reasons = [game.unpack(entries + ((first + i) % capacity) * 4, '<I')[0] for i in range(count)]
    return (actor, table, emitter), reasons


class EnemyStealth:
    def __init__(self):
        self.owner = self.base = self.allocation = self.context = self.patch = None
        self.installed = False
        self.initialized = False
        self.guard = RunSpeed()

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
        for rva, size, expected in SIGNATURES:
            if hashlib.sha256(game.read(self.base + rva, size)).hexdigest() != expected:
                raise ValueError('Enemy stealth needs the supported NX2navi 0.9.2 Windows code signature')
        entry = self.base + EMITTER_RVA
        start = (self.base + module.image_size + 65535) & ~65535
        for index in range(256):
            candidate = start + index * 65536
            if candidate - entry >= (1 << 31):
                break
            self.allocation = K.VirtualAllocEx(game.handle, candidate, 8192, 0x3000, 4)
            if self.allocation:
                break
        if not self.allocation:
            raise OSError('Could not allocate the temporary enemy-stealth helper')
        self.owner = game
        self.control = self.allocation + 4096
        trampoline = self.allocation + 2048
        code = stealth_stub(self.control, self.base + SETTER_RVA, trampoline)
        if len(code) >= 2048:
            raise ValueError('Enemy-stealth helper exceeds its reserved code area')
        game.write_verified(self.allocation, code, 'Enemy stealth helper')
        game.write_verified(trampoline, PROLOGUE + b'\x48\xb8' + struct.pack('<Q', entry + 6) + b'\xff\xe0',
                            'Enemy stealth continuation')
        actor, table, emitter = self.context
        data = struct.pack('<QQiiiIQQ', emitter, actor, 1, -1, 0, REASON,
                           game.BASE + 0x4E371D0, game.BASE + 0x4B4D578)
        game.write_verified(self.control, data, 'Enemy stealth request')
        self.initialized = True
        old = W.DWORD()
        if not K.VirtualProtectEx(game.handle, self.allocation, 4096, 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        if not K.FlushInstructionCache(game.handle, self.allocation, 4096):
            raise C.WinError(C.get_last_error())
        self.patch = b'\xe9' + struct.pack('<i', self.allocation - entry - 5) + b'\x90'
        with self.guard.paused(game, [(entry, entry + 6)]):
            self.guard.code_write(game, entry, PROLOGUE, self.patch)
            self.installed = True

    def update(self, game, enabled):
        if self.owner is not None and self.owner is not game:
            if self.owner.alive():
                raise NotReady('Enemy stealth still belongs to a different game process')
            self.__init__()
        if not enabled:
            self.restore(game)
            return 'Enemies: normal detection'
        context, reasons = emitter_context(game)
        if self.allocation and not self.installed:
            self.restore(game)
            return self.update(game, enabled)
        if not self.allocation:
            if REASON in reasons:
                raise NotReady('Enemy stealth reason is already owned by another helper')
            self.context = context
            self.install(game)
        elif context != self.context:
            if REASON in reasons:
                raise NotReady('The new player already has an independently owned stealth reason')
            with self.guard.paused(game, [(self.allocation, self.allocation + 4096)]):
                if game.unpack(self.control + 24, '<i')[0]:
                    raise NotReady('Enemy stealth is finishing a previous update')
                actor, table, emitter = context
                game.write_verified(self.control, struct.pack('<QQii', emitter, actor, 1, -1), 'Enemy stealth player')
                self.context = context
        game.write_verified(self.control + 16, struct.pack('<i', 1), 'Enemy stealth request')
        requested, applied, busy = game.unpack(self.control + 16, '<iii')
        if game.unpack(self.control + 48, '<i')[0]:
            return 'Enemy stealth pending: perception reason list is full'
        if applied == 1 and REASON not in reasons:
            game.write_verified(self.control + 20, struct.pack('<i', -1), 'Refresh enemy stealth')
            applied = -1
        return ('Blocks new perception detection; scripted fights may still attack.' if applied == 1
                else 'Enemy stealth: resume play to apply')

    def restore(self, game):
        if not self.allocation:
            return
        if self.owner is not game:
            if self.owner is not None and self.owner.alive():
                raise NotReady('Cannot restore enemy stealth through another game process')
            self.__init__()
            return
        entry = self.base + EMITTER_RVA
        if not self.initialized:
            with self.guard.paused(game, [(entry, entry + 6), (self.allocation, self.allocation + 4096)]):
                if game.read(entry, 6) != PROLOGUE:
                    raise NotReady('Incomplete stealth setup has unexpected game code; restart NX2navi')
                if not K.VirtualFreeEx(game.handle, self.allocation, 0, 0x8000):
                    raise C.WinError(C.get_last_error())
                self.__init__()
            return
        game.write_verified(self.control + 16, struct.pack('<i', 0), 'Restore enemy perception')
        requested, applied, busy = game.unpack(self.control + 16, '<iii')
        current, _ = emitter_context(game)
        if current == self.context and (busy or applied == 1):
            raise NotReady('Resume play briefly to restore enemy detection')
        with self.guard.paused(game, [(entry, entry + 6), (self.allocation, self.allocation + 4096)]):
            if game.unpack(self.control + 24, '<i')[0]:
                raise NotReady('Enemy stealth is completing its native update')
            current_code = game.read(entry, 6)
            if current_code == self.patch:
                self.guard.code_write(game, entry, self.patch, PROLOGUE)
            elif current_code != PROLOGUE:
                raise NotReady('Enemy-stealth code changed outside Navi Scout; restore cancelled')
            if not K.VirtualFreeEx(game.handle, self.allocation, 0, 0x8000):
                raise C.WinError(C.get_last_error())
            self.__init__()
