"""Reversible fishing resource assists for the validated E0F3CCFAF50065AE build."""
from dataclasses import dataclass
import logging
import math
import struct

from memory import NotReady, StaleParameter
from running import RunSpeed


FISHING_OPTIONS = (('hook_window', 'Longer hook window'),
                   ('escape_window', 'More forgiving escape window'),
                   ('quick_exhaust', 'Shorter stamina cycles'),
                   ('reel_speed', 'Reel speed 2x'))

# Native FishParam bindings and their inheritance flags; never touch records,
# size, rewards, inventory, fish state transitions, or empty-lure return speed.
ROOT_TYPE = 0x4B3E548
GROUPS = {
    'hook_window': (0x21C, 0xB0, 0x12B, 0x4B5B1F0,
                    ((0x38, 0x50), (0x3C, 0x52), (0x48, 0x54))),
    'escape_window': (0x220, 0x38, 0x12C, 0x4B5AF98,
                      ((0x40, 0x51), (0x4C, 0x52), (0x3C, 0x53),
                       (0x48, 0x54), (0x44, 0x55))),
    'quick_exhaust': (0x224, 0x60, 0x12D, 0x4B5B060,
                      ((0x48, 0x70), (0x40, 0x71), (0x60, 0x76),
                       (0x6C, 0x73), (0x64, 0x74))),
}


@dataclass
class ParameterPatch:
    option: str
    value_address: int
    flag_address: int
    original: bytes
    original_flag: bytes
    modified: bytes
    path: tuple


def _remember(game, path, address, size):
    raw = game.read(address, size)
    path.append((address, raw))
    return raw


def _effective(game, parameter, offset, flag_offset, type_rva, path):
    """Follow the native generation-checked resource inheritance handle."""
    seen = set()
    while parameter:
        if parameter in seen or len(seen) >= 8:
            raise NotReady('Fishing parameter inheritance is cyclic or too deep')
        seen.add(parameter)
        header = _remember(game, path, parameter, 0x28)
        if struct.unpack_from('<Q', header)[0] != game.BASE + type_rva:
            raise NotReady('Fishing parameter type is not verified for this build')
        flag = game.read(parameter + flag_offset, 1)[0]
        if flag not in (0, 1):
            raise NotReady('Fishing parameter override flag is invalid')
        slot = struct.unpack_from('<Q', header, 0x18)[0]
        if flag or not struct.unpack_from('<Q', header, 0x10)[0] or not slot:
            return parameter + offset
        serial = struct.unpack_from('<I', header, 0x20)[0]
        slot_header = _remember(game, path, slot, 0x10)
        if struct.unpack_from('<I', slot_header, 0xC)[0] != serial:
            return parameter + offset
        parent = struct.unpack_from('<Q', slot_header)[0]
        if not parent:
            return parameter + offset
        parameter = parent
    raise NotReady('Fishing parameter inheritance is unavailable')


def _local_group(game, root, fish, option, path):
    index_offset, group_offset, group_flag, group_type, _ = GROUPS[option]
    array = _effective(game, root, 0xA8, 0x29B, ROOT_TYPE, path)
    index = game.unpack(fish + index_offset, '<I')[0]
    # EnumArray entries have a pointer and an inheritance flag. More complex
    # parent-array/vector combinations stay unavailable until runtime verified.
    header = _remember(game, path, array, 0x28)
    count = struct.unpack_from('<I', header, 8)[0]
    entries = struct.unpack_from('<Q', header, 0x10)[0]
    if not 1 <= count <= 32 or index >= count or not entries:
        raise NotReady('Fishing situation index or array layout is not verified')
    entry = _remember(game, path, entries + index * 16, 16)
    record, flag = struct.unpack_from('<Q', entry)[0], entry[8]
    if flag != 1 or struct.unpack_from('<Q', header, 0x20)[0]:
        raise NotReady('Inherited fishing situation arrays are not yet verified')
    vector = _effective(game, record, group_offset, group_flag, 0x4B5AED0, path)
    header = _remember(game, path, vector, 0x20)
    count = struct.unpack_from('<I', header, 8)[0]
    pointers = struct.unpack_from('<Q', header, 0x10)[0]
    if count != 1 or not pointers or struct.unpack_from('<Q', header, 0x18)[0]:
        raise NotReady('Inherited or multi-object fishing parameter groups are not yet verified')
    raw = _remember(game, path, pointers, 8)
    parameter = struct.unpack('<Q', raw)[0]
    if not parameter or game.pointer(parameter) != game.BASE + group_type:
        raise NotReady('Fishing parameter group has an unverified type')
    return parameter, group_type


def _actor_handle(game, view):
    slot = game.pointer(view + 8)
    serial = game.unpack(view + 0x10, '<I')[0]
    if not slot or serial == 0xFFFFFFFF or game.unpack(slot + 0x48, '<I')[0] != serial:
        return None
    actor = game.pointer(slot + 0x40)
    if (not actor or not 2 <= game.unpack(actor + 0x2C, '<I')[0] <= 6
            or game.unpack(actor + 0x18, '<I')[0] != serial
            or game.pointer(actor + 0x1B0) != slot):
        return None
    return slot, serial, actor


def _inventory_actor(game, registry, key):
    count = game.unpack(registry + 0x34, '<I')[0]
    entries = game.pointer(registry + 0x28)
    if not 1 <= count <= 128 or not entries:
        raise NotReady('Fishing equipment registry size is invalid')
    # Follow the native open-addressed item lookup, bounded by table capacity.
    for probe in range(count):
        entry = entries + ((key % count + probe) % count) * 32
        found = game.unpack(entry, '<I')[0]
        if not found:
            return None
        if found != key:
            continue
        size = game.unpack(entry + 0x10, '<I')[0]
        objects = game.pointer(entry + 0x18)
        if size == 0:
            return None
        if size != 1 or not objects:
            raise NotReady('Fishing equipment registry entry is ambiguous')
        item = game.pointer(objects)
        if not item or game.pointer(item) != game.BASE + 0x4B469A0:
            raise NotReady('Fishing equipment item type is invalid')
        if game.read(item + 0x3C, 1)[0] & 1 or not game.read(item + 0x3D, 1)[0] & 1:
            return None
        return _actor_handle(game, item + 0x28)
    raise NotReady('Fishing equipment registry lookup is invalid')


def _player_action(game):
    """Find an active lure owned by Link and his current fishing rod.

    The lure's native owner handles also cover fishing started through player
    states that do not instantiate the ExecutePlayerFishing AI action.
    """
    manager = game.pointer(game.BASE + 0x4E371D0)
    player = game.pointer(manager + 0x480) if manager else 0
    if not player:
        return None
    if game.read(game.pointer(player + 0x20), 7) != b'Player\0':
        raise NotReady('Fishing player identity is invalid')
    components = game.pointer(player + 0x270)
    body = game.pointer(components + 0x358) if components else 0
    if not body:
        return None
    if game.pointer(body) != game.BASE + 0x4B4DFC0 or game.pointer(body + 0x18) != player:
        raise NotReady('Fishing player component ownership is invalid')
    if game.unpack(body + 0x7D8, '<I')[0] != 18:
        return None
    registry = game.pointer(components + 0x110)
    if (not registry or game.pointer(registry) != game.BASE + 0x4B46870
            or game.pointer(registry + 0x18) != player):
        raise NotReady('Fishing equipment registry ownership is invalid')
    rod_identity = _inventory_actor(game, registry, 0xEF1DF6C8)
    if rod_identity is None:
        return None
    rod = rod_identity[-1]
    if game.read(game.pointer(rod + 0x20), 16) != b'Item_FishingRod\0':
        raise NotReady('Equipped fishing rod actor identity is invalid')
    matches = []
    for key, name in ((0x27D2FDE5, b'Weapon_Lure\0'), (0x791406DD, b'Weapon_SinkingLure\0')):
        identity = _inventory_actor(game, registry, key)
        if identity is None:
            continue
        lure = identity[-1]
        if game.read(game.pointer(lure + 0x20), len(name)) != name:
            raise NotReady('Fishing lure actor identity is invalid')
        table = game.pointer(lure + 0x270)
        component = game.pointer(table + 0x2E0) if table else 0
        if (not component or game.pointer(component) != game.BASE + 0x4B4CA80
                or game.pointer(component + 0x18) != lure):
            raise NotReady('Fishing lure component type or owner is invalid')
        if (not game.read(component + 0x20, 1)[0] & 1
                or game.unpack(component + 0x24, '<I')[0] not in (4, 5)):
            continue
        player_identity = _actor_handle(game, component + 0xA0)
        parent_identity = _actor_handle(game, component + 0xB8)
        if (player_identity is None or player_identity[-1] != player
                or parent_identity != rod_identity):
            raise NotReady('Fishing lure player or rod ownership changed')
        matches.append((player, body, lure, *rod_identity, *identity, *player_identity))
    if len(matches) > 1:
        raise NotReady('Active fishing lure is ambiguous; writes paused')
    return matches[0] if matches else None


def fishing_context(game):
    action = _player_action(game)
    if action is None:
        return None
    player, body, lure = action[:3]
    if not lure or not 2 <= game.unpack(lure + 0x2C, '<I')[0] <= 6:
        return None
    lure_slot = game.pointer(lure + 0x1B0)
    lure_serial = game.unpack(lure + 0x18, '<I')[0]
    if (not lure_slot or lure_serial == 0xFFFFFFFF
            or game.pointer(lure_slot + 0x40) != lure
            or game.unpack(lure_slot + 0x48, '<I')[0] != lure_serial):
        raise NotReady('Fishing lure actor generation is invalid')
    table = game.pointer(lure + 0x270)
    component = game.pointer(table + 0x2E0) if table else 0
    if (not component or game.pointer(component) != game.BASE + 0x4B4CA80
            or game.pointer(component + 0x18) != lure):
        raise NotReady('Fishing lure component type or owner is invalid')
    if not game.read(component + 0x20, 1)[0] & 1:
        return None
    phase = game.unpack(component + 0x24, '<I')[0]
    if phase not in (4, 5):
        return None
    slot = game.pointer(component + 0xF0)
    serial = game.unpack(component + 0xF8, '<I')[0]
    if not slot or serial == 0xFFFFFFFF or game.unpack(slot + 0x48, '<I')[0] != serial:
        return None
    link = game.pointer(table + 0x2C0)
    if (not link or game.pointer(link) != game.BASE + 0x4B4C568
            or game.pointer(link + 0x18) != lure
            or game.pointer(link + 0xD0) != slot
            or game.unpack(link + 0xD8, '<I')[0] != serial):
        raise NotReady('Fishing lure current target changed; write cancelled')
    fish_actor = game.pointer(slot + 0x40)
    if not fish_actor or not 2 <= game.unpack(fish_actor + 0x2C, '<I')[0] <= 6:
        return None
    if game.read(game.pointer(fish_actor + 0x20), 17) != b'Animal_Fish_Bass\0':
        raise NotReady('This fishing assist currently supports pond bass only')
    fish_table = game.pointer(fish_actor + 0x270)
    fish = game.pointer(fish_table + 0x218) if fish_table else 0
    if (not fish or game.pointer(fish) != game.BASE + 0x4B49B08
            or game.pointer(fish + 0x18) != fish_actor):
        raise NotReady('Current fish component type or owner is invalid')
    descriptor, root = game.pointer(fish + 0x10), game.pointer(fish + 0x20)
    if (not descriptor or not root or game.pointer(descriptor + 0x150) != root
            or game.pointer(root) != game.BASE + ROOT_TYPE):
        raise NotReady('Current fish resource ownership or type is invalid')
    return (*action, lure, component, phase, slot, serial, fish_actor,
            lure_slot, lure_serial, link, fish, descriptor, root)


class FishingAssists:
    def __init__(self):
        self.owner = self.context = None
        self.patches = []
        self.guard = RunSpeed()

    def _owner(self, game):
        if self.owner is not None and self.owner is not game:
            if self.owner.alive():
                raise NotReady('Fishing assists still belong to a different game process')
            self.owner = self.context = None
            self.patches.clear()

    def _plan(self, game, context, options):
        fish, descriptor, root = context[-3:]
        base_path = []
        _remember(game, base_path, descriptor, 0x28)
        _remember(game, base_path, descriptor + 0x150, 8)
        _remember(game, base_path, root, 0x28)
        planned = []
        for option in options:
            path = list(base_path)
            first_cycle = 0.0
            if option == 'reel_speed':
                parameter, type_rva = root, ROOT_TYPE
                fields = ((0x224, 0x2D4), (0x220, 0x2D5))
            else:
                parameter, type_rva = _local_group(game, root, fish, option, path)
                fields = GROUPS[option][-1]
            for index, (offset, flag_offset) in enumerate(fields):
                field_path = list(path)
                source = _effective(game, parameter, offset, flag_offset, type_rva, field_path)
                value = game.unpack(source, '<f')[0]
                limit = 32 if option == 'reel_speed' else 36000
                if not math.isfinite(value) or not 0 < value <= limit:
                    raise NotReady('Fishing parameter is outside the supported range')
                if option == 'reel_speed':
                    wanted = value * 2
                elif option == 'quick_exhaust':
                    if index < 2:
                        first_cycle = max(first_cycle, value)
                        wanted = min(value, 60)
                    elif index == 2:
                        wanted = min(value, 30)
                    else:
                        # The game rereads reductions at subsequent struggles;
                        # leave any already-running native countdown untouched.
                        wanted = max(value, first_cycle)
                elif option == 'hook_window':
                    wanted = max(value, min(1800, max(value * 3, 120)))
                else:
                    wanted = max(value, min(1800, max(value * 3, 90)))
                planned.append(ParameterPatch(option, parameter + offset, parameter + flag_offset,
                                              game.read(parameter + offset, 4),
                                              game.read(parameter + flag_offset, 1),
                                              struct.pack('<f', wanted), tuple(field_path)))
        return planned

    def _validate_paths(self, game, patches):
        for patch in patches:
            for address, raw in patch.path:
                if game.read(address, len(raw)) != raw:
                    raise StaleParameter('Fishing resource was released or replaced; write cancelled')

    def _check_values(self, game, patches, active=False):
        for patch in patches:
            value = game.read(patch.value_address, 4)
            flag = game.read(patch.flag_address, 1)
            if ((active and (value != patch.modified or flag != b'\1'))
                    or value not in (patch.original, patch.modified)
                    or flag not in (patch.original_flag, b'\1')):
                raise NotReady('Fishing settings changed outside Navi Scout; write cancelled')

    def update(self, game, options):
        unknown = set(options) - {key for key, _ in FISHING_OPTIONS}
        if unknown or any(type(value) is not bool for value in options.values()):
            raise ValueError('Fishing options must be supported boolean switches')
        self._owner(game)
        enabled = tuple(key for key, _ in FISHING_OPTIONS if options.get(key, False))
        if not enabled:
            self.restore(game)
            return 'Fishing assists: Off.'
        context = fishing_context(game)
        if self.patches:
            if context != self.context or enabled != tuple(dict.fromkeys(p.option for p in self.patches)):
                self.restore(game)
            else:
                self._validate_paths(game, self.patches)
                self._check_values(game, self.patches, active=True)
        if context is None:
            return 'Waiting for active pond fishing and a current fish.'
        if not self.patches:
            planned = self._plan(game, context, enabled)
            with self.guard.paused(game, ()):
                if fishing_context(game) != context:
                    raise NotReady('Fishing changed during update; write cancelled')
                self._validate_paths(game, planned)
                for patch in planned:
                    if (game.read(patch.value_address, 4), game.read(patch.flag_address, 1)) != (patch.original, patch.original_flag):
                        raise NotReady('Fishing settings changed during update; write cancelled')
                self.owner, self.context = game, context
                # Retain the entire restoration journal before the first write,
                # including on write/read-back errors or partial transactions.
                self.patches = planned
                for patch in planned:
                    game.write_verified(patch.value_address, patch.modified, 'Fishing assist value')
                    game.write_verified(patch.flag_address, b'\1', 'Fishing assist inheritance')
        labels = dict(FISHING_OPTIONS)
        return 'Fishing assists active: ' + ', '.join(labels[key] for key in enabled) + '.'

    def restore(self, game):
        self._owner(game)
        if not self.patches:
            return
        with self.guard.paused(game, ()):
            valid = []
            for patch in self.patches:
                try:
                    self._validate_paths(game, (patch,))
                except NotReady:
                    logging.info('Discarded a released fishing parameter without writing to it')
                else:
                    valid.append(patch)
            # A replaced child group does not release the independently owned
            # root resource. Preflight every surviving field before restoring.
            self._check_values(game, valid)
            for patch in reversed(valid):
                if game.read(patch.flag_address, 1) != patch.original_flag:
                    game.write_verified(patch.flag_address, patch.original_flag, 'Fishing original inheritance')
                if game.read(patch.value_address, 4) != patch.original:
                    game.write_verified(patch.value_address, patch.original, 'Fishing original value')
        self.patches.clear()
        self.owner = self.context = None
