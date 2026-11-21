"""Attribute inspections that can observe changes without calling the edited function."""

import ast
import atexit
import builtins
from collections import defaultdict
import concurrent.futures
import importlib.abc
import importlib.machinery
import json
import multiprocessing.util
import os
from pathlib import Path
import sys
import types

active = ""
seen = defaultdict(set)
root = Path(os.environ["BLAST_SOURCE"]).resolve()
scratch = Path(os.environ["BLAST_NAMESPACE_DIR"])
FIELDS = {
    "__code__",
    "__doc__",
    "__defaults__",
    "__kwdefaults__",
    "__annotations__",
    "co_code",
    "co_consts",
    "co_names",
    "co_firstlineno",
    "co_positions",
    "co_lines",
    "co_linetable",
    "co_filename",
    "tb_lineno",
    "f_lineno",
    "f_code",
}
INSPECT = {
    "getsource",
    "getsourcefile",
    "getsourcelines",
    "getdoc",
    "getfile",
    "getframeinfo",
    "signature",
    "getfullargspec",
    "get_annotations",
}


def record(obj):
    if isinstance(obj, types.MethodType):
        obj = obj.__func__
    if isinstance(obj, types.FunctionType):
        obj = obj.__code__
    if isinstance(obj, types.TracebackType):
        obj = obj.tb_frame
    if isinstance(obj, types.FrameType):
        obj = obj.f_code
    if isinstance(obj, types.CodeType):
        path = obj.co_filename
    else:
        if isinstance(obj, types.ModuleType):
            module = obj
        else:
            cls = obj if isinstance(obj, type) else type(obj)
            module = sys.modules.get(cls.__module__)
        path = (
            vars(module).get("__file__")
            if isinstance(module, types.ModuleType)
            else None
        )
    if not path:
        seen[active].add("*")
        return
    try:
        relative = Path(path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError, TypeError):
        # An external object can still wrap source in the checkout.
        seen[active].add("*")
        return
    seen[active].add(relative)


def observed(obj):
    record(obj)
    return obj


def lookup(fn, obj, name, *rest):
    if fn in (getattr, hasattr) and isinstance(name, str) and name in FIELDS:
        record(obj)
    return fn(obj, name, *rest)


class Reads(ast.NodeTransformer):
    def wrap(self, node):
        return ast.copy_location(
            ast.Call(ast.Name("_blast_observed", ast.Load()), [node], []), node
        )

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if node.attr in FIELDS and isinstance(node.ctx, ast.Load):
            node.value = self.wrap(node.value)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in {"getattr", "hasattr"}:
            if len(node.args) in (2, 3) and not node.keywords:
                return ast.copy_location(
                    ast.Call(
                        ast.Name("_blast_metadata_lookup", ast.Load()),
                        [node.func, *node.args],
                        [],
                    ),
                    node,
                )
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in INSPECT and node.args and not isinstance(node.args[0], ast.Starred):
            node.args[0] = self.wrap(node.args[0])
        return node


class Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        tree = Reads().visit(ast.parse(self.get_data(self.path), filename=self.path))
        return compile(
            ast.fix_missing_locations(tree), self.path, "exec", dont_inherit=True
        )


class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".", 1)[0] not in {"sqlglot", "tests"}:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = Loader(fullname, spec.origin)
        return spec


def save():
    (scratch / f"namespaces-{os.getpid()}.json").write_text(
        json.dumps({ctx: sorted(files) for ctx, files in seen.items()})
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


builtins._blast_observed = observed
builtins._blast_metadata_lookup = lookup
sys.meta_path.insert(0, Finder())
atexit.register(save)
original = concurrent.futures.ProcessPoolExecutor.submit


def submit(executor, fn, /, *args, **kwargs):
    return original(executor, job, active, fn, args, kwargs)


concurrent.futures.ProcessPoolExecutor.submit = submit
