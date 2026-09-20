from types import SimpleNamespace

def parse(*args, **kwargs):
    return SimpleNamespace(entries=[], bozo=False, feed=SimpleNamespace(title=''))
