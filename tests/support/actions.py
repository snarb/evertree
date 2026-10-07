from evertree.core.actions import ActionOption


class Adapter:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    async def list_actions(self):
        return [ActionOption({"move": 2})]

    async def execute(self, command):
        self.calls += 1
        if self.fail:
            raise OSError("Lost connection after send")
        return "accepted"
