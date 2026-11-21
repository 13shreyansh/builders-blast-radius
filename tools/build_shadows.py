"""Find scalar class overrides that reveal another scalar binding when removed."""

import gzip
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

PIN = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


def measure(tree, usage, out):
    members = json.loads(gzip.decompress(usage.read_bytes()))
    eligible = []
    for symbol, row in members.items():
        module = row[0].removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        relative = symbol.removeprefix(module + ".").split(".")
        try:
            owner = importlib.import_module(module)
            for part in relative[:-1]:
                owner = vars(owner)[part]
        except (ImportError, KeyError):
            continue
        if not isinstance(owner, type):
            continue
        name = relative[-1]
        if name not in vars(owner) or type(vars(owner)[name]) not in (
            bool,
            str,
            int,
            float,
            type(None),
        ):
            continue
        ancestor = next(
            (base for base in owner.__mro__[1:] if name in vars(base)), None
        )
        if ancestor is not None and type(vars(ancestor)[name]) is type(
            vars(owner)[name]
        ):
            eligible.append(symbol)
    out.write_bytes(
        gzip.compress(
            json.dumps(sorted(eligible), separators=(",", ":")).encode(), mtime=0
        )
    )
    print(len(eligible), "scalar overrides with matching inherited types")


if __name__ == "__main__":
    args = [Path(p).resolve() for p in sys.argv[-3:]]
    tree = args[0]
    if len(sys.argv) == 5 and sys.argv[1] == "--measure":
        measure(*args)
    else:
        git = ["git", "-C", str(tree)]
        assert (
            subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
            == PIN
        )
        assert not subprocess.check_output(git + ["status", "--porcelain"])
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--measure",
                *map(str, args),
            ],
            cwd=tree,
            check=True,
            env={**os.environ, "PYTHONPATH": str(tree), "PYTHONDONTWRITEBYTECODE": "1"},
        )
