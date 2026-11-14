import ctypes as C
import hashlib
import struct
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from memory import K, NotReady
from running import ModuleEntry
from stealth import EnemyStealth, PROLOGUES, StealthLayout, select_stealth_layout


class StealthTests(unittest.TestCase):
    def fixture(self):
        base, allocation = 0x100000, 0x9000
        data = {base + 0x100: PROLOGUES[0], base + 0x200: PROLOGUES[1], base + 0x300: b'collector'}
        signatures = tuple((address-base, len(raw), hashlib.sha256(raw).hexdigest()) for address, raw in data.items())
        layout = StealthLayout(0x100, 0x200, signatures)
        memory = {address + i: value for address, raw in data.items() for i, value in enumerate(raw)}
        writes, freed = [], []

        def read(address, size):
            return bytes(memory[address+i] for i in range(size))

        def write(address, raw, _):
            memory.update({address+i: value for i, value in enumerate(raw)})
            writes.append(address)

        def module(_, pointer):
            item = C.cast(pointer, C.POINTER(ModuleEntry)).contents
            item.base, item.image_size = base, 0x100000
            return 1

        def code_write(game, address, expected, raw):
            self.assertEqual(read(address, len(expected)), expected)
            write(address, raw, 'code')

        game = SimpleNamespace(pid=123, BASE=0x7000000000, handle=4, read=read, write_verified=write)
        control = EnemyStealth()
        self.addCleanup(patch.stopall)
        patch('stealth.STEALTH_LAYOUTS', (layout,)).start()
        patch.object(K, 'CreateToolhelp32Snapshot', return_value=50).start()
        patch.object(K, 'Module32FirstW', side_effect=module).start()
        patch.object(K, 'CloseHandle', return_value=1).start()
        patch.object(K, 'VirtualAllocEx', return_value=allocation).start()
        patch.object(K, 'VirtualProtectEx', return_value=1).start()
        patch.object(K, 'FlushInstructionCache', return_value=1).start()
        patch.object(K, 'VirtualFreeEx', side_effect=lambda *args: freed.append(args[1]) or 1).start()
        patch.object(control.guard, 'paused', side_effect=lambda *_: nullcontext()).start()
        patch.object(control.guard, 'code_write', side_effect=code_write).start()
        return control, game, layout, memory, writes, freed

    def test_layout_checks_both_filters_and_their_calling_collector(self):
        control, game, layout, memory, _, _ = self.fixture()
        self.assertIs(select_stealth_layout(game, 0x100000, 0x100000), layout)
        for rva, size, _ in layout.signatures:
            previous = memory[0x100000+rva]
            memory[0x100000+rva] ^= 1
            with self.assertRaises(ValueError):
                select_stealth_layout(game, 0x100000, 0x100000)
            memory[0x100000+rva] = previous
        with self.assertRaises(ValueError):
            select_stealth_layout(game, 0x100000, 0x150)

    def test_both_filters_install_restore_and_never_write_to_an_actor(self):
        control, game, layout, _, writes, freed = self.fixture()
        self.assertIn('Enemy-only', control.update(game, True))
        self.assertTrue(control.installed)
        original_entries = [(entry, original) for entry, original, _ in control.patches]
        self.assertEqual(len(original_entries), 2)
        self.assertEqual(control.update(game, False), 'Enemies: normal detection')
        self.assertEqual(freed, [0x9000])
        for entry, original in original_entries:
            self.assertEqual(game.read(entry, len(original)), original)
        self.assertTrue(all(0x9000 <= address < 0xB000 or address in (0x100100, 0x100200) for address in writes))
        self.assertIsNone(control.allocation)

    def test_interrupted_installations_restore_both_sites(self):
        for failure in ('first_write', 'protect', 'flush', 'first_patch', 'second_patch'):
            with self.subTest(failure=failure):
                control, game, layout, _, _, freed = self.fixture()
                if failure == 'first_write':
                    original_write = game.write_verified
                    def fail_write(*args):
                        original_write(*args)
                        raise OSError('Injected write failure')
                    game.write_verified = fail_write
                elif failure in ('protect', 'flush'):
                    api = 'VirtualProtectEx' if failure == 'protect' else 'FlushInstructionCache'
                    patch.object(K, api, return_value=0).start()
                else:
                    original_patch = control.guard.code_write.side_effect
                    count = 0
                    def fail_patch(*args):
                        nonlocal count
                        count += 1
                        if count == (1 if failure == 'first_patch' else 2):
                            raise OSError('Injected detour failure')
                        original_patch(*args)
                    control.guard.code_write.side_effect = fail_patch
                with self.assertRaises(OSError):
                    control.install(game)
                control.restore(game)
                self.assertEqual(freed, [0x9000])
                for rva, original in zip((layout.candidate_rva, layout.copy_rva), PROLOGUES):
                    self.assertEqual(game.read(0x100000+rva, len(original)), original)
                patch.stopall()

    def test_restore_waits_for_every_filter_thread_to_leave(self):
        control, game, _, _, _, freed = self.fixture()
        control.install(game)
        control.guard.paused.side_effect = NotReady('Filter is executing')
        with self.assertRaises(NotReady):
            control.restore(game)
        self.assertFalse(freed)

    def test_foreign_code_prevents_freeing_a_referenced_helper(self):
        control, game, _, memory, _, freed = self.fixture()
        control.install(game)
        memory[0x100200] = 0xCC
        with self.assertRaises(NotReady):
            control.restore(game)
        self.assertFalse(freed)
        self.assertEqual(game.read(0x100100, 6), control.patches[0][2])

    def test_off_without_an_override_never_touches_game_memory(self):
        self.assertEqual(EnemyStealth().update(None, False), 'Enemies: normal detection')
