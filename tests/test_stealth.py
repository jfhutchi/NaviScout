import ctypes as C
import hashlib
import struct
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from memory import K
from stealth import EnemyStealth, ModuleEntry, PROLOGUE, EMITTER_RVA, StealthLayout, stealth_stub, select_stealth_layout


class StealthStubTests(unittest.TestCase):
    def test_interrupted_new_layout_cleanup_checks_its_selected_entry(self):
        from stealth import STEALTH_LAYOUTS
        from unittest.mock import Mock
        control = EnemyStealth()
        control.base, control.allocation = 0x1000, 0x9000
        control.layout = STEALTH_LAYOUTS[1]
        entry = control.base + control.layout.emitter_rva
        read = Mock(return_value=PROLOGUE)
        game = SimpleNamespace(read=read, handle=123)
        control.owner = game
        with patch.object(control.guard, 'paused', return_value=nullcontext()), \
             patch.object(K, 'VirtualFreeEx', return_value=1):
            control.restore(game)
        read.assert_called_once_with(entry, 6)

    def test_layout_selection_checks_both_native_functions(self):
        data = {0x1100: b'emitter', 0x1200: b'setter'}
        signatures = tuple((address - 0x1000, len(raw), hashlib.sha256(raw).hexdigest()) for address, raw in data.items())
        layout = StealthLayout(0x100, 0x200, signatures)
        game = SimpleNamespace(read=lambda address, _size: data[address])
        with patch('stealth.STEALTH_LAYOUTS', (layout,)):
            self.assertIs(select_stealth_layout(game, 0x1000, 0x1000), layout)
            data[0x1200] = b'changed'
            with self.assertRaises(ValueError):
                select_stealth_layout(game, 0x1000, 0x1000)

    def test_off_without_an_override_never_touches_game_memory(self):
        EnemyStealth().restore(None)

    def test_failed_installations_remain_recoverable_without_an_orphan_hook(self):
        for failure in ('first_write', 'control_write', 'protect', 'flush', 'detour'):
            with self.subTest(failure=failure):
                memory, freed, writes = {}, [], []
                base, allocation = 0x100000, 0x9000
                entry = base + EMITTER_RVA
                memory.update({entry+i: value for i, value in enumerate(PROLOGUE)})

                def module(_, pointer):
                    item = C.cast(pointer, C.POINTER(ModuleEntry)).contents
                    item.base, item.image_size = base, 0x10000000
                    return 1

                def write(address, raw, _):
                    memory.update({address+i: value for i, value in enumerate(raw)})
                    writes.append(address)
                    if (failure == 'first_write' and len(writes) == 1
                            or failure == 'control_write' and len(writes) == 3):
                        raise OSError('Injected write/verification failure')

                def read(address, size):
                    return bytes(memory[address+i] for i in range(size))

                game = SimpleNamespace(pid=123, BASE=0x7000000000, handle=4, read=read, write_verified=write,
                                       unpack=lambda address, fmt: struct.unpack(fmt, read(address, struct.calcsize(fmt))))
                control = EnemyStealth()
                control.context = (0x2000, 0x3000, 0x4000)
                with patch('stealth.STEALTH_LAYOUTS', (StealthLayout(EMITTER_RVA, 0x4132E0, ()),)), \
                     patch.object(K, 'CreateToolhelp32Snapshot', return_value=50), \
                     patch.object(K, 'Module32FirstW', side_effect=module), \
                     patch.object(K, 'CloseHandle', return_value=1), \
                     patch.object(K, 'VirtualAllocEx', return_value=allocation), \
                     patch.object(K, 'VirtualProtectEx', return_value=failure != 'protect'), \
                     patch.object(K, 'FlushInstructionCache', return_value=failure != 'flush'), \
                     patch.object(K, 'VirtualFreeEx', side_effect=lambda *args: freed.append(args[1]) or 1), \
                     patch.object(control.guard, 'paused', side_effect=lambda *_: nullcontext()), \
                     patch.object(control.guard, 'code_write', side_effect=OSError('Injected detour failure')), \
                     patch('stealth.emitter_context', return_value=(control.context, [])):
                    with self.assertRaises(OSError):
                        control.install(game)
                    self.assertFalse(control.installed)
                    control.restore(game)
                    self.assertEqual(freed, [allocation])
                    self.assertEqual(read(entry, 6), PROLOGUE)
                    self.assertIsNone(control.allocation)

    def test_off_waits_for_native_cleanup_before_freeing_code(self):
        control = EnemyStealth()
        game = SimpleNamespace(write_verified=lambda *_: None, unpack=lambda *_: (0, 1, 0))
        control.owner, control.allocation, control.base = game, 0x9000, 0x1000
        control.initialized = True
        control.control, control.context = 0xA000, (1, 2, 3)
        with patch('stealth.emitter_context', return_value=(control.context, [])), \
             patch.object(K, 'VirtualFreeEx') as free:
            from memory import NotReady
            with self.assertRaisesRegex(NotReady, 'Resume play'):
                control.restore(game)
            free.assert_not_called()

    def test_native_setter_runs_with_own_reason_and_preserves_the_cpu(self):
        callback_type = C.CFUNCTYPE(None, C.c_void_p)
        actor, table, emitter, manager, root = (C.create_string_buffer(n) for n in (0x300, 0x400, 0x100, 0x500, 8))
        control = C.create_string_buffer(64)
        a, t, e, m = map(C.addressof, (actor, table, emitter, manager))
        vt = 0x7004B4D578
        struct.pack_into('<Q', actor, 0x270, t)
        struct.pack_into('<Q', table, 0x328, e)
        struct.pack_into('<Q', emitter, 0, vt)
        struct.pack_into('<Q', emitter, 0x18, a)
        struct.pack_into('<iii', emitter, 0x40, 8, 0, 0)
        struct.pack_into('<Q', manager, 0x480, a)
        struct.pack_into('<Q', root, 0, m)
        struct.pack_into('<QQiiiIQQ', control, 0, e, a, 1, -1, 0, 0x4E534354, C.addressof(root), vt)
        calls, passed = [], []

        def setter(cpu):
            calls.append(struct.unpack('<3Q', C.string_at(cpu, 24)))
            C.memset(cpu, 0xCC, 1024)

        setter_callback = callback_type(setter)
        original_callback = callback_type(lambda cpu: passed.append(C.string_at(cpu, 1024)))
        code = stealth_stub(C.addressof(control), C.cast(setter_callback, C.c_void_p).value,
                            C.cast(original_callback, C.c_void_p).value)
        process = C.c_void_p(-1)
        address = K.VirtualAllocEx(process, None, 4096, 0x3000, 0x40)
        self.assertTrue(address)
        try:
            C.memmove(address, code, len(code))
            K.FlushInstructionCache(process, address, len(code))
            function = callback_type(address)
            initial = bytearray([0x35] * 1024)
            struct.pack_into('<Q', initial, 0, e)
            cpu = C.create_string_buffer(bytes(initial))
            function(C.addressof(cpu))
            self.assertEqual(calls, [(e + 0x20, C.addressof(control) + 28, 0)])
            self.assertEqual(passed[-1], initial)
            self.assertEqual(struct.unpack_from('<i', control, 20)[0], 1)
            self.assertEqual(struct.unpack_from('<i', control, 24)[0], 0)
            function(C.addressof(cpu))
            self.assertEqual(len(calls), 1)
            struct.pack_into('<i', control, 16, 0)
            function(C.addressof(cpu))
            self.assertEqual(calls[-1], (e + 0x20, C.addressof(control) + 28, 1))
            self.assertEqual(passed[-1], initial)
            self.assertEqual(struct.unpack_from('<i', control, 20)[0], 0)
            struct.pack_into('<i', control, 16, 1)
            struct.pack_into('<iii', emitter, 0x40, 8, 0, 8)
            function(C.addressof(cpu))
            self.assertEqual(len(calls), 2)
            self.assertEqual(struct.unpack_from('<i', control, 48)[0], 1)
            self.assertEqual(struct.unpack_from('<i', control, 24)[0], 0)
            self.assertEqual(passed[-1], initial)
            struct.pack_into('<ii', control, 16, 0, 1)
            function(C.addressof(cpu))
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[-1][2], 1)
            self.assertEqual(struct.unpack_from('<iii', emitter, 0x40), (8, 0, 8))
            struct.pack_into('<i', control, 16, 1)
            struct.pack_into('<iii', emitter, 0x40, 8, 0, 0)
            struct.pack_into('<Q', manager, 0x480, 0)
            function(C.addressof(cpu))
            self.assertEqual(len(calls), 3)
        finally:
            K.VirtualFreeEx(process, address, 0, 0x8000)


if __name__ == '__main__':
    unittest.main()
