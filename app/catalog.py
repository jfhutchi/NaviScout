"""Generate collectible guidance from the recipient's own extracted game files."""
import json
from pathlib import Path
import struct
import zstandard

from core import murmur3, read_byml
from settings import BUILD_ID, atomic_json

MAX_RESOURCE = 64 * 1024 * 1024
CATALOG_VERSION = 2


def archive_members(data):
    if data[:4] != b'SARC' or len(data) < 32:
        raise ValueError('The game dictionary archive is invalid.')
    header = struct.unpack_from('<H', data, 4)[0]
    start = struct.unpack_from('<I', data, 12)[0]
    count = struct.unpack_from('<H', data, header + 6)[0]
    if header + 12 + count * 16 > len(data):
        raise ValueError('The game dictionary archive is truncated.')
    result = []
    for index in range(count):
        lo, hi = struct.unpack_from('<II', data, header + 12 + index * 16 + 8)
        if not 0 <= start + lo <= start + hi <= len(data):
            raise ValueError('The dictionary archive contains an invalid range.')
        result.append(data[start + lo:start + hi])
    return result


class GameFiles:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.entries = None
        index = self.root / 'index.json'
        if index.is_file():
            data = json.loads(index.read_text(encoding='utf-8'))
            if data.get('status') != 'pass':
                raise ValueError('NX2navi has not verified this RomFS index.')
            self.entries = {row['path']: row for row in data['files']}
        self.dictionaries = {}

    def raw(self, name):
        if self.entries is None:
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError('Invalid game resource path.')
            if path.stat().st_size > MAX_RESOURCE:
                raise ValueError('Game resource is unexpectedly large.')
            return path.read_bytes()
        row = self.entries[name]
        offset, size = row['offset'], row['size']
        if type(offset) is not int or type(size) is not int or offset < 0 or not 0 < size <= MAX_RESOURCE:
            raise ValueError('Invalid resource range in the game index.')
        with (self.root / 'romfs.bin').open('rb') as stream:
            stream.seek(offset)
            data = stream.read(size)
        if len(data) != size:
            raise ValueError('The game resource image is truncated.')
        return data

    def decode(self, data, dictionary=None):
        try:
            with zstandard.ZstdDecompressor(dict_data=dictionary).stream_reader(data) as reader:
                result = reader.read(MAX_RESOURCE + 1)
        except zstandard.ZstdError as error:
            raise ValueError('A compressed game resource could not be read.') from error
        if len(result) > MAX_RESOURCE:
            raise ValueError('The decompressed game resource is unexpectedly large.')
        return result

    def load(self, name):
        raw = self.raw(name)
        if not name.endswith('.zs'):
            return raw
        try:
            dictionary_id = zstandard.get_frame_parameters(raw).dict_id
            if dictionary_id and not self.dictionaries:
                archive = self.decode(self.raw('Pack/ZsDic.pack.zs'))
                for contents in archive_members(archive):
                    dictionary = zstandard.ZstdCompressionDict(contents)
                    self.dictionaries[dictionary.dict_id()] = dictionary
        except zstandard.ZstdError as error:
            raise ValueError('A compressed game resource could not be read. Verify your NX2navi game files.') from error
        return self.decode(raw, self.dictionaries[dictionary_id] if dictionary_id else None)


def heart_condition(row, reward_flags):
    kind = row['Type']
    if kind == 0:
        return dict(actor=row['ActorHash'])
    if kind == 1:
        key = murmur3(str(row['ActorHash']))
        if key not in reward_flags:
            raise ValueError('A chest-based heart reward has no completion flag in this game.')
        return dict(flag=reward_flags[key])
    if kind == 2:
        return dict(flag=murmur3(row['GameDataHashName']))
    raise ValueError(f'Unsupported heart-piece completion type: {kind}')


def extract_catalog(game):
    files = GameFiles(Path(game) / 'romfs')
    maps = read_byml(files.load('Banc/BancBasedResource/MapParam.byml.zs'))
    schema = read_byml(files.load('GameData/GameDataList.Product.110.byml.zs'))['Data']
    reward_map = next((row for row in schema['Struct'] if row['Hash'] == 0xCE0C4DFE), None)
    if reward_map is None:
        raise ValueError('The game has no chest-reward completion mapping.')
    reward_flags = {row['Hash']: row['Value'] for row in reward_map['DefaultValue']}
    boolean_keys = {row['Hash'] for row in schema['Bool']}
    if len(reward_flags) != len(reward_map['DefaultValue']) or not set(reward_flags.values()) <= boolean_keys:
        raise ValueError('The game has an invalid chest-reward completion mapping.')
    catalog = []

    def visit(node, area, floor=None):
        if isinstance(node, dict):
            for key, rows in node.items():
                if key in ('CollectSign', 'CollectHeart'):
                    for row in rows:
                        item = dict(id=row['InstanceID'], area=area, xyz=row['Trans'], floor=floor,
                                    kind='skull' if key == 'CollectSign' else 'heart')
                        if item['kind'] == 'heart':
                            item.update(heart_condition(row, reward_flags))
                        catalog.append(item)
                elif key == 'Floor':
                    for index, value in enumerate(rows):
                        visit(value, area, index)
                elif key not in ('CollectSignAll', 'CollectHeartAll'):
                    visit(rows, area, floor)
        elif isinstance(node, list):
            for value in node:
                visit(value, area, floor)

    for area, node in maps.items():
        visit(node, area)
    unique = {kind: len({row['id'] for row in catalog if row['kind'] == kind}) for kind in ('skull', 'heart')}
    if unique != {'skull': 100, 'heart': 36}:
        raise ValueError(f'This game has an unexpected collectible layout: {unique}')
    return dict(game_build=BUILD_ID, catalog_version=CATALOG_VERSION, unique=unique, items=catalog)


def save_catalog(game, destination):
    result = extract_catalog(game)
    atomic_json(destination, result)
    return result
