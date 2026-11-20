"""Standing instructions the user gave the agent (stop sending, no meetings before N, defer work...)."""


class Standing:
    def __init__(self):
        self.reset()

    def reset(self):
        self.no_send = False
        self.min_meeting_hour: int | None = None
        self.defer_to = None   # date work tasks were pushed to


standing = Standing()
