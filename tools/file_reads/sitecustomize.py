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
calls = set()
capture_functions = os.environ.get("BLAST_CAPTURE_FUNCTIONS") == "1"


def on_start(code, offset):
    filename = code.co_filename
    if filename.startswith(prefix):
        relative = filename[len(prefix):]
        if relative.startswith(("sqlglot/","tests/")) and code.co_name != "<module>":
            calls.add((relative,code.co_firstlineno,code.co_name))
    return sys.monitoring.DISABLE


if capture_functions:
    monitor = sys.monitoring
    monitor.use_tool_id(monitor.PROFILER_ID,"blast clean test")
    monitor.register_callback(monitor.PROFILER_ID,monitor.events.PY_START,on_start)
    monitor.set_events(monitor.PROFILER_ID,monitor.events.PY_START)


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
        payload = [sorted(used),sorted(dirs)]
        if capture_functions:
            payload.append(sorted(calls))
        json.dump(payload,f,separators=(",",":"))


sys.addaudithook(observe)
atexit.register(flush)
multiprocessing.util.Finalize(None,flush,exitpriority=2)
