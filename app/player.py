"""Reversible overrides for Link's own movement parameters."""
from dataclasses import dataclass
import math
import logging
import struct

from memory import MOVEMENT_LIMITS, NotReady, StaleParameter


@dataclass(frozen=True)
class ParameterPatch:
    context: tuple
    original: bytes
    flag: int
    modified: bytes


class PlayerModifiers:
    def __init__(self):
        self.patches = {}

    def update(self, game, run=False, jump=False, roll=False):
        wanted = dict(roll=roll, jump=jump, swim=run, swim_heavy=run,
                      swim_dash=run, swim_dash_heavy=run)
        if not any(wanted.values()):
            self.restore(game)
            return
        context = game.player_parameter_context()
        if any(patch.context != context for patch in self.patches.values()):
            self.restore(game)
        for name, enabled in wanted.items():
            if not enabled:
                self.restore(game, name)
                continue
            if name in self.patches:
                patch = self.patches[name]
                current, flag, _ = game.parameter_snapshot(context, name)
                if (current, flag) != (patch.modified, patch.flag | 1):
                    raise NotReady(f'{name} changed outside Navi Scout; restart the game to reset controls')
                continue
            original, flag, effective = game.parameter_snapshot(context, name)
            if not math.isfinite(effective) or not 0.1 <= effective <= MOVEMENT_LIMITS[name] / 2:
                raise ValueError(f'Unexpected {name} parameter; movement override stopped')
            modified = struct.pack('<f', effective * 2)
            patch = ParameterPatch(context, original, flag, modified)
            # Remember before writing so a partial failure can still be restored.
            self.patches[name] = patch
            game.parameter_replace(context, name, (original, flag), modified, flag | 1)

    def restore(self, game, name=None):
        errors = []
        for key in list(self.patches):
            if name is not None and key != name:
                continue
            patch = self.patches[key]
            try:
                current, flag, _ = game.parameter_snapshot(patch.context, key)
            except StaleParameter:
                logging.info('Discarded released %s parameter resource without writing to it', key)
                del self.patches[key]
                continue
            except NotReady as error:
                errors.append(error)
                continue
            if (current, flag) != (patch.original, patch.flag):
                if current != patch.modified or flag not in (patch.flag, patch.flag | 1):
                    errors.append(NotReady(f'{key} changed outside Navi Scout; restore cancelled'))
                    continue
                try:
                    game.parameter_replace(patch.context, key, (current, flag), patch.original, patch.flag)
                except (NotReady, OSError) as error:
                    errors.append(error)
                    continue
            del self.patches[key]
        if errors:
            raise errors[0]
