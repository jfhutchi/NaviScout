"""Compatible figure identifiers and local virtual reader tokens; no tag dumps."""
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path

from core import murmur3, read_byml

SETTINGS_RESOURCE = 'Game/AmiiboSetting/AmiiboSetting.game__ui__AmiiboSetting.bgyml'


@dataclass(frozen=True)
class AmiiboPreset:
    name: str
    tag_id: str
    reward: str = 'Random supplies'
    upcoming: bool = False


# Identifier metadata: AmiiboAPI (8bitDream/AmiiboAPI, database/amiibo.json).
# The two upcoming presets use the model numbers in this game's own mask rules.
PRESETS = (
    AmiiboPreset("Zelda and Loftwing", '0101030004140902'),
    AmiiboPreset("Guardian", '0140000003550902'),
    AmiiboPreset("Link (Smash Bros.)", '0100000000040002'),
    AmiiboPreset("Link - Archer", '0100000003530902'),
    AmiiboPreset("8-Bit Link", '01000000034f0902'),
    AmiiboPreset("Link - Rider", '0100000003540902'),
    AmiiboPreset("Toon Link - The Wind Waker", '0100010003500902'),
    AmiiboPreset("Zelda (Breath of the Wild)", '0101000003560902'),
    AmiiboPreset("Young Link (Smash Bros.)", '01000000037c0002'),
    AmiiboPreset("Midna & Wolf Link", '01030000024f0902'),
    AmiiboPreset("Daruk", '0105000003580902'),
    AmiiboPreset("Tulin", '010b000004a50902'),
    AmiiboPreset("Yunobo", '010c000004a60902'),
    AmiiboPreset("Sidon", '010a000004a40902'),
    AmiiboPreset("Riju", '0109000004a30902'),
    AmiiboPreset("Mineru's Construct", '010d000004a70902'),
    AmiiboPreset("Mipha", '01070000035a0902'),
    AmiiboPreset("Revali", '01080000035b0902'),
    AmiiboPreset("Toon Zelda - The Wind Waker", '0101000003520902'),
    AmiiboPreset("Link - Twilight Princess", '01000000034d0902'),
    AmiiboPreset("Ganondorf - Tears of the Kingdom", '01020100041a0902'),
    AmiiboPreset("Link - Ocarina of Time", '01000000034b0902'),
    AmiiboPreset("Link - Majora's Mask", '01000000034c0902'),
    AmiiboPreset("Bokoblin", '01410000035c0902'),
    AmiiboPreset("Urbosa", '0106000003590902'),
    AmiiboPreset("Link - Link's Awakening", '0100000003990902'),
    AmiiboPreset("Zelda - Tears of the Kingdom", '0101000004190902'),
    AmiiboPreset("Link - Tears of the Kingdom", '0100000004180902'),
    AmiiboPreset("Toon Link (Smash Bros.)", '0100010000160002'),
    AmiiboPreset("Link - Skyward Sword", '01000000034e0902'),
    AmiiboPreset("Sheik (Smash Bros.)", '0101010000170002'),
    AmiiboPreset("Ganondorf (Smash Bros.)", '01020100001b0002'),
    AmiiboPreset("Zelda (Smash Bros.)", '01010000000e0002'),
    AmiiboPreset('Young Link (Ocarina of Time, 2027)', '0100000004fd0902', 'Retro Link mask', True),
    AmiiboPreset('Young Zelda (Ocarina of Time, 2027)', '0101000004ff0902', 'Retro Zelda mask', True),
)
_BY_ID = {row.tag_id: row for row in PRESETS}
_BASE_NAMES = {0x0100: 'Link', 0x0101: 'Zelda', 0x0102: 'Ganon'}


def compatible_presets(settings):
    rules = settings['AmiiboDropActorSettingSet']
    if not isinstance(rules, list) or any(not isinstance(row, dict) for row in rules):
        raise ValueError('The game has an invalid amiibo compatibility table')
    result = []
    for preset in PRESETS:
        tag = bytes.fromhex(preset.tag_id)
        model = int.from_bytes(tag[4:6], 'big')
        base = _BASE_NAMES.get(int.from_bytes(tag[:2], 'big'))
        for rule in rules:
            numbering_match = rule.get('NumberingID') == murmur3(f'NumberingID_{model}')
            series_match = (rule.get('AmiiboSetType') == murmur3('SeriesID')
                            and rule.get('SeriesIDType') == murmur3(f'AmiiboSeriesID{tag[6]:02d}'))
            character_match = (base is not None and rule.get('AmiiboSetType') == murmur3('CharacterBaseID')
                               and rule.get('CharacterBaseIDType') == murmur3(base))
            if not (numbering_match or series_match or character_match):
                continue
            actors = {row['ActorNameShort'] for row in rule.get('DropActorInfoList', {}).get('DropActorInfo', [])}
            reward = ('Retro Link mask' if 'Obj_Mask_Amiibo0' in actors else
                      'Retro Zelda mask' if 'Obj_Mask_Amiibo1' in actors else 'Random supplies')
            result.append(replace(preset, reward=reward))
            break
    return sorted(result, key=lambda row: row.name.casefold())


def load_presets(game_dir):
    from catalog import GameFiles
    return compatible_presets(read_byml(GameFiles(Path(game_dir) / 'romfs').load(SETTINGS_RESOURCE)))


def virtual_tag(preset):
    if preset.tag_id not in _BY_ID:
        raise ValueError('This amiibo identifier is not in the verified preset catalog')
    raw = bytearray(540)
    uid = bytearray(hashlib.sha256(('NaviScout:' + preset.tag_id).encode('ascii')).digest()[:7])
    uid[0] = 4
    raw[:3], raw[4:8] = uid[:3], uid[3:]
    raw[3] = 0x88 ^ raw[0] ^ raw[1] ^ raw[2]
    raw[8] = raw[4] ^ raw[5] ^ raw[6] ^ raw[7]
    raw[12:16] = bytes.fromhex('f110ffee')
    raw[0x54:0x5c] = bytes.fromhex(preset.tag_id)
    return bytes(raw)


def cache_tag(preset, game_dir):
    contents = virtual_tag(preset)
    folder = Path(game_dir) / 'amiibo/NaviScout'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (preset.tag_id + '.bin')
    if not target.is_file() or target.read_bytes() != contents:
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(contents)
        temporary.replace(target)
    return target
