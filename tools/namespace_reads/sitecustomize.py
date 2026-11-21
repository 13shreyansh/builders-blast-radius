"""Observe whole-namespace access and reflection in the pinned source and tests."""

import ast
import atexit
import builtins
import collections
import concurrent.futures
import importlib.abc
import importlib.machinery
import json
import multiprocessing.util
from pathlib import Path
import os
import sys

active = ""
seen = collections.defaultdict(set)
cache = {}
scratch = Path(os.environ["BLAST_NAMESPACE_DIR"])


def record(obj):
    cls = obj if isinstance(obj, type) else type(obj)
    if cls not in cache:
        cache[cls] = tuple(
            c.__module__ + "." + c.__qualname__
            for c in cls.__mro__
            if c.__module__.startswith("sqlglot")
        )
    seen[active].update(cache[cls])


def namespace(obj):
    value = obj.__dict__
    record(obj)
    return value


def lookup(fn, obj, *args, **kwargs):
    if (
        fn in (vars, dir)
        or getattr(fn, "__module__", "") == "inspect"
        or getattr(fn, "__name__", "") == "__getattribute__"
    ):
        record(obj)
    return fn(obj, *args, **kwargs)


class Reads(ast.NodeTransformer):
    def visit_Attribute(self, node):
        self.generic_visit(node)
        if node.attr == "__dict__" and isinstance(node.ctx, ast.Load):
            return ast.copy_location(
                ast.Call(ast.Name("_blast_namespace", ast.Load()), [node.value], []),
                node,
            )
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        name = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else node.func.id
            if isinstance(node.func, ast.Name)
            else None
        )
        if (
            node.args
            and not isinstance(node.args[0], ast.Starred)
            and name
            in (
                "vars",
                "dir",
                "getmembers",
                "getmembers_static",
                "getattr_static",
                "__getattribute__",
            )
        ):
            return ast.copy_location(
                ast.Call(
                    ast.Name("_blast_reflection", ast.Load()),
                    [node.func, *node.args],
                    node.keywords,
                ),
                node,
            )
        return node


class Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        tree = Reads().visit(ast.parse(self.get_data(self.path), filename=self.path))
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


def save():
    (scratch / f"namespaces-{os.getpid()}.json").write_text(
        json.dumps({k: sorted(v) for k, v in seen.items()})
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


builtins._blast_namespace = namespace
builtins._blast_reflection = lookup
sys.meta_path.insert(0, Finder())
atexit.register(save)
original = concurrent.futures.ProcessPoolExecutor.submit


def submit(executor, fn, /, *args, **kwargs):
    return original(executor, job, active, fn, args, kwargs)


concurrent.futures.ProcessPoolExecutor.submit = submit
