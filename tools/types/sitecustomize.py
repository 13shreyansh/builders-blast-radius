"""Record concrete SQLGlot class objects and receivers passed through clean calls."""

import atexit
import collections
import concurrent.futures
import json
import multiprocessing.util
import os
from pathlib import Path
import sys

prefix = os.environ["BLAST_SOURCE"] + os.sep
dest = Path(os.environ["BLAST_TYPES_SCRATCH"])
active = ""
contexts = collections.defaultdict(set)
classes = {}
m = sys.monitoring
tool = m.PROFILER_ID


def start(code, offset):
    if code.co_filename.startswith((prefix + "sqlglot/", prefix + "tests/")):
        m.set_local_events(tool, code, m.events.CALL)
    return m.DISABLE


def remember(cls):
    if cls not in classes:
        classes[cls] = tuple(
            a.__module__ + "." + a.__qualname__
            for a in cls.__mro__
            if a.__module__.startswith("sqlglot")
        )
    names = classes[cls]
    if names:
        contexts[active].update(names)


def call(code, offset, fn, first):
    if active:
        if isinstance(fn, type):
            remember(fn)
        remember(first if isinstance(first, type) else type(first))


def save():
    (dest / f"types-{os.getpid()}.json").write_text(
        json.dumps({k: sorted(v) for k, v in contexts.items()}, separators=(",", ":"))
    )


def job(node, fn, args, kwargs):
    global active
    active = node
    if not getattr(job, "started", False):
        multiprocessing.util.Finalize(None, save, exitpriority=5)
        job.started = True
    try:
        return fn(*args, **kwargs)
    finally:
        active = ""


m.use_tool_id(tool, "clean type dependencies")
m.register_callback(tool, m.events.PY_START, start)
m.register_callback(tool, m.events.CALL, call)
m.set_events(tool, m.events.PY_START)
atexit.register(save)
original = concurrent.futures.ProcessPoolExecutor.submit


def submit(executor, fn, /, *args, **kwargs):
    return original(executor, job, active, fn, args, kwargs)


concurrent.futures.ProcessPoolExecutor.submit = submit
