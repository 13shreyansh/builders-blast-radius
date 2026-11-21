"""Verify that literal-only class edits can still initialize on the pinned source."""

import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def smoke():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    path, source, packages, is_package = json.load(sys.stdin)
    base = Path(__file__).resolve().parent
    cache = base / f"import-{sys.version_info.major}{sys.version_info.minor}.zip"
    root = cache if cache.is_file() else base / "source.zip"
    sys.path.insert(0, str(root))
    name = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    seen = []

    class Changed(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, search, target=None):
            if fullname != name:
                return None
            spec = importlib.util.spec_from_loader(
                fullname, self, is_package=is_package
            )
            if is_package:
                spec.submodule_search_locations = [
                    str(root) + "/" + path.rsplit("/", 1)[0]
                ]
            return spec

        def exec_module(self, module):
            module.__file__ = str(root) + "/" + path
            exec(
                compile(source, module.__file__, "exec", dont_inherit=True),
                module.__dict__,
            )
            seen.append(name)

    sys.meta_path.insert(0, Changed())
    importlib.import_module(name)
    for module in packages:
        importlib.import_module(module)
    return 0 if seen == [name] else 1


class Imports:
    def __init__(self):
        self.cache = {}
        self.remaining = 45.0

    def check(self, path, source, receivers, names):
        cache_key = (path, source, tuple(sorted(receivers)))
        if cache_key in self.cache:
            return self.cache[cache_key]
        if self.remaining <= 0:
            return False
        started = time.monotonic()
        modules = set()
        for receiver in receivers:
            parts = receiver.split(".")
            while parts:
                candidate = "/".join(parts)
                if candidate + ".py" in names or candidate + "/__init__.py" in names:
                    modules.add(".".join(parts))
                    break
                parts.pop()
        data = json.dumps(
            [path, source, sorted(modules), path.endswith("/__init__.py")]
        ).encode()

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(Path(__file__).resolve()),
                    "--check",
                ],
                input=data,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd="/tmp",
                env={"HOME": "/tmp", "PATH": os.defpath},
                timeout=min(12.0, self.remaining),
            )
            ok = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        self.remaining -= time.monotonic() - started
        self.cache[cache_key] = ok
        return ok


if __name__ == "__main__":
    sys.exit(smoke())
