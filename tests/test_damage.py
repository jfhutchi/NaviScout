import ctypes as C
import hashlib
from contextlib import nullcontext
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from damage import EnemyDamage, damage_stub, PROLOGUE, FUNCTION_RVA
from memory import K, NotReady


class DamageTests(unittest.TestCase):
    def test_native_filter_covers_owned_attacks_and_preserves_cpu(self):
        buffers = []

        def block(size):
            result = C.create_string_buffer(size)
            buffers.append(result)
            return C.addressof(result)

        def q(address, value):
            C.c_uint64.from_address(address).value = value

        def i(address, value):
            C.c_int32.from_address(address).value = value

        player, enemy, source = block(0x400), block(0x400), block(0x400)
        target_table, source_table = block(0x400), block(0x400)
        life, affiliation, creator = block(0x300), block(0x50), block(0x60)
        manager, root, source_slot, creator_slot = block(0x500), block(8), block(0x60), block(0x60)
        info, cpu, control = block(0x100), block(1024), block(64)
        q(root, manager)
        q(manager + 0x480, player)
        q(control + 24, root)
        q(enemy + 0x270, target_table)
        q(target_table + 0x2B8, life)
        q(target_table + 0x130, affiliation)
        q(life + 0x18, enemy)
        q(life + 0x218, enemy)
        q(affiliation + 0x18, enemy)
        i(affiliation + 0x28, 1)
        q(source + 0x270, source_table)
        q(source_table + 0x1D8, creator)
        q(creator + 0x18, source)
        q(creator + 0x28, creator_slot)
        i(creator + 0x30, 7)
        q(creator_slot + 0x40, player)
        i(creator_slot + 0x48, 7)
        q(info + 0x28, source_slot)
        i(info + 0x30, 42)
        i(source_slot + 0x48, 42)
        q(source_slot + 0x40, player)
        observed = []
        callback_type = C.CFUNCTYPE(None, C.c_void_p)
        callback = callback_type(lambda pointer: observed.append(C.string_at(pointer, 1024)))
        process = C.c_void_p(-1)
        address = K.VirtualAllocEx(process, None, 4096, 0x3000, 0x40)
        self.assertTrue(address)
        try:
            code = damage_stub(control, C.cast(callback, C.c_void_p).value)
            C.memmove(address, code, len(code))
            self.assertTrue(K.FlushInstructionCache(process, address, len(code)))
            function = callback_type(address)

            def hit(value=4):
                layout = bytearray([0x35] * 1024)
                struct.pack_into('<QQQ', layout, 0, life + 0x210, 0, info)
                C.memmove(cpu, bytes(layout), 1024)
                i(info, value)
                function(cpu)
                self.assertEqual(observed[-1], bytes(layout))
                self.assertEqual(C.string_at(cpu, 1024), bytes(layout))
                return C.c_int32.from_address(info).value

            self.assertEqual(hit(), 8)
            q(source_slot + 0x40, source)
            self.assertEqual(hit(7), 14)
            self.assertEqual(C.c_uint64.from_address(control + 8).value, 2)
            self.assertEqual(struct.unpack('<ii', C.string_at(control + 16, 8)), (7, 14))
            for value in (0, -1, 0x40000000):
                self.assertEqual(hit(value), value)
            i(affiliation + 0x28, 2)
            self.assertEqual(hit(), 4)
            i(affiliation + 0x28, 1)
            i(source_slot + 0x48, 41)
            self.assertEqual(hit(), 4)
            i(source_slot + 0x48, 42)
            i(creator_slot + 0x48, 8)
            self.assertEqual(hit(), 4)
            i(creator_slot + 0x48, 7)
            q(creator_slot + 0x40, source)  # A cyclic creator chain must terminate.
            self.assertEqual(hit(), 4)
            q(creator_slot + 0x40, player)
            i(source + 0x2C, 8)
            self.assertEqual(hit(), 4)
            i(source + 0x2C, 0)
            q(creator + 0x18, enemy)
            self.assertEqual(hit(), 4)
            q(creator + 0x18, source)
            q(life + 0x18, player)
            self.assertEqual(hit(), 4)
            q(life + 0x18, enemy)
            q(manager + 0x480, enemy)
            self.assertEqual(hit(), 4)  # Never amplify damage to the player.
            q(manager + 0x480, 0)
            self.assertEqual(hit(), 4)
        finally:
            self.assertTrue(K.VirtualFreeEx(process, address, 0, 0x8000))

    def test_off_does_not_access_a_process(self):
        EnemyDamage().update(None, False)

    def test_interrupted_installations_leave_no_orphan_detour(self):
        from running import ModuleEntry
        for failure in ('first_write', 'control_write', 'protect', 'flush', 'detour'):
            with self.subTest(failure=failure):
                memory, writes, freed = {}, [], []
                base, allocation = 0x100000, 0x9000
                entry = base + FUNCTION_RVA
                memory.update({entry + i: value for i, value in enumerate(PROLOGUE)})

                def module(_, pointer):
                    item = C.cast(pointer, C.POINTER(ModuleEntry)).contents
                    item.base, item.image_size = base, 0x100000
                    return 1

                def write(address, raw, _):
                    memory.update({address + i: value for i, value in enumerate(raw)})
                    writes.append(address)
                    if (failure == 'first_write' and len(writes) == 1
                            or failure == 'control_write' and len(writes) == 3):
                        raise OSError('Injected write/verification failure')

                def read(address, size):
                    return bytes(memory[address + i] for i in range(size))

                game = SimpleNamespace(pid=123, BASE=0x7000000000, handle=4, read=read, write_verified=write)
                control = EnemyDamage()
                with patch('damage.FUNCTION_SIZE', len(PROLOGUE)), \
                     patch('damage.FUNCTION_SHA256', hashlib.sha256(PROLOGUE).hexdigest()), \
                     patch.object(K, 'CreateToolhelp32Snapshot', return_value=50), \
                     patch.object(K, 'Module32FirstW', side_effect=module), \
                     patch.object(K, 'CloseHandle', return_value=1), \
                     patch.object(K, 'VirtualAllocEx', return_value=allocation), \
                     patch.object(K, 'VirtualProtectEx', return_value=failure != 'protect'), \
                     patch.object(K, 'FlushInstructionCache', return_value=failure != 'flush'), \
                     patch.object(K, 'VirtualFreeEx', side_effect=lambda *args: freed.append(args[1]) or 1), \
                     patch.object(control.guard, 'paused', side_effect=lambda *_: nullcontext()), \
                     patch.object(control.guard, 'code_write', side_effect=OSError('Injected detour failure')):
                    with self.assertRaises(OSError):
                        control.install(game)
                    control.restore(game)
                self.assertEqual(freed, [allocation])
                self.assertEqual(read(entry, 6), PROLOGUE)
                self.assertIsNone(control.allocation)

    def test_restore_does_not_free_code_while_a_thread_is_executing_it(self):
        control = EnemyDamage()
        control.base, control.allocation, control.patch = 0x1000, 0x9000, b'patch!'
        game = SimpleNamespace(handle=123)
        control.owner = game
        with patch.object(control.guard, 'paused', side_effect=NotReady('Damage callback is busy')), \
             patch.object(K, 'VirtualFreeEx') as free:
            with self.assertRaises(NotReady):
                control.restore(game)
            free.assert_not_called()

    def test_restore_reverts_detour_before_freeing_memory(self):
        control = EnemyDamage()
        control.base, control.allocation, control.patch = 0x1000, 0x9000, b'patch!'
        game = SimpleNamespace(read=lambda *_: control.patch, handle=123)
        control.owner = game
        calls = []
        with patch.object(control.guard, 'paused', return_value=nullcontext()), \
             patch.object(control.guard, 'code_write', side_effect=lambda *args: calls.append(args[1:])), \
             patch.object(K, 'VirtualFreeEx', side_effect=lambda *_: calls.append('free') or 1):
            control.restore(game)
        self.assertEqual(calls, [(0x1000 + FUNCTION_RVA, b'patch!', PROLOGUE), 'free'])
        self.assertIsNone(control.allocation)

    def test_foreign_detour_is_never_overwritten_or_freed(self):
        control = EnemyDamage()
        control.base, control.allocation, control.patch = 0x1000, 0x9000, b'patch!'
        game = SimpleNamespace(read=lambda *_: b'other!', handle=123)
        control.owner = game
        with patch.object(control.guard, 'paused', return_value=nullcontext()), patch.object(K, 'VirtualFreeEx') as free:
            with self.assertRaises(NotReady):
                control.restore(game)
            free.assert_not_called()


if __name__ == '__main__':
    unittest.main()
