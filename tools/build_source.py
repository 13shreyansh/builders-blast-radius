"""Create a read-only source archive from the pinned upstream checkout."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

PIN = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
EXPECTED = "452fef57462d70c340df9007b101887cb22ef2c9e175240885b697e8cc785a28"


def upstream_files():
    url = f"https://github.com/tobymao/sqlglot/archive/{PIN}.tar.gz"
    with urllib.request.urlopen(url, timeout=90) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
        for member in archive:
            path = member.name.partition("/")[2]
            if member.isfile() and path.startswith(("sqlglot/", "tests/")) and path.endswith(".py"):
                yield path, archive.extractfile(member).read()


def local_files(tree):
    names = subprocess.check_output(["git","ls-files","sqlglot","tests"],cwd=tree,text=True).splitlines()
    return [(p,(tree / p).read_bytes()) for p in names if p.endswith(".py")]


def pack(files, output):
    digest = hashlib.sha256()
    with ZipFile(output, "w") as archive:
        for name, raw in sorted(files):
            digest.update(name.encode() + b"\0" + hashlib.sha256(raw).digest())
            info = ZipInfo(name)
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, raw)
    return digest.hexdigest()


if __name__ == "__main__":
    source, output = sys.argv[1:]
    files = upstream_files() if source == "--pinned" else local_files(Path(source))
    actual = pack(files, output)
    if actual != EXPECTED:
        raise ValueError(f"Upstream Python source digest mismatch: {actual}")
