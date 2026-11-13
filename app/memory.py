"""Validated access to the installed NX2navi game's guest data on Windows."""
import ctypes as C
from ctypes import wintypes as W
import math
from pathlib import Path
import struct

from core import RESOURCES, murmur3, refill_target

OWNERSHIP_FLAGS = {'bombchus': (0x5AB49C8E, 8852), 'magic_beans': (0x6D39C600, 8896),
                   'scrub_seeds': (0xCFBB16F6, 8934), 'magic': (0xB1309073, 8888)}

# GroundSpeedScale affects rolling; normal walking uses animation root movement.
MOVEMENT_PARAMETERS = {'roll': (0x2A0, 0x561), 'jump': (0x334, 0x563),
                       'swim': (0x4F4, 0x5BC), 'swim_heavy': (0x4EC, 0x5BD),
                       'swim_dash': (0x4C4, 0x5BE), 'swim_dash_heavy': (0x4BC, 0x5BF)}
MOVEMENT_LIMITS = {name: 32 if name.startswith('swim') else 8 for name in MOVEMENT_PARAMETERS}

K = C.WinDLL('kernel32', use_last_error=True)
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.CloseHandle.argtypes = [W.HANDLE]
K.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
K.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
K.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
K.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
K.CreateToolhelp32Snapshot.restype = W.HANDLE
K.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]


class ProcessEntry(C.Structure):
    _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD), ('heap', C.c_size_t),
                ('module', W.DWORD), ('threads', W.DWORD), ('parent', W.DWORD),
                ('priority', W.LONG), ('flags', W.DWORD), ('exe', W.WCHAR * 260)]


K.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
K.Process32NextW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]


class NotReady(Exception):
    """The game has no loaded player or is transitioning between scenes."""


class DifferentInstallation(ValueError):
    """A process with the same name belongs to another installation."""


class StaleParameter(NotReady):
    """A cached parameter resource was freed or replaced; never write through it."""


class Game:
    BASE = 0x7000000000

    def __init__(self, pid, executable):
        self.pid = pid
        self.handle = K.OpenProcess(0x438, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        try:
            path, size = C.create_unicode_buffer(32768), W.DWORD(32768)
            if not K.QueryFullProcessImageNameW(self.handle, 0, path, C.byref(size)):
                raise C.WinError(C.get_last_error())
            if Path(path.value).resolve() != Path(executable).resolve():
                raise DifferentInstallation('Refusing a process outside this NX2navi installation')
            header = (Path(executable).parent / 'exefs/main').read_bytes()[:0x48]
            if header[:4] != b'NSO0' or header[0x40:0x48].hex().upper() != 'E0F3CCFAF50065AE':
                raise ValueError('This helper supports game build E0F3CCFAF50065AE only')
            self.executable = Path(executable)
        except (OSError, ValueError):
            self.close()
            raise

    @classmethod
    def find(cls, executable):
        snapshot = K.CreateToolhelp32Snapshot(2, 0)
        if snapshot == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        try:
            entry = ProcessEntry()
            entry.size = C.sizeof(entry)
            found = K.Process32FirstW(snapshot, C.byref(entry))
            while found:
                if entry.exe.lower() == Path(executable).name.lower():
                    try:
                        return cls(entry.pid, executable)
                    except DifferentInstallation:
                        pass
                found = K.Process32NextW(snapshot, C.byref(entry))
        finally:
            K.CloseHandle(snapshot)
        return None

    def close(self):
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None

    def alive(self):
        code = W.DWORD()
        return bool(self.handle and K.GetExitCodeProcess(self.handle, C.byref(code)) and code.value == 259)

    def read(self, address, size):
        data, done = C.create_string_buffer(size), C.c_size_t()
        if not address or not K.ReadProcessMemory(self.handle, address, data, size, C.byref(done)) or done.value != size:
            raise NotReady(f'Game data unavailable at {address:#x}')
        return data.raw

    def unpack(self, address, fmt):
        return struct.unpack(fmt, self.read(address, struct.calcsize(fmt)))

    def pointer(self, address):
        return self.unpack(address, '<Q')[0]

    def manager(self):
        manager = self.pointer(self.pointer(self.BASE + 0x4C7E180))
        if not manager:
            raise NotReady('Load a save to activate the helper')
        return manager

    def entry(self, manager, key, kind, stride, expected=None):
        section = manager + kind * 0x60
        count = self.unpack(section + 0x10, '<I')[0]
        entries, table = self.unpack(section + 0x18, '<QQ')
        slots = self.unpack(section + 0x2C, '<I')[0]
        if not count or slots != count * 2 or count > 20000:
            raise NotReady('GameData table layout does not match this game build')
        if kind == 2 and count != 1259:
            raise NotReady('Integer table has an unexpected size')
        if kind == 4 and count != 89:
            raise NotReady('Float table has an unexpected size')
        slot = key % slots
        for _ in range(slots):
            hashed, index = self.unpack(table + slot * 8, '<II')
            if not hashed:
                raise NotReady(f'GameData key {key:08X} is absent')
            if hashed == key:
                if index >= count or (expected is not None and index != expected):
                    raise NotReady('GameData key/index validation failed')
                address = entries + index * stride
                vtable = self.pointer(address)
                if not self.BASE <= vtable < self.BASE + 0x4EA0000:
                    raise NotReady('GameData entry vtable validation failed')
                return address
            slot = (slot + 1) % slots
        raise NotReady('GameData table lookup failed')

    def text(self, manager, name):
        entry = self.entry(manager, murmur3(name), 16, 0x108)
        return self.read(self.pointer(entry + 0x68), 64).split(b'\0', 1)[0].decode('utf-8')

    def boolean(self, manager, key, expected=None):
        return self.read(self.entry(manager, key, 0, 24, expected) + 22, 1)[0] != 0

    def state(self):
        manager = self.manager()
        actor = self.pointer(self.pointer(self.BASE + 0x4E371D0) + 0x480)
        if not actor or self.read(self.pointer(actor + 0x20), 7) != b'Player\0':
            raise NotReady('Load a save to activate the radar')
        xyz = self.unpack(actor + 0x31C, '<fff')
        if not all(math.isfinite(x) and abs(x) < 100000 for x in xyz):
            raise NotReady('Player position is not valid')
        area = self.text(manager, 'Sequence_CurrentBanc')
        if not area:
            raise NotReady('Waiting for the current area')
        for key in (0xF5DEEF0A, 0x9A9506E7, 0xF8633C7F, 0xF96989B6, 0xE19DFDD6):
            if self.boolean(manager, key):
                raise NotReady('Scene transition: refills paused')
        return manager, area, xyz

    def camera_direction(self):
        # The first scene view's look-at camera stores its position and target as six doubles.
        views = self.pointer(self.pointer(self.BASE + 0x4C7E888))
        camera = self.pointer(views + 0x248)
        if self.pointer(camera) != self.BASE + 0x4C5DE98:
            raise NotReady('Scene camera layout is not available')
        look = self.pointer(camera + 8)
        vtable = self.pointer(look)
        if not self.BASE <= vtable < self.BASE + 0x4EA0000:
            raise NotReady('Scene camera validation failed')
        values = self.unpack(look + 0x60, '<6d')
        if not all(math.isfinite(v) and abs(v) < 100000 for v in values):
            raise NotReady('Scene camera vectors are invalid')
        fx, fz = values[3] - values[0], values[5] - values[2]
        length = math.hypot(fx, fz)
        if not 1e-4 < length < 10000:
            raise NotReady('Scene camera is pointing vertically or is not ready')
        return fx / length, fz / length

    def resources(self, manager, refill=()):
        result = {}
        for name, (key, index, cap_key, cap_index, caps) in RESOURCES.items():
            target = self.entry(manager, key, 2, 40, index) + 28
            cap_address = self.entry(manager, cap_key, 2, 40, cap_index) + 28 if cap_key is not None else None
            value = self.unpack(target, '<i')[0]
            cap = self.unpack(cap_address, '<i')[0] if cap_address is not None else caps[0]
            ownership = OWNERSHIP_FLAGS.get(name)
            owned = not ownership or self.boolean(manager, *ownership)
            active_reader = (self.health_target if name == 'health' else
                             self.magic_target if name == 'magic' and owned else None)
            active_target = active_reader(cap) if active_reader is not None else None
            if active_target is not None:
                value = self.unpack(active_target, '<i')[0]
            wanted = refill_target(name, value, cap) if owned else None
            if (name in refill and wanted is not None and value != wanted
                    and not (name == 'health' and value == 0)):
                if self.manager() != manager or (cap_address is not None and self.unpack(cap_address, '<i')[0] != cap):
                    raise NotReady('Save changed during refill: write cancelled')
                if ownership and not self.boolean(manager, *ownership):
                    raise NotReady(f'{name.replace("_", " ").title()} ownership changed during refill: write cancelled')
                if active_target is not None:
                    if (active_reader(cap) != active_target
                            or (name == 'health' and self.unpack(active_target, '<i')[0] <= 0)):
                        raise NotReady(f'Player changed during {name} refill: write cancelled')
                    self.write_verified(active_target, struct.pack('<i', wanted), f'active {name}')
                raw = struct.pack('<ii', wanted, wanted)
                self.write_verified(target, raw, name)
                value = wanted
            result[name] = dict(current=value, capacity=cap, unlocked=wanted is not None)
        return result

    def write_verified(self, target, raw, name):
        done = C.c_size_t()
        if not K.WriteProcessMemory(self.handle, target, raw, len(raw), C.byref(done)) or done.value != len(raw):
            raise OSError(f'Could not refill {name}: Windows error {C.get_last_error()}')
        if self.read(target, len(raw)) != raw:
            raise OSError(f'Read-back verification failed for {name}')

    def health_target(self, capacity):
        # Life's bound integer publishes its cached value back to PlayerStatus each frame.
        actor = self.pointer(self.pointer(self.BASE + 0x4E371D0) + 0x480)
        if not actor or self.read(self.pointer(actor + 0x20), 7) != b'Player\0':
            raise NotReady('Active health player is not available')
        component = self.pointer(self.pointer(actor + 0x270) + 0x198)
        if self.pointer(component) != self.BASE + 0x4B48300 or self.pointer(component + 0x18) != actor:
            raise NotReady('Active health component validation failed')
        life = self.pointer(component + 0x40)
        if self.pointer(life + 0x50) != self.BASE + 0x4B486A0 or self.pointer(life + 0x58) != actor:
            raise NotReady('Active health binding owner validation failed')
        current_vtable, current, current_hash, max_vtable, maximum, max_hash = self.unpack(life + 0x60, '<QiIQiI')
        if (current_vtable != self.BASE + 0x4B63438 or max_vtable != current_vtable
                or current_hash != 0x31AB5580 or max_hash != 0xFBE01DA1
                or maximum != capacity or not 0 <= current <= maximum):
            raise NotReady('Active health binding/capacity validation failed')
        return life + 0x68

    def magic_target(self, capacity):
        # Casting reads this Player binding; each frame it republishes MP to GameData.
        actor = self.pointer(self.pointer(self.BASE + 0x4E371D0) + 0x480)
        if not actor or self.read(self.pointer(actor + 0x20), 7) != b'Player\0':
            raise NotReady('Active magic player is not available')
        component = self.pointer(self.pointer(actor + 0x270) + 0x358)
        if self.pointer(component) != self.BASE + 0x4B4DFC0 or self.pointer(component + 0x18) != actor:
            raise NotReady('Active magic component validation failed')
        binding = component + 0x1B78
        if (self.pointer(binding) != self.BASE + 0x4B633F0 or self.pointer(binding + 8) != actor
                or self.pointer(binding + 0x20) != self.BASE + 0x4B648C8):
            raise NotReady('Active magic binding owner validation failed')
        maximum, current_hash, max_hash, auxiliary_hash, current = self.unpack(binding + 0x34, '<iIIIi')
        # A freshly loaded Player can leave the bound maximum cache at zero.
        # GameData's validated owned meter remains the limit used for every refill.
        if (current_hash != 0x76B18200 or max_hash != 0x12D63A97 or auxiliary_hash != 0x3AFA3349
                or maximum not in (0, capacity) or capacity not in (240, 480) or not 0 <= current <= capacity):
            raise NotReady('Active magic binding/capacity validation failed')
        return binding + 0x44

    def player_parameter_context(self):
        actor = self.pointer(self.pointer(self.BASE + 0x4E371D0) + 0x480)
        if not actor or self.read(self.pointer(actor + 0x20), 7) != b'Player\0':
            raise NotReady('Link is not available for movement controls')
        table = self.pointer(actor + 0x270)
        component = self.pointer(table + 0x358)
        if self.pointer(component) != self.BASE + 0x4B4DFC0 or self.pointer(component + 0x18) != actor:
            raise NotReady('Link movement component validation failed')
        blackboard = self.pointer(table + 0xA8)
        if self.pointer(blackboard) != self.BASE + 0x4C60D70:
            raise NotReady('Link parameter table validation failed')
        count = self.unpack(blackboard + 0x30, '<I')[0]
        entries = self.pointer(blackboard + 0x38)
        if not 1 <= count <= 128:
            raise NotReady('Link parameter table size is invalid')
        matches = []
        for index in range(count):
            entry = self.pointer(entries + index * 8)
            if self.unpack(entry, '<I')[0] == 0x6B7E094A:
                matches.append(self.pointer(entry + 8))
        if len(matches) != 1 or self.pointer(matches[0]) != self.BASE + 0x4BF9010:
            raise NotReady('Link movement parameter descriptor is invalid')
        descriptor = matches[0]
        parameter = self.pointer(descriptor + 0x150)
        if self.pointer(parameter) != self.BASE + 0x4B6D1A8:
            raise NotReady('Link movement parameter type is invalid')
        return descriptor, parameter, self.read(parameter, 0x28)

    def validate_parameter_context(self, context):
        descriptor, parameter, header = context
        try:
            valid = (self.pointer(descriptor) == self.BASE + 0x4BF9010
                     and self.pointer(descriptor + 0x150) == parameter
                     and self.read(parameter, 0x28) == header
                     and self.pointer(parameter) == self.BASE + 0x4B6D1A8)
        except NotReady as error:
            raise StaleParameter('Link parameter resource was released; write cancelled') from error
        if not valid:
            raise StaleParameter('Link parameter resource changed; write cancelled')
        return parameter

    def parameter_snapshot(self, context, name):
        parameter = self.validate_parameter_context(context)
        offset, flag_offset = MOVEMENT_PARAMETERS[name]
        original = self.read(parameter + offset, 4)
        flag = self.read(parameter + flag_offset, 1)[0]
        seen = set()
        while True:
            if parameter in seen or len(seen) >= 8 or self.pointer(parameter) != self.BASE + 0x4B6D1A8:
                raise NotReady('Link parameter inheritance is invalid')
            seen.add(parameter)
            inherited_flag = self.read(parameter + flag_offset, 1)[0]
            if inherited_flag not in (0, 1):
                raise NotReady('Link parameter override flag is invalid')
            value = self.unpack(parameter + offset, '<f')[0]
            if not math.isfinite(value) or not 0.1 <= value <= MOVEMENT_LIMITS[name]:
                raise NotReady('Link movement parameter is outside the supported range')
            parent = self.pointer(parameter + 0x18)
            if inherited_flag or not self.pointer(parameter + 0x10) or not parent:
                return original, flag, value
            if self.unpack(parent + 0xC, '<I')[0] != self.unpack(parameter + 0x20, '<I')[0]:
                return original, flag, value
            next_parameter = self.pointer(parent)
            if not next_parameter:
                return original, flag, value
            parameter = next_parameter

    def parameter_replace(self, context, name, expected, value, flag):
        offset, flag_offset = MOVEMENT_PARAMETERS[name]
        parameter = self.validate_parameter_context(context)
        if (self.read(parameter + offset, 4), self.read(parameter + flag_offset, 1)[0]) != expected:
            raise NotReady(f'Link {name} setting changed outside Navi Scout; write cancelled')
        number = struct.unpack('<f', value)[0]
        if flag not in (0, 1) or not math.isfinite(number) or not 0.1 <= number <= MOVEMENT_LIMITS[name]:
            raise ValueError('Invalid Link movement override')
        # Clear inheritance override before restoring; enable it only after the new value is ready.
        if not flag:
            self.write_verified(parameter + flag_offset, bytes([flag]), f'{name} inheritance')
        self.write_verified(parameter + offset, value, f'Link {name}')
        if flag:
            self.write_verified(parameter + flag_offset, bytes([flag]), f'{name} inheritance')

    def validate_dive_identity(self, identity):
        actor, ai, table, entry, module, wrapper, module_slot, node_slot, node = identity
        module_count = self.unpack(module + 0x18, '<I')[0]
        module_array = self.pointer(module + 0x20)
        node_count = self.unpack(wrapper + 0x60, '<I')[0]
        node_array = self.pointer(wrapper + 0x68)
        if (not 1 <= module_count <= 512 or not 1 <= node_count <= 512
                or not 0 <= module_slot - module_array < module_count * 8
                or (module_slot - module_array) % 8
                or not 0 <= node_slot - node_array < node_count * 8
                or (node_slot - node_array) % 8):
            return False
        if entry not in self.dive_module_entries(table):
            return False
        return (self.pointer(self.pointer(self.BASE + 0x4E371D0) + 0x480) == actor
                and self.read(self.pointer(actor + 0x20), 7) == b'Player\0'
                and self.pointer(self.pointer(actor + 8) + 0x518) == ai
                and self.pointer(ai) == self.BASE + 0x4B47190 and self.pointer(ai + 0x18) == actor
                and self.pointer(ai + 0x440) == table and self.pointer(entry + 0x18) == module
                and self.pointer(module) == self.BASE + 0x4B479E8 and self.pointer(module + 0x1F0) == actor
                and self.pointer(module_slot) == wrapper and self.pointer(wrapper) == self.BASE + 0x4C26670
                and self.pointer(wrapper + 8) == module and self.pointer(node_slot) == node
                and self.pointer(node) == self.BASE + 0x49CAC00 and self.pointer(node + 8) == wrapper)

    def dive_module_entries(self, table):
        count = self.unpack(table, '<I')[0]
        buckets = self.pointer(table + 8)
        if not 1 <= count <= 64:
            raise NotReady('Dive controller table size is invalid')
        entries = set()
        for bucket in range(count):
            entry = self.pointer(buckets + bucket * 8)
            while entry and entry not in entries:
                if len(entries) >= 256:
                    raise NotReady('Dive controller table exceeds the supported size')
                entries.add(entry)
                entry = self.pointer(entry)
        return entries

    def dive_context(self):
        identity = getattr(self, '_dive_identity', None)
        if identity:
            try:
                valid = self.validate_dive_identity(identity)
            except NotReady:
                valid = False
            if not valid:
                identity = self._dive_identity = None
        if identity is None:
            actor = self.pointer(self.pointer(self.BASE + 0x4E371D0) + 0x480)
            if not actor or self.read(self.pointer(actor + 0x20), 7) != b'Player\0':
                raise NotReady('Waiting for Link to load')
            owner = self.pointer(actor + 8)
            if self.pointer(owner) != self.BASE + 0x4BF78E0:
                raise NotReady('Dive actor layout validation failed')
            ai = self.pointer(owner + 0x518)
            if self.pointer(ai) != self.BASE + 0x4B47190 or self.pointer(ai + 0x18) != actor:
                raise NotReady('Dive controller ownership validation failed')
            table = self.pointer(ai + 0x440)
            if not table:
                return None
            count = self.unpack(table, '<I')[0]
            buckets = self.pointer(table + 8)
            if not 1 <= count <= 64:
                raise NotReady('Dive controller table size is invalid')
            matches, seen = [], set()
            for bucket in range(count):
                entry = self.pointer(buckets + bucket * 8)
                while entry and entry not in seen:
                    if len(seen) >= 256:
                        raise NotReady('Dive controller table exceeds the supported size')
                    seen.add(entry)
                    module = self.pointer(entry + 0x18)
                    if (module and self.pointer(module) == self.BASE + 0x4B479E8
                            and self.pointer(module + 0x1F0) == actor):
                        length = self.unpack(module + 0x18, '<I')[0]
                        slots = self.pointer(module + 0x20)
                        if length > 512:
                            raise NotReady('Dive module size is invalid')
                        for index in range(length):
                            module_slot = slots + index * 8
                            wrapper = self.pointer(module_slot)
                            if not wrapper or self.pointer(wrapper) != self.BASE + 0x4C26670:
                                continue
                            if self.pointer(wrapper + 8) != module:
                                raise NotReady('Dive module ownership changed')
                            size = self.unpack(wrapper + 0x60, '<I')[0]
                            nodes = self.pointer(wrapper + 0x68)
                            if size > 512:
                                raise NotReady('Dive action table size is invalid')
                            for offset in range(size):
                                node_slot = nodes + offset * 8
                                node = self.pointer(node_slot)
                                if node and self.pointer(node) == self.BASE + 0x49CAC00:
                                    candidate = (actor, ai, table, entry, module, wrapper,
                                                 module_slot, node_slot, node)
                                    if not self.validate_dive_identity(candidate):
                                        raise NotReady('Dive action ownership changed')
                                    matches.append(candidate)
                    entry = self.pointer(entry)
            if not matches:
                return None
            if len(matches) != 1:
                raise NotReady('Dive action is ambiguous; writes paused')
            identity = self._dive_identity = matches[0]
        node = identity[-1]
        phase = self.unpack(node + 0x20, '<I')[0]
        depth = self.unpack(node + 0x30, '<f')[0]
        if phase > 7 or not math.isfinite(depth) or not 0 <= depth <= 100000:
            raise NotReady('Dive state or depth is invalid')
        return dict(identity=identity, phase=phase, depth=depth)

    def set_dive_depth(self, context, expected, wanted):
        if not math.isfinite(wanted) or not 3 <= wanted <= 100000:
            raise ValueError('Invalid dive depth override')
        current = self.dive_context()
        if (current is None or current['identity'] != context['identity']
                or current['phase'] != context['phase'] or current['depth'] != expected):
            raise NotReady('Dive changed during update; write cancelled')
        self.write_verified(context['identity'][-1] + 0x30, struct.pack('<f', wanted), 'Link dive limit')

    def minigame_context(self, manager):
        # SetItemForMiniGame assigns these transient PlayerStatus fields; the HUD reads 969.
        item_entry = self.entry(manager, 0x76F85E6D, 6, 56, 68)
        item = self.unpack(item_entry + 28, '<I')[0]
        supported = {2565786591: ('bombchus', 9), 3852308563: ('seeds', 4),
                     1399920009: ('arrows', 30)}
        if item not in supported:
            return None
        name, equipped = supported[item]
        actor = self.pointer(self.pointer(self.BASE + 0x4E371D0) + 0x480)
        if not actor or self.read(self.pointer(actor + 0x20), 7) != b'Player\0':
            raise NotReady('Minigame player is not available')
        component = self.pointer(self.pointer(actor + 0x270) + 0x358)
        if self.pointer(component) != self.BASE + 0x4B4DFC0:
            raise NotReady('Minigame equipment layout does not match this build')
        if not self.read(component + 0x7C1, 1)[0] & 1:
            return None
        if self.unpack(component + 0x7DC, '<i')[0] != equipped:
            raise NotReady('Waiting for minigame equipment setup')
        target = self.entry(manager, 0xC7324B14, 2, 40, 969) + 28
        capacity_address = self.entry(manager, 0x14C1A399, 2, 40, 968) + 28
        value = self.unpack(target, '<i')[0]
        capacity = self.unpack(capacity_address, '<i')[0]
        if not 1 <= capacity <= 100 or not 0 <= value <= capacity:
            raise NotReady('Waiting for a valid minigame ammunition allowance')
        return name, value, capacity, target, actor, component

    def minigame_resources(self, manager, refill=()):
        context = self.minigame_context(manager)
        if context is None:
            return None
        name, value, capacity, target, _, _ = context
        if name in refill and value < capacity:
            if self.manager() != manager or self.minigame_context(manager) != context:
                raise NotReady('Minigame changed during refill: write cancelled')
            raw = struct.pack('<ii', capacity, capacity)
            done = C.c_size_t()
            if not K.WriteProcessMemory(self.handle, target, raw, len(raw), C.byref(done)) or done.value != len(raw):
                raise OSError(f'Could not refill minigame {name}: Windows error {C.get_last_error()}')
            if self.read(target, 8) != raw:
                raise OSError(f'Read-back verification failed for minigame {name}')
            value = capacity
        return dict(resource=name, current=value, capacity=capacity)

    def timer_context(self, manager):
        if not self.boolean(manager, 0xF0312188, 10101):
            return None
        # Quest-stage checks distinguish minigames from timed deliveries sharing this clock.
        games = (('Diving', 0xA4ED3902, 93, (3949112793,)),
                 ("Dampe's race", 0xE73DAF62, 91, (4289256035, 1535793379)),
                 ('Horse race', 0xD601EE20, 100, (4289256035,)),
                 ('Cucco search', 0x3E7D10C0, 94, (4289256035,)),
                 ('Running race', 0xF6EB33A1, 120, (4289256035,)))
        active = []
        for name, key, index, stages in games:
            stage = self.unpack(self.entry(manager, key, 6, 56, index) + 28, '<I')[0]
            if stage in stages:
                active.append((name, stage))
        if len(active) != 1:
            return None
        countdown = self.boolean(manager, 0xDD49184A, 10100)
        target = self.entry(manager, 0x9D350590, 4, 40, 67) + 28
        limit_address = self.entry(manager, 0xFCD114C3, 4, 40, 68) + 28
        value, limit = self.unpack(target, '<f')[0], self.unpack(limit_address, '<f')[0]
        if not all(math.isfinite(x) and 0 <= x <= 3600000 for x in (value, limit)):
            raise NotReady('Minigame timer values are invalid')
        if (countdown and value == 0) or (not countdown and limit > 0 and value >= limit):
            return None
        return dict(game=active[0][0], stage=active[0][1], countdown=countdown,
                    milliseconds=value, limit=limit, address=target)

    def freeze_minigame_timer(self, manager, area, hold, enabled=False):
        context = self.timer_context(manager)
        if context is None or not enabled:
            hold.reset()
            return dict(context, frozen=False) if context else None
        fields = ('game', 'stage', 'countdown', 'limit', 'address')
        identity = tuple(context[field] for field in fields)
        wanted = hold.target((manager, area, *identity), context['milliseconds'], context['countdown'])
        check = self.timer_context(manager)
        if self.manager() != manager or check is None or tuple(check[field] for field in fields) != identity:
            hold.reset()
            raise NotReady('Minigame ended or changed: timer write cancelled')
        reset = (check['milliseconds'] > context['milliseconds'] + 250 if context['countdown']
                 else check['milliseconds'] < context['milliseconds'] - 250)
        if reset:
            hold.reset()
            raise NotReady('New minigame round: timer write cancelled')
        self.write_verified(context['address'], struct.pack('<ff', wanted, wanted), 'minigame timer')
        return dict(context, milliseconds=wanted, frozen=True)

    def collections(self, manager, named_keys):
        count = self.unpack(manager + 0xC58, '<I')[0]
        if count != 11657:
            raise NotReady('Collected-object table has an unexpected size')
        raw = self.read(self.pointer(manager + 0xC60), count * 16)
        entries = list(struct.iter_unpack('<QII', raw))
        hashes = [row[0] for row in entries]
        if hashes != sorted(hashes) or len(set(hashes)) != count:
            raise NotReady('Collected-object table validation failed')
        if any(flags & 0xFF not in (0, 1) for _, _, flags in entries):
            raise NotReady('Collected-object values are invalid')
        ids = {key for key, _, flags in entries if flags & 1}
        values = {key: int(self.boolean(manager, key)) for key in named_keys}
        if self.manager() != manager:
            raise NotReady('Scene changed while reading collectibles')
        return ids, values
