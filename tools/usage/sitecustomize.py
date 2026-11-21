"""Trace resolved reads of values declared on SQLGlot classes."""

import ast
import atexit
import builtins
import collections
import concurrent.futures
import importlib.abc
import importlib.machinery
import json
import multiprocessing.util
import os
from pathlib import Path
import sys

active = ""
root = Path(os.environ["BLAST_USAGE_SCRATCH"])
definitions = json.loads((root / "definitions.json").read_bytes())
names = {name.rpartition(".")[2] for name in definitions}
resolved = {}
contexts = collections.defaultdict(set)
early = collections.defaultdict(set)


def observe(obj, name):
    if not isinstance(name, str) or name not in names:
        return
    cls = obj if isinstance(obj, type) else type(obj)
    key = (cls, name)
    if key not in resolved:
        symbol = None
        for ancestor in cls.__mro__:
            if name in vars(ancestor):
                candidate = (
                    ancestor.__module__ + "." + ancestor.__qualname__ + "." + name
                )
                if candidate in definitions:
                    symbol = candidate
                break
        resolved[key] = symbol
    symbol = resolved[key]
    if symbol:
        if active:
            contexts[symbol].add(active)
        else:
            early[symbol].add(cls.__module__ + "." + cls.__qualname__)


def access(obj, name):
    value = getattr(obj, name)
    observe(obj, name)
    return value


def lookup(fn, obj, name, *default):
    value = fn(obj, name, *default)
    if fn is getattr:
        observe(obj, name)
    return value


class Accesses(ast.NodeTransformer):
    def visit_Attribute(self, node):
        self.generic_visit(node)
        if isinstance(node.ctx, ast.Load) and node.attr in names:
            return ast.copy_location(
                ast.Call(
                    ast.Name("_blast_class_read", ast.Load()),
                    [node.value, ast.Constant(node.attr)],
                    [],
                ),
                node,
            )
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) in (2, 3)
            and not node.keywords
        ):
            return ast.copy_location(
                ast.Call(
                    ast.Name("_blast_class_lookup", ast.Load()),
                    [node.func, *node.args],
                    [],
                ),
                node,
            )
        return node


class Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        tree = Accesses().visit(ast.parse(self.get_data(self.path), filename=self.path))
        return compile(
            ast.fix_missing_locations(tree), self.path, "exec", dont_inherit=True
        )


class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".", 1)[0] not in ("sqlglot", "tests"):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = Loader(fullname, spec.origin)
        return spec


def flush():
    (root / f"events-{os.getpid()}.json").write_text(
        json.dumps(
            [{k: sorted(v) for k, v in table.items()} for table in (contexts, early)],
            separators=(",", ":"),
        )
    )


def job(node, fn, args, kwargs):
    global active
    active = node
    if not getattr(job, "started", False):
        multiprocessing.util.Finalize(None, flush, exitpriority=5)
        job.started = True
    try:
        return fn(*args, **kwargs)
    finally:
        active = ""


builtins._blast_class_read = access
builtins._blast_class_lookup = lookup
sys.meta_path.insert(0, Finder())
atexit.register(flush)
submit = concurrent.futures.ProcessPoolExecutor.submit


def launch(executor, fn, /, *args, **kwargs):
    return submit(executor, job, active, fn, args, kwargs)


concurrent.futures.ProcessPoolExecutor.submit = launch
