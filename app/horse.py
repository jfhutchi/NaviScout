"""Validated, reversible speed overrides for the currently ridden Epona."""
import logging
import struct

from memory import ChangedHorsePower, NotReady, StaleParameter


class HorseSpeed:
    def __init__(self):
        self.owner = self.context = self.original = self.modified = None
        self.hold_context = None

    def clear_patch(self):
        self.owner = self.context = self.original = self.modified = None

    def update(self, game, enabled):
        if self.owner is not None and self.owner is not game:
            if self.owner.alive():
                raise NotReady('Epona speed still belongs to a different game process')
            self.__init__()
        context = game.horse_context() if enabled or self.hold_context is not None else None
        if self.hold_context is not None and (context is None or context[:5] != self.hold_context):
            self.hold_context = None
        if not enabled:
            self.restore(game)
            return 'Epona speed: normal / riding test pending'
        if self.context is not None and self.context != context:
            self.restore(game)
        if self.hold_context is not None:
            return 'Epona speed paused: dismount and remount after the game refreshes her power.'
        if context is None:
            return 'Epona 2x armed: mount Epona to activate. Riding test pending.'
        if self.context is not None:
            if game.horse_speed_snapshot(context) != self.modified:
                raise NotReady('Epona speed changed outside Navi Scout; restore cancelled')
        else:
            original = game.horse_speed_snapshot(context)
            speeds = struct.unpack('<4f', original)
            if any(value > 32 for value in speeds):
                raise ValueError('Epona speed is too high to double safely')
            self.owner, self.context, self.original = game, context, original
            self.modified = struct.pack('<4f', *(value * 2 for value in speeds))
            game.horse_speed_replace(context, original, self.modified, riding=True)
        return 'Epona riding speed 2x active. Riding test pending.'

    def restore(self, game):
        if self.context is None:
            return
        if self.owner is not game:
            if self.owner.alive():
                raise NotReady('Cannot restore Epona speed through another game process')
            self.__init__()
            return
        try:
            current = game.horse_speed_snapshot(self.context)
        except ChangedHorsePower:
            # Power is stored before the native gear-cache refresh. Never capture
            # a partly refreshed cache, including after switching Off then On.
            self.hold_context = self.context[:5]
            self.clear_patch()
            return
        except StaleParameter:
            logging.info('Discarded released or replaced Epona speed context without writing to it')
            self.clear_patch()
            return
        if current != self.original:
            if current != self.modified:
                raise NotReady('Epona speed changed outside Navi Scout; restore cancelled')
            game.horse_speed_replace(self.context, current, self.original, riding=False)
        self.clear_patch()
