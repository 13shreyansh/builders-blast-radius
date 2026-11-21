"""Track source and fixture access by one fresh test-file process and its children."""
import atexit
import importlib.util
import json
import multiprocessing.util
import os
import sys

tree = os.environ["BLAST_SOURCE"]
prefix = tree + os.sep
scratch = os.environ["BLAST_READ_LOG"]
used = set()
dirs = set()


def normalize(value):
    if not isinstance(value, str):
        return None
    if value.startswith(prefix):
        value = value[len(prefix):]
    elif os.path.isabs(value):
        return None
    else:
        value = os.path.abspath(value)
        if not value.startswith(prefix):
            return None
        value = value[len(prefix):]
    if value.endswith(".pyc"):
        try:
            value = importlib.util.source_from_cache(value)
        except ValueError:
            return None
    if value.startswith(("sqlglot/","tests/","sqlglotc/")):
        return value
    return None


def observe(event, args):
    if event in ("open","os.listdir","os.scandir") and args:
        name = normalize(args[0])
        if name:
            (used if event == "open" else dirs).add(name)


def flush():
    for module in tuple(sys.modules.values()):
        path = normalize(vars(module).get("__file__")) if isinstance(module,type(sys)) else None
        if path:
            used.add(path)
    with open(os.path.join(scratch,f"{os.getpid()}.json"),"w") as f:
        json.dump([sorted(used),sorted(dirs)],f)


sys.addaudithook(observe)
atexit.register(flush)
multiprocessing.util.Finalize(None,flush,exitpriority=2)
