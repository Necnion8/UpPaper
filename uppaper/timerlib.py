from dncore.extensions.timerlib import Timer


class UpPaperTimer(object):
    def __init__(self, owner):
        self.timer = Timer(owner)

    def schedule(self, hour: int, callback):
        return self.timer.daily(hour, 0, callback)

    def cancel(self):
        self.timer.cancel_all()
