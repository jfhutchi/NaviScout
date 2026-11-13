"""Small label-aware encoder for the trainer's checked x64 helpers."""
import struct


class Assembly:
    def __init__(self):
        self.code, self.fixups, self.labels = bytearray(), [], {}

    def emit(self, raw):
        self.code.extend(bytes.fromhex(raw))

    def address(self, opcode, address):
        self.emit(opcode)
        self.code.extend(struct.pack('<Q', address))

    def branch(self, opcode, label):
        self.emit(opcode)
        self.fixups.append((len(self.code), label))
        self.code.extend(bytes(4))

    def finish(self):
        for offset, label in self.fixups:
            struct.pack_into('<i', self.code, offset, self.labels[label] - offset - 4)
        return bytes(self.code)
