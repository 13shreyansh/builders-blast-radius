"""Measure the clean SQLGlot suite and write a compressed dependency index."""
import argparse
import collections
import concurrent.futures
from contextlib import contextmanager
import gzip
import json
import multiprocessing.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import coverage
from coverage.numbits import numbits_to_nums
import pytest
from _pytest.fixtures import FixtureDef

PIN = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
active = ""
child = None
reads = collections.defaultdict(set)


def trace_reads(event, args):
    if active and event == "open" and isinstance(args[0], str):
        path = args[0].replace(os.sep, "/")
        base = os.environ["BLAST_SOURCE"] + "/"
        if path.startswith(base):
            path = path[len(base):]
        if path.startswith(("tests/", "sqlglot/")) and not path.endswith((".pyc", ".so")):
            reads[path].add(active)


def tracer(name):
    return coverage.Coverage(source=["sqlglot", "tests"], config_file=False,
                             data_file=os.path.join(os.environ["BLAST_MAP_DIR"], name))


def flush_child():
    child.stop()
    child.save()
    write_reads("reads-" + str(os.getpid()))


def write_reads(name):
    path = Path(os.environ["BLAST_MAP_DIR"]) / name
    path.write_text(json.dumps({p: sorted(ids) for p, ids in reads.items()}))


def covered_job(nodeid, fn, args, kwargs):
    global child, active
    if child is None:
        sys.addaudithook(trace_reads)
        child = tracer("coverage-" + str(os.getpid()))
        child.start()
        multiprocessing.util.Finalize(None, flush_child, exitpriority=5)
    active = nodeid
    child.switch_context(nodeid)
    try:
        return fn(*args, **kwargs)
    finally:
        active = ""


class Tests:
    @contextmanager
    def context(self,name):
        global active
        previous = active
        active = name
        self.parent.switch_context(name)
        try:
            yield
        finally:
            active = previous
            self.parent.switch_context(previous)

    def pytest_collection_finish(self,session):
        nodes = [item.nodeid for item in session.items]
        (Path(os.environ["BLAST_MAP_DIR"])/"collected.json").write_text(json.dumps(nodes))

    @pytest.hookimpl(hookwrapper=True,tryfirst=True)
    def pytest_runtest_protocol(self,item,nextitem):
        with self.context(item.nodeid):
            yield

    @contextmanager
    def fixture(self,fixturedef,request):
        if fixturedef.scope == "function":
            yield
        else:
            with self.context("@scope:" + request.node.nodeid):
                yield

    @pytest.hookimpl(hookwrapper=True,tryfirst=True)
    def pytest_fixture_setup(self,fixturedef,request):
        with self.fixture(fixturedef,request):
            yield


def measure(tree, scratch):
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree, text=True).strip() != PIN:
        raise ValueError("The checkout must be at the pinned revision")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=tree):
        raise ValueError("Start with an unmodified checkout")
    scratch.mkdir(exist_ok=False)
    os.environ.update(BLAST_MAP_DIR=str(scratch), BLAST_SOURCE=str(tree), SKIP_INTEGRATION="0", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    os.chdir(tree)
    sys.path.insert(0, str(tree))
    plugin = Tests()
    plugin.parent = tracer("coverage-parent")
    submit = concurrent.futures.ProcessPoolExecutor.submit

    def submit_job(executor, fn, /, *args, **kwargs):
        return submit(executor, covered_job, active, fn, args, kwargs)

    concurrent.futures.ProcessPoolExecutor.submit = submit_job
    sys.addaudithook(trace_reads)
    finish = FixtureDef.finish
    def scoped_finish(fixturedef,request):
        with plugin.fixture(fixturedef,request):
            return finish(fixturedef,request)
    FixtureDef.finish = scoped_finish
    plugin.parent.start()
    result = pytest.main(["tests", "-q", "-p", "pytest_timeout", "--timeout=360"], plugins=[plugin])
    FixtureDef.finish = finish
    plugin.parent.stop()
    plugin.parent.save()
    write_reads("reads-parent")
    if result != 0:
        raise RuntimeError(f"Base suite exited with {result}")


def export(tree, scratch, output):
    files = collections.defaultdict(dict)
    contexts = set()
    maps = sorted(scratch.glob("coverage-*"))
    for path in maps:
        with sqlite3.connect(path) as db:
            contexts.update(row[0] for row in db.execute("select context from context where context != ''"))
    ids = sorted(json.loads((scratch / "collected.json").read_text()))
    bits = {name: 1 << i for i, name in enumerate(ids)}
    for context in sorted(contexts):
        if context.startswith("@scope:"):
            owner = context.removeprefix("@scope:")
            bits[context] = sum(1 << i for i,node in enumerate(ids)
                                if not owner or node == owner or node.startswith((owner+"::",owner+"/")))
    for path in maps:
        with sqlite3.connect(path) as db:
            query = """select file.path, context.context, numbits from line_bits
                       join file on file_id=file.id join context on context_id=context.id
                       where context.context != ''"""
            for filename, name, lines in db.execute(query):
                rel = Path(filename).relative_to(tree).as_posix()
                table = files[rel]
                bit = bits[name]
                for line in numbits_to_nums(lines):
                    table[line] = table.get(line, 0) | bit
    fixtures = collections.defaultdict(int)
    for path in scratch.glob("reads-*"):
        for name, nodes in json.loads(path.read_text()).items():
            for node in nodes:
                fixtures[name] |= bits.get(node, 0)
    pool = {0: 0}
    def index(mask):
        return pool.setdefault(mask, len(pool))
    rows = {name: [index(lines.get(i, 0)) for i in range(1, max(lines, default=0) + 1)]
            for name, lines in sorted(files.items())}
    fixture_ids = {name: index(mask) for name, mask in sorted(fixtures.items())}
    payload = dict(ids=ids, lines=rows, fixtures=fixture_ids, masks=[hex(mask) for mask in pool])
    output.write_bytes(gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0))
    print(f"{len(maps)} processes, {len(ids)} contexts, {len(rows)} files, {len(fixtures)} fixtures", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("checkout", "scratch", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    tree, scratch, output = [p.resolve() for p in (args.checkout, args.scratch, args.output)]
    measure(tree, scratch)
    export(tree, scratch, output)
