"""Measure actual class attribute readers, including inherited access and shared fixtures."""

import ast
import collections
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys


def build(tree, scratch, index, output):
    git = ["git", "-C", str(tree)]
    assert (
        subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
        == "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
    )
    assert not subprocess.check_output(git + ["status", "--porcelain"])
    scratch.mkdir(exist_ok=False)
    definitions = {}
    for path in sorted((tree / "sqlglot").rglob("*.py")):
        rel = path.relative_to(tree).as_posix()
        module = rel.removesuffix(".py").replace("/", ".").removesuffix(".__init__")

        def visit(body, prefix):
            for node in body:
                if isinstance(node, ast.ClassDef):
                    visit(node.body, prefix + "." + node.name)
                elif prefix != module and isinstance(node, (ast.Assign, ast.AnnAssign)):
                    for t in (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    ):
                        if isinstance(t, ast.Name):
                            definitions[prefix + "." + t.id] = [
                                rel,
                                node.lineno,
                                node.end_lineno,
                            ]

        visit(ast.parse(path.read_bytes()).body, module)
    (scratch / "definitions.json").write_text(json.dumps(definitions))
    hooks = Path(__file__).resolve().with_name("usage")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(hooks), str(tree)]),
        "BLAST_USAGE_SCRATCH": str(scratch),
        "SKIP_INTEGRATION": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
    }
    subprocess.run(
        [sys.executable, str(hooks / "run.py")], cwd=tree, env=env, check=True
    )
    ids = json.loads(gzip.decompress(index.read_bytes()))["ids"]
    positions = {n: 1 << i for i, n in enumerate(ids)}
    by_name = collections.defaultdict(int)
    early = collections.defaultdict(set)
    for path in scratch.glob("events-*.json"):
        active, startup = json.loads(path.read_bytes())
        for name, contexts in active.items():
            for c in contexts:
                if c.startswith("@scope:") and c not in positions:
                    scope = c.removeprefix("@scope:")
                    positions[c] = sum(
                        1 << i
                        for i, n in enumerate(ids)
                        if not scope
                        or n == scope
                        or n.startswith((scope + "::", scope + "/"))
                    )
                by_name[name] |= positions[c]
        for name, classes in startup.items():
            early[name].update(classes)
    result = {
        name: [*where, hex(by_name[name]), sorted(early[name])]
        for name, where in sorted(definitions.items())
    }
    output.write_bytes(
        gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0)
    )
    print(
        len(definitions),
        "class members;",
        sum(bool(v) for v in by_name.values()),
        "with direct test reads;",
        sum(bool(v) for v in early.values()),
        "with startup reads",
        flush=True,
    )


if __name__ == "__main__":
    build(*(Path(x).resolve() for x in sys.argv[1:]))
