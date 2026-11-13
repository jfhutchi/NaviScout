"""Per-dive depth limits, kept separate from air and minigame clocks."""
import logging

from memory import NotReady

DIVE_MODES = ('Off', '2x', 'Unlimited')


class DiveLimit:
    def __init__(self):
        self.reset()

    def reset(self):
        self.identity = None
        self.base = None
        self.written = None
        self.previous_written = None
        self.phase = None

    def restore(self, game):
        if self.written is None:
            self.reset()
            return
        context = game.dive_context()
        if (context and context['identity'] == self.identity
                and context['depth'] in (self.written, self.previous_written)):
            game.set_dive_depth(context, context['depth'], self.base)
        else:
            logging.info('Dive ended or changed; discarded transient depth override without writing')
        self.reset()

    def update(self, game, mode='Off'):
        if mode not in DIVE_MODES:
            raise ValueError('Invalid dive limit mode')
        if mode == 'Off':
            self.restore(game)
            return None
        context = game.dive_context()
        if context is None:
            self.reset()
            return None
        identity, phase, depth = (context[field] for field in ('identity', 'phase', 'depth'))
        if identity != self.identity:
            self.reset()
            self.identity = identity
        if phase not in (1, 2):
            self.phase = phase
            return None
        fresh = self.phase not in (1, 2) or self.base is None
        if fresh or (depth != self.written and depth in (3.0, 6.0, 9.0)):
            if depth not in (3.0, 6.0, 9.0):
                raise NotReady('Waiting for the game to initialize the current scale dive limit')
            self.base = depth
            self.written = None
            self.previous_written = None
        elif depth != self.written:
            raise NotReady('Dive limit changed outside Navi Scout; waiting for a new dive')
        wanted = self.base * 2 if mode == '2x' else 100000.0
        self.previous_written = self.written
        self.written = wanted
        self.phase = phase
        if depth != wanted:
            game.set_dive_depth(context, depth, wanted)
        self.previous_written = None
        return dict(base=self.base, depth=wanted, mode=mode)
