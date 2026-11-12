"""Round-local state for holding a minigame's shared timer."""


class TimerHold:
    def __init__(self):
        self.reset()

    def reset(self):
        self.key = None
        self.value = None

    def target(self, key, value, countdown):
        restarted = (self.value is not None and
                     (value > self.value + 250 if countdown else value < self.value - 250))
        if key != self.key or restarted:
            self.key, self.value = key, value
        return self.value
