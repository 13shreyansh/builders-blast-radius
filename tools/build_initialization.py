"""Measure eager class-field reads in the pinned package and find class-body aliases."""

import ast
from collections import defaultdict
import gzip
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys


def declarations(tree, members):
    """Find uses of earlier sibling bindings, including in copies and derived tables."""
    users = defaultdict(set)
    for path in sorted((tree / "sqlglot").rglob("*.py")):
        relative = path.relative_to(tree).as_posix()
        module = (
            relative.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        )

        def visit_class(node, prefix):
            owner = prefix + "." + node.name
            bound = set()
            for statement in node.body:
                if isinstance(statement, ast.ClassDef):
                    visit_class(statement, owner)
                    continue
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                sinks = [
                    owner + "." + target.id
                    for target in targets
                    if isinstance(target, ast.Name)
                ]
                if statement.value is None:
                    continue
                for use in ast.walk(statement.value):
                    if (
                        isinstance(use, ast.Name)
                        and isinstance(use.ctx, ast.Load)
                        and use.id in bound
                    ):
                        upstream = owner + "." + use.id
                        users[upstream].update(sinks or ["@" + relative])
                bound.update(k.rpartition(".")[2] for k in sinks if k in members)

        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.ClassDef):
                visit_class(node, module)
    return users


def exercise(tree):
    """Include lazily imported built-in modules while no test owns the import."""
    import sitecustomize as hook
    from eager_consumers import Consumers

    scratch = Path(os.environ["BLAST_USAGE_SCRATCH"])
    recorder = Consumers(tree, json.loads((scratch / "definitions.json").read_bytes()))
    recorder.install(hook)
    errors = {}
    for path in sorted((tree / "sqlglot").rglob("*.py")):
        if path.name == "__main__.py":
            continue
        name = path.relative_to(tree).as_posix().removesuffix(".py").replace("/", ".")
        name = name.removesuffix(".__init__")
        try:
            importlib.import_module(name)
        except ImportError as error:
            errors[name] = type(error).__name__
    (scratch / "destinations.json").write_text(
        json.dumps(
            [
                {k: sorted(v) for k, v in group.items()}
                for group in (recorder.fields, recorder.classes, recorder.modules)
            ]
        )
    )
    print(json.dumps(errors, sort_keys=True))


def build(tree, scratch, usage, output):
    pin = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
    assert (
        subprocess.check_output(
            ["git", "-C", str(tree), "rev-parse", "HEAD"], text=True
        ).strip()
        == pin
    )
    assert not subprocess.check_output(
        ["git", "-C", str(tree), "status", "--porcelain"]
    )
    scratch.mkdir(exist_ok=False)
    members = json.loads(gzip.decompress(usage.read_bytes()))
    (scratch / "definitions.json").write_text(
        json.dumps({k: v[:3] for k, v in members.items()})
    )
    hooks = Path(__file__).resolve().with_name("usage")
    env = {
        **os.environ,
        "BLAST_USAGE_SCRATCH": str(scratch),
        "PYTHONPATH": os.pathsep.join(map(str, (hooks, tree))),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--exercise", str(tree)],
        cwd=tree,
        env=env,
        check=True,
    )
    early = defaultdict(set)
    for path in scratch.glob("events-*.json"):
        _, reads = json.loads(path.read_bytes())
        for member, receivers in reads.items():
            early[member].update(receivers)
    users = declarations(tree, members)
    sinks, classes, modules = json.loads((scratch / "destinations.json").read_bytes())
    for key, values in sinks.items():
        users[key].update(value for value in values if value != key)
    result = [
        {k: sorted(s) for k, s in sorted(g.items())}
        for g in (early, users, classes, modules)
    ]
    output.write_bytes(
        gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0)
    )
    print(
        len(early),
        "initialization dependencies;",
        sum(map(len, users.values())),
        "sibling dependencies",
    )


if __name__ == "__main__":
    if sys.argv[1] == "--exercise":
        exercise(Path(sys.argv[2]))
    else:
        build(*(Path(s).resolve() for s in sys.argv[1:]))
