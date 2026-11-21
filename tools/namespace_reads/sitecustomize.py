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
whole_namespaces = os.environ.get("BLAST_WHOLE_NAMESPACES") == "1"
scratch = Path(os.environ["BLAST_NAMESPACE_DIR"])


def record(obj, key=None):
    cls = obj if isinstance(obj, type) else type(obj)
    if cls not in cache:
        cache[cls] = tuple(
            c.__module__ + "." + c.__qualname__
            for c in cls.__mro__
            if c.__module__.startswith("sqlglot")
        )
    if key is None or whole_namespaces:
        seen[active].update(cache[cls])
    else:
        seen[active].update(name + "." + key for name in cache[cls])


def namespace(obj, key=None):
    value = obj.__dict__
    record(obj, key)
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
    @staticmethod
    def mark_key(node, key):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__dict__"
            and isinstance(key, ast.Constant)
            and isinstance(key.value, str)
        ):
            node.namespace_key = key.value

    def visit_Subscript(self, node):
        self.mark_key(node.value, node.slice)
        return self.generic_visit(node)

    def visit_Compare(self, node):
        if len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)):
            self.mark_key(node.comparators[0], node.left)
        return self.generic_visit(node)

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if node.attr == "__dict__" and isinstance(node.ctx, ast.Load):
            return ast.copy_location(
                ast.Call(
                    ast.Name("_blast_namespace", ast.Load()),
                    [node.value, ast.Constant(getattr(node, "namespace_key", None))],
                    [],
                ),
                node,
            )
        return node

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            self.mark_key(node.func.value, node.args[0])
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
