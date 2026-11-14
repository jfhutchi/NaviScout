import io
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from alert_audio import ECHO_RESOURCE, bwav_to_wav, prepare_echo_sound


def bwav(samples=14, codec=1, payload=b'\x00\x12\x34\x56\x78\x9a\xbc\xde',
         coefficients=None, history=(0, 0)):
    data = bytearray(128)
    struct.pack_into('<4sHHIHH', data, 0, b'BWAV', 0xFEFF, 1, 0, 0, 1)
    struct.pack_into('<HHIII', data, 16, codec, 2, 48000, samples, samples)
    struct.pack_into('<16h', data, 32, *(coefficients or [0] * 16))
    struct.pack_into('<IIIiI', data, 64, 128, 128, 1, -1, 0)
    struct.pack_into('<Hhh', data, 84, 0, *history)
    return bytes(data) + payload


def pcm(wav):
    with wave.open(io.BytesIO(wav), 'rb') as stream:
        return stream.getparams(), struct.unpack('<' + 'h' * stream.getnframes(), stream.readframes(stream.getnframes()))


class AlertAudioTests(unittest.TestCase):
    def test_dsp_decodes_signed_nibbles_in_order(self):
        params, values = pcm(bwav_to_wav(bwav()))
        self.assertEqual((params.nchannels, params.sampwidth, params.framerate), (1, 2, 48000))
        self.assertEqual(values, (1, 2, 3, 4, 5, 6, 7, -8, -7, -6, -5, -4, -3, -2))

    def test_dsp_uses_initial_history_and_clamps_prediction(self):
        data = bwav(samples=2, payload=b'\x00\x00' + b'\0' * 6,
                    coefficients=[4096, 0] + [0] * 14, history=(20000, 0))
        self.assertEqual(pcm(bwav_to_wav(data))[1], (32767, 32767))

    def test_dsp_carries_history_across_frames_and_trims_last_frame(self):
        data = bwav(samples=15, payload=b'\x00\x10' + b'\0' * 6 + b'\x00' * 8,
                    coefficients=[2048, 0] + [0] * 14)
        self.assertEqual(pcm(bwav_to_wav(data))[1], (1,) * 15)

    def test_pcm_bwav_has_lossless_wav_payload(self):
        self.assertEqual(pcm(bwav_to_wav(bwav(samples=3, codec=0, payload=struct.pack('<3h', -100, 0, 100))))[1],
                         (-100, 0, 100))

    def test_rejects_truncated_invalid_and_unsupported_audio(self):
        cases = [b'', bwav()[:40], bwav()[:-1], bwav(samples=10000000), bwav(codec=2),
                 bwav(payload=b'\x80' + b'\0' * 7)]
        for data in cases:
            with self.subTest(data=data[:24]), self.assertRaises(ValueError):
                bwav_to_wav(data)
        for offset, fmt, value in [(4, '<H', 0), (6, '<H', 2), (12, '<H', 1),
                                    (14, '<H', 2), (20, '<I', 0), (68, '<I', 1),
                                    (24, '<I', 15), (76, '<i', 14)]:
            data = bytearray(bwav())
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                bwav_to_wav(data)

    def test_prepares_only_private_wav_from_recipients_resource(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game, data = root / 'game', root / 'private'
            source = game / 'romfs' / ECHO_RESOURCE
            source.parent.mkdir(parents=True)
            source.write_bytes(bwav())
            result = prepare_echo_sound(game, data)
            self.assertEqual(result, data / 'media' / 'echo-gem-near.wav')
            self.assertEqual(pcm(result.read_bytes())[1][0], 1)
            stamp = result.stat().st_mtime_ns
            self.assertEqual(prepare_echo_sound(game, data), result)
            self.assertEqual(result.stat().st_mtime_ns, stamp)
            self.assertEqual(source.read_bytes(), bwav())

    def test_missing_resource_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as temp, self.assertLogs('alert_audio', level='WARNING') as logs:
            self.assertIsNone(prepare_echo_sound(Path(temp) / 'missing', Path(temp) / 'private'))
        self.assertIn('Echo Gem sound unavailable', logs.output[0])

    def test_malformed_resource_is_reported_as_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'romfs' / ECHO_RESOURCE
            source.parent.mkdir(parents=True)
            source.write_bytes(b'invalid')
            with self.assertRaisesRegex(ValueError, 'BWAV'):
                prepare_echo_sound(root, root / 'private')


if __name__ == '__main__':
    unittest.main()
