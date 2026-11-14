"""Decode the recipient's Echo Gem cue into their private media directory.

The English PouchContent message names Item_AgonyStone "Echo Gem". Its actor
uses the Near/Far sound events, with Near00 as the close proximity cue.
No game audio is distributed with Navi Scout.
"""
import io
import logging
import os
from pathlib import Path
import struct
import tempfile
import wave

from catalog import GameFiles


ECHO_RESOURCE = 'Sound/Resource/Stream/SE_AgonyStone_Near00.bwav'
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 10
_LOG = logging.getLogger(__name__)


def bwav_to_wav(data: bytes) -> bytes:
    """Convert a bounded, complete mono PCM16 or DSP ADPCM BWAV to PCM WAV.

    BWAV channel headers are 0x4c bytes, following the 0x10 byte file header.
    DSP frames store one predictor/scale byte and fourteen signed nibbles.
    """
    if not 0x5C <= len(data) <= MAX_AUDIO_BYTES or data[:4] != b'BWAV':
        raise ValueError('The Echo Gem BWAV resource is invalid or truncated.')
    bom, version = struct.unpack_from('<HH', data, 4)
    prefetch, channels = struct.unpack_from('<HH', data, 12)
    if bom != 0xFEFF or version != 1 or prefetch or channels != 1:
        raise ValueError('Unsupported Echo Gem BWAV header; a complete mono resource is required.')
    codec, _layout, rate, full_samples, samples = struct.unpack_from('<HHIII', data, 16)
    offset = struct.unpack_from('<I', data, 68)[0]
    loop_end = struct.unpack_from('<i', data, 76)[0]
    if not 8000 <= rate <= 192000 or not 0 < samples <= rate * MAX_SECONDS or samples != full_samples:
        raise ValueError('The Echo Gem BWAV sample count or rate is invalid.')
    if loop_end != -1:
        raise ValueError('The Echo Gem cue must be a one-shot BWAV resource.')
    if codec not in (0, 1):
        raise ValueError(f'Unsupported Echo Gem BWAV codec: {codec}.')
    length = samples * 2 if codec == 0 else ((samples + 13) // 14) * 8
    if offset < 0x5C or offset + length > len(data):
        raise ValueError('The Echo Gem BWAV audio range is truncated or invalid.')
    if codec == 0:
        pcm = data[offset:offset + length]
    else:
        coefficients = struct.unpack_from('<16h', data, 32)
        history1, history2 = struct.unpack_from('<hh', data, 86)
        pcm = bytearray(samples * 2)
        written = 0
        for at in range(offset, offset + length, 8):
            predictor, shift = data[at] >> 4, data[at] & 15
            if predictor > 7:
                raise ValueError('The Echo Gem BWAV has an invalid DSP predictor.')
            coefficient1, coefficient2 = coefficients[predictor * 2:predictor * 2 + 2]
            for index in range(min(14, samples - written)):
                packed = data[at + 1 + index // 2]
                nibble = packed & 15 if index & 1 else packed >> 4
                signed = nibble - 16 if nibble >= 8 else nibble
                predicted = ((signed << shift << 11) + 1024 +
                             coefficient1 * history1 + coefficient2 * history2) >> 11
                sample = max(-32768, min(32767, predicted))
                struct.pack_into('<h', pcm, written * 2, sample)
                history2, history1 = history1, sample
                written += 1
    result = io.BytesIO()
    with wave.open(result, 'wb') as output:
        output.setparams((1, 2, rate, samples, 'NONE', 'not compressed'))
        output.writeframes(pcm)
    return result.getvalue()


def prepare_echo_sound(game_dir: Path, data_dir: Path) -> Path | None:
    """Return a private PCM WAV path, or log why the source is unavailable.

    Invalid resources and write failures propagate for the UI to report. Only
    an absent game resource returns None. Existing identical output is reused.
    """
    files = GameFiles(Path(game_dir) / 'romfs')
    if files.entries is not None and ECHO_RESOURCE not in files.entries:
        _LOG.warning('Echo Gem sound unavailable: this game index has no %s.', ECHO_RESOURCE)
        return None
    try:
        source = files.load(ECHO_RESOURCE)
    except FileNotFoundError:
        _LOG.warning('Echo Gem sound unavailable: game resource %s is missing.', ECHO_RESOURCE)
        return None
    audio = bwav_to_wav(source)
    destination = Path(data_dir) / 'media' / 'echo-gem-near.wav'
    if destination.is_file() and destination.stat().st_size == len(audio) and destination.read_bytes() == audio:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='echo-gem-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(audio)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
