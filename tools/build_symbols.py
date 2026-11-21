"""Find plain class and enum references already evaluated by clean class tables."""

import ast
import enum
import gzip
import importlib
import inspect
import json
from pathlib import Path
import subprocess
import sys


def resolve(expr, module):
    if isinstance(expr, ast.Name):
        return vars(module).get(expr.id)
    if isinstance(expr, ast.Attribute):
        parent = resolve(expr.value, module)
        if parent is not None:
            return inspect.getattr_static(parent, expr.attr, None)
    return None


def collect(tree):
    output = {}
    for path in sorted((tree / "sqlglot").rglob("*.py")):
        if path.name == "__main__.py":
            continue
        relative = path.relative_to(tree).as_posix()
        name = relative[:-3].replace("/", ".").removesuffix(".__init__")
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        candidates = set()
        for node in ast.walk(ast.parse(path.read_bytes())):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                value = getattr(statement, "value", None)
                if not isinstance(
                    statement, (ast.Assign, ast.AnnAssign)
                ) or not isinstance(value, ast.Dict):
                    continue
                for element in (*value.keys, *value.values):
                    if isinstance(element, (ast.Name, ast.Attribute)):
                        result = resolve(element, module)
                        if isinstance(result, (enum.Enum, type)):
                            candidates.add(ast.unparse(element))
        if candidates:
            output[relative] = sorted(candidates)
    return output


if __name__ == "__main__":
    tree, out = (Path(arg).resolve() for arg in sys.argv[1:])
    git = ["git", "-C", str(tree)]
    assert (
        subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        == "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
    )
    assert not subprocess.check_output([*git, "status", "--porcelain"])
    sys.path.insert(0, str(tree))
    indexed = collect(tree)
    out.write_bytes(
        gzip.compress(json.dumps(indexed, separators=(",", ":")).encode(), mtime=0)
    )
    print(
        len(indexed),
        "files with",
        sum(map(len, indexed.values())),
        "resolved references",
    )
