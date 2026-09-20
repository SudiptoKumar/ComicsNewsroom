from types import SimpleNamespace
class Cerebras:
    def __init__(self, *args, **kwargs):
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self._create))
    def _create(self, *args, **kwargs):
        content='{"ranked":[]}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
