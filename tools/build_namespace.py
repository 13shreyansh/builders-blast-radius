"""Collect per-test reflection dependencies, including fixture scopes and process-pool jobs."""

from collections import defaultdict
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys


def pack(index, output, folders, baseline=None):
    ids = json.loads(gzip.decompress(index.read_bytes()))["ids"]
    contexts = {name: 1 << i for i, name in enumerate(ids)}
    reads = defaultdict(int)
    startup = set()
    for folder in folders:
        for record in sorted(folder.glob("namespaces-*.json")):
            for context, names in json.loads(record.read_bytes()).items():
                if not context:
                    startup.update(names)
                    continue
                if context.startswith("@scope:") and context not in contexts:
                    prefix = context.removeprefix("@scope:")
                    contexts[context] = sum(
                        1 << i
                        for i, name in enumerate(ids)
                        if not prefix
                        or name == prefix
                        or name.startswith((prefix + "::", prefix + "/"))
                    )
                for name in names:
                    reads[name] |= contexts[context]
    if baseline:
        whole, early = json.loads(gzip.decompress(baseline.read_bytes()))
        for owner, mask in whole.items():
            accounted = reads[owner]
            for target, observed in tuple(reads.items()):
                if target.rpartition(".")[0] == owner:
                    accounted |= observed
            reads[owner] |= int(mask, 16) & ~accounted
        for owner in early:
            if not any(
                target == owner or target.rpartition(".")[0] == owner
                for target in startup
            ):
                startup.add(owner)
    result = [
        {name: hex(mask) for name, mask in sorted(reads.items()) if mask},
        sorted(startup),
    ]
    output.write_bytes(
        gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0)
    )
    print(len(result[0]), "observer targets")


def build(tree, scratch, index, output, baseline=None, hooks="namespace_reads"):
    git = ["git", "-C", str(tree)]
    assert (
        subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        == "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
    )
    assert not subprocess.check_output([*git, "status", "--porcelain"])
    scratch.mkdir(exist_ok=False)
    hook_path = Path(__file__).resolve().with_name(hooks)
    env = {
        **os.environ,
        "BLAST_SOURCE": str(tree),
        "BLAST_NAMESPACE_DIR": str(scratch),
        "PYTHONPATH": os.pathsep.join(map(str, (hook_path, tree))),
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "SKIP_INTEGRATION": "0",
    }
    subprocess.run(
        [sys.executable, str(hook_path / "run.py")], cwd=tree, env=env, check=True
    )
    pack(index, output, [scratch], baseline)


if __name__ == "__main__":
    if sys.argv[1] == "--merge":
        index, base, out, *sources = (Path(v).resolve() for v in sys.argv[2:])
        pack(index, out, sources, base)
    else:
        build(*(Path(v).resolve() for v in sys.argv[1:]))
