"""Save, resource and radar policies for Ocarina 1.1.1; no process access."""
import math
import struct


RESOURCES = {
    'rupees': (0xA77921D7, 962, 0xE0010A50, 976, (200, 500, 1000)),
    'sticks': (0xB9494411, 1021, 0x457616B0, 975, (10, 20, 30)),
    'seeds': (0x5FADF7FC, 1020, 0xAE8CC742, 974, (30, 40, 50)),
    'nuts': (0xF30D9F54, 1019, 0x735B00F7, 973, (20, 30, 40)),
    'bombs': (0xDB1BCD4F, 1007, 0xE753508B, 972, (20, 30, 40)),
    'bombchus': (0xDF7C517A, 1011, 0xE753508B, 972, (20, 30, 40)),
    'arrows': (0x518EC74B, 1006, 0x418DB791, 971, (30, 40, 50)),
    'magic_beans': (0xB003124D, 1032, None, None, (10,)),
    'scrub_seeds': (0x600E29EB, 1057, None, None, (30,)),
    'health': (0x31AB5580, 963, 0xFBE01DA1, 964, tuple(range(12, 81, 4))),
    'magic': (0x76B18200, 965, 0x12D63A97, 967, (240, 480)),
}


def murmur3(text):
    data = text.encode('utf-8')
    h = 0

    def rotate(x, n):
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

    end = len(data) // 4 * 4
    for off in range(0, end, 4):
        k = int.from_bytes(data[off:off + 4], 'little') * 0xCC9E2D51 & 0xFFFFFFFF
        k = rotate(k, 15) * 0x1B873593 & 0xFFFFFFFF
        h = (rotate(h ^ k, 13) * 5 + 0xE6546B64) & 0xFFFFFFFF
    k = int.from_bytes(data[end:], 'little')
    if k:
        k = rotate(k * 0xCC9E2D51 & 0xFFFFFFFF, 15) * 0x1B873593 & 0xFFFFFFFF
        h ^= k
    h ^= len(data)
    h ^= h >> 16
    h = h * 0x85EBCA6B & 0xFFFFFFFF
    h ^= h >> 13
    h = h * 0xC2B2AE35 & 0xFFFFFFFF
    return h ^ (h >> 16)


class Save:
    def __init__(self, data):
        if len(data) < 40:
            raise ValueError('Save is truncated')
        magic, version, end = struct.unpack_from('<III', data)
        if magic != 0x01020304 or version != 0x002D80EB or not 40 <= end <= len(data) or (end - 40) % 8:
            raise ValueError('Unsupported save header')
        self.values = {}
        for off in range(40, end, 8):
            key, value = struct.unpack_from('<II', data, off)
            if key:
                if key in self.values:
                    raise ValueError('Duplicate save field')
                self.values[key] = value
        start = self.values.get(0xA3DB7114)
        if start is None or start < end or start > len(data) - 8 or (len(data) - start) % 8:
            raise ValueError('Invalid collected-object table')
        values = list(struct.unpack_from('<' + 'Q' * ((len(data) - start) // 8), data, start))
        if not values or values[-1] != 0 or values[:-1] != sorted(values[:-1]):
            raise ValueError('Invalid collected-object ordering')
        self.ids = set(values[:-1])


def collected(item, save):
    if item['kind'] == 'skull':
        return item['id'] in save.ids
    if item.get('flag'):
        if item['flag'] not in save.values:
            raise ValueError('Heart-piece completion flag is absent')
        return save.values[item['flag']] != 0
    if item.get('actor'):
        return item['actor'] in save.ids
    raise ValueError('Heart piece has no completion condition')


def refill_target(name, current, capacity):
    if capacity not in RESOURCES[name][4] or not 0 <= current <= capacity:
        return None
    return capacity


def nearby(catalog, area, xyz, save, radius=10000):
    result = []
    for item in catalog:
        if item['area'] != area or collected(item, save):
            continue
        d = math.dist(xyz, item['xyz'])
        if d <= radius:
            result.append(dict(item, distance=d, dx=item['xyz'][0] - xyz[0],
                               dz=item['xyz'][2] - xyz[2], dy=item['xyz'][1] - xyz[1]))
    return sorted(result, key=lambda x: x['distance'])


def radar_offset(dx, dz, forward):
    """Project a world offset onto camera right and camera forward (screen up)."""
    fx, fz = forward
    length = math.hypot(fx, fz)
    if not math.isfinite(length) or length < 1e-6:
        raise ValueError('Camera direction is invalid')
    fx, fz = fx / length, fz / length
    return -fz * dx + fx * dz, -(fx * dx + fz * dz)


def radar_edge_target(rows, radius, forward):
    """Return the nearest target's screen bearing only when it is outside the circle."""
    if not rows:
        return None
    item = min(rows, key=lambda row: row['distance'])
    distance = math.hypot(item['dx'], item['dz'])
    if distance <= radius:
        return None
    x, y = radar_offset(item['dx'], item['dz'], forward)
    return item, x / distance, y / distance


def read_byml(data):
    if data[:2] not in (b'YB', b'BY'):
        raise ValueError('Not BYML')
    endian = '<' if data[:2] == b'YB' else '>'
    order = 'little' if endian == '<' else 'big'

    def u32(off):
        return struct.unpack_from(endian + 'I', data, off)[0]

    def count(off):
        return int.from_bytes(data[off + 1:off + 4], order)

    def strings(off):
        return [data[off + u32(off + 4 + i * 4):].split(b'\0', 1)[0].decode('utf-8')
                for i in range(count(off))] if off else []

    keys, texts = strings(u32(4)), strings(u32(8))

    def value(kind, raw):
        if kind == 0xA0:
            return texts[raw]
        if kind == 0xC0:
            n = count(raw)
            at = (raw + 4 + n + 3) & ~3
            return [value(data[raw + 4 + i], u32(at + i * 4)) for i in range(n)]
        if kind == 0xC1:
            return {keys[int.from_bytes(data[raw + 4 + 8 * i:raw + 7 + 8 * i], order)]:
                    value(data[raw + 7 + 8 * i], u32(raw + 8 + 8 * i)) for i in range(count(raw))}
        if kind == 0xD0:
            return bool(raw)
        if kind in (0xD1, 0xD2):
            return struct.unpack(endian + ('i' if kind == 0xD1 else 'f'), struct.pack(endian + 'I', raw))[0]
        if kind == 0xD3:
            return raw
        if kind in (0xD4, 0xD5, 0xD6):
            return struct.unpack_from(endian + {0xD4: 'q', 0xD5: 'Q', 0xD6: 'd'}[kind], data, raw)[0]
        if kind == 0xFF:
            return None
        raise ValueError(f'Unsupported BYML node {kind:#x}')

    root = u32(12)
    return value(data[root], root)
