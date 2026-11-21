"""Precompile verified upstream modules for inexpensive isolated initialization checks."""

from pathlib import Path
import py_compile
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def build(source, output):
    with (
        tempfile.TemporaryDirectory() as temp,
        ZipFile(source) as original,
        ZipFile(output, "w") as target,
    ):
        src = Path(temp) / "module.py"
        pyc = Path(temp) / "module.pyc"
        for name in sorted(original.namelist()):
            if not name.startswith("sqlglot/") or not name.endswith(".py"):
                continue
            src.write_bytes(original.read(name))
            py_compile.compile(
                str(src),
                cfile=str(pyc),
                dfile="/pinned/" + name,
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
            )
            info = ZipInfo(name + "c")
            info.compress_type = ZIP_DEFLATED
            target.writestr(info, pyc.read_bytes())


if __name__ == "__main__":
    build(*(Path(v) for v in sys.argv[1:]))
