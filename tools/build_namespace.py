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
    hooks = Path(__file__).resolve().with_name("namespace_reads")
    env = {
        **os.environ,
        "BLAST_SOURCE": str(tree),
        "PYTHONPATH": os.pathsep.join([str(hooks), str(tree)]),
        "BLAST_NAMESPACE_DIR": str(scratch),
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
    contexts = {n: 1 << i for i, n in enumerate(ids)}
    classes = collections.defaultdict(int)
    outside = set()
    for p in scratch.glob("namespaces-*.json"):
        for c, names in json.loads(p.read_bytes()).items():
            if not c:
                outside.update(names)
                continue
            if c.startswith("@scope:") and c not in contexts:
                prefix = c.removeprefix("@scope:")
                contexts[c] = sum(
                    1 << i
                    for i, n in enumerate(ids)
                    if not prefix
                    or n == prefix
                    or n.startswith((prefix + "::", prefix + "/"))
                )
            for name in names:
                classes[name] |= contexts[c]
    output.write_bytes(
        gzip.compress(
            json.dumps(
                [{k: hex(v) for k, v in sorted(classes.items())}, sorted(outside)],
                separators=(",", ":"),
            ).encode(),
            mtime=0,
        )
    )
    print(len(classes), "namespace observers", flush=True)


if __name__ == "__main__":
    build(*(Path(x).resolve() for x in sys.argv[1:]))
