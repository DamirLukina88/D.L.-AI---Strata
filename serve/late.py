"""A way to read names that stay in serve/server.py (or that tests patch on it) from the modules split out of it, at
call time, so a patch on `serve.server` still reaches them."""


def server():
    import importlib
    return importlib.import_module("serve.server")
