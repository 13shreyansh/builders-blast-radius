"""Observe comparison operands while running tests on the pinned tree."""

import ast
import atexit
import builtins
import concurrent.futures
import importlib.abc
import importlib.machinery
import multiprocessing.util
import os
from pathlib import Path
import sys
import operands

context = ""
scratch = Path(os.environ["BLAST_ATTR_SCRATCH"])


def flush():
    operands.save(scratch / f"operands-{os.getpid()}.json")


def compare(site, name, left, right):
    return operands.compare(context, site, name, left, right)


class Comparisons(ast.NodeTransformer):
    def __init__(self, filename):
        self.path = os.path.relpath(filename, os.environ["BLAST_SOURCE"])

    def visit_Compare(self, node):
        self.generic_visit(node)
        name = type(node.ops[0]).__name__
        if len(node.ops) == 1 and name in operands.OPS:
            site = f"{self.path}:{node.lineno}:{node.col_offset}"
            new = ast.Call(
                ast.Name("_blast_base_compare", ast.Load()),
                [
                    ast.Constant(site),
                    ast.Constant(name),
                    node.left,
                    node.comparators[0],
                ],
                [],
            )
            return ast.copy_location(new, node)
        return node


class Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        source = self.get_data(self.path)
        visitor = Comparisons(self.path)
        tree = visitor.visit(ast.parse(source, filename=self.path))
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


def run_job(node, fn, args, kwargs):
    global context
    context = node
    if not getattr(run_job, "started", False):
        multiprocessing.util.Finalize(None, flush, exitpriority=5)
        run_job.started = True
    try:
        return fn(*args, **kwargs)
    finally:
        context = ""


def setup():
    builtins._blast_base_compare = compare
    sys.meta_path.insert(0, Finder())
    atexit.register(flush)
    original = concurrent.futures.ProcessPoolExecutor.submit

    def submit(executor, fn, /, *args, **kwargs):
        return original(executor, run_job, context, fn, args, kwargs)

    concurrent.futures.ProcessPoolExecutor.submit = submit


setup()
