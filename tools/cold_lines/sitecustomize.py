"""Observe lines and receiver classes in one unmodified test's process tree."""

import atexit
import collections
import json
import multiprocessing.util
import os
import sys
from pathlib import Path

prefix = os.environ["BLAST_SOURCE"] + os.sep
destination = Path(os.environ["BLAST_LINE_DIR"])
monitor = sys.monitoring
tool = monitor.PROFILER_ID
sources = {}
lines = collections.defaultdict(set)
types_seen = set()
constructors = {}


def observe_start(code, offset):
    key = id(code)
    if key in constructors:
        name = constructors[key]
    else:
        filename = code.co_filename
        if not filename.startswith(prefix):
            return monitor.DISABLE
        path = filename[len(prefix) :]
        if not path.startswith(("sqlglot/", "tests/")):
            return monitor.DISABLE
        sources[key] = (code, lines[path])
        monitor.set_local_events(tool, code, monitor.events.LINE)
        if code.co_name not in ("__init__", "__new__") or not code.co_argcount:
            return monitor.DISABLE
        name = code.co_varnames[0]
        constructors[key] = name
    receiver = sys._getframe(1).f_locals.get(name)
    if receiver is not None:
        types_seen.add(receiver if isinstance(receiver, type) else type(receiver))


def observe_line(code, line):
    sources[id(code)][1].add(line)
    return monitor.DISABLE


def flush():
    paths = {}
    for path, observed in lines.items():
        if observed:
            packed = bytearray(max(observed) // 8 + 1)
            for n in observed:
                packed[n // 8] |= 1 << (n % 8)
            paths[path] = packed.hex()
    classes = {
        base.__module__ + "." + base.__qualname__
        for cls in types_seen
        for base in cls.__mro__
        if base.__module__.startswith("sqlglot")
    }
    (destination / f"{os.getpid()}.json").write_text(
        json.dumps([paths, sorted(classes)], separators=(",", ":"))
    )


monitor.use_tool_id(tool, "clean SQLGlot test context")
monitor.register_callback(tool, monitor.events.PY_START, observe_start)
monitor.register_callback(tool, monitor.events.LINE, observe_line)
monitor.set_events(tool, monitor.events.PY_START)
atexit.register(flush)
multiprocessing.util.Finalize(None, flush, exitpriority=2)
