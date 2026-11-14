import ctypes as C
import struct
import unittest

import stealth
from memory import K


class EnemyFilterTests(unittest.TestCase):
    def test_only_enemy_receivers_lose_current_players_signal(self):
        self.assertTrue(hasattr(stealth, 'enemy_filter_stub'),
                        'Stealth needs an enemy-only filter instead of disabling Link globally')
        buffers = []

        def block(size):
            value = C.create_string_buffer(size)
            buffers.append(value)
            return C.addressof(value)

        def q(address, value):
            C.c_uint64.from_address(address).value = value

        def i(address, value):
            C.c_uint32.from_address(address).value = value

        player, receiver, other = block(0x300), block(0x300), block(0x300)
        player_table, receiver_table = block(0x400), block(0x400)
        emitter, sdk, affiliation = block(0x100), block(0x240), block(0x40)
        manager, root, context = block(0x500), block(8), block(0xC0)
        result, cpu, control = block(0xD8), block(1024), block(64)
        q(root, manager)
        q(manager + 0x480, player)
        q(player + 0x270, player_table)
        q(player_table + 0x328, emitter)
        q(emitter, 0x7004B4D578)
        q(emitter + 0x18, player)
        q(emitter + 0x30, sdk)
        q(receiver + 0x270, receiver_table)
        q(receiver_table + 0x130, affiliation)
        q(affiliation + 0x18, receiver)
        i(affiliation + 0x28, 1)
        q(context + 0xB0, receiver)
        q(result + 0xD0, sdk)
        q(control, root)
        q(control + 8, 0x7004B4D578)
        calls = []
        callback_type = C.CFUNCTYPE(None, C.c_void_p)
        callback = callback_type(lambda pointer: calls.append(C.string_at(pointer, 1024)))
        process = C.c_void_p(-1)
        address = K.VirtualAllocEx(process, None, 4096, 0x3000, 0x40)
        self.assertTrue(address)
        try:
            for copied in (False, True):
                with self.subTest(copied=copied):
                    code = stealth.enemy_filter_stub(control, C.cast(callback, C.c_void_p).value, copied)
                    C.memmove(address, code, len(code))
                    self.assertTrue(K.FlushInstructionCache(process, address, len(code)))
                    function = callback_type(address)

                    def signal(blocked, source=sdk, caller=0x70000DA5CC):
                        original = bytearray([0x35] * 1024)
                        struct.pack_into('<QQQ', original, 0, 123, result if copied else context, source)
                        struct.pack_into('<Q', original, 19 * 8, context)
                        struct.pack_into('<Q', original, 30 * 8, caller)
                        q(result + 0xD0, source)
                        C.memmove(cpu, bytes(original), 1024)
                        before = len(calls)
                        function(cpu)
                        expected = bytearray(original)
                        if blocked:
                            struct.pack_into('<Q', expected, 0, 0)
                        self.assertEqual(C.string_at(cpu, 1024), bytes(expected))
                        self.assertEqual(len(calls), before + (not blocked))
                        if not blocked:
                            self.assertEqual(calls[-1], bytes(original))

                    signal(True)
                    signal(True, caller=0x70000DA6C8)
                    for group in (0, 2, 3, 4, 5):
                        i(affiliation + 0x28, group)
                        signal(False)  # Includes Navi, NPCs and the player.
                    i(affiliation + 0x28, 1)
                    signal(False, source=other)
                    if copied:
                        signal(False, caller=0x7000000000)
                    q(affiliation + 0x18, other)
                    signal(False)
                    q(affiliation + 0x18, receiver)
                    q(context + 0xB0, player)
                    signal(False)
                    q(context + 0xB0, receiver)
                    q(emitter + 0x18, other)
                    signal(False)
                    q(emitter + 0x18, player)
                    q(emitter, 0)
                    signal(False)
                    q(emitter, 0x7004B4D578)
                    q(manager + 0x480, 0)
                    signal(False)
                    q(manager + 0x480, player)
            self.assertEqual(C.string_at(emitter + 0x40, 12), bytes(12))
        finally:
            self.assertTrue(K.VirtualFreeEx(process, address, 0, 0x8000))
