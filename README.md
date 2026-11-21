# Blast Radius

This selector chooses regression tests for independent changes to SQLGlot revision `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. It reconstructs each changed Python file and checks whether the edit changes executable code inside an existing function, changes module structure, or prevents compilation. It uses whole-function coverage for body edits. Structural edits use the tests that imported or read the file in fresh processes. Unknown paths and invalid Python select every available test.

The scheduler tries one to eight workers with the manifest's integer-millisecond durations and two-second worker cost. It emits one JSON object per patch. Build with `docker build --platform linux/amd64 -t blast-radius .` and mount the manifest at `/data/tests.json` and the patch directory at `/data/commits`.

## Rebuilding the maps

Use a clean checkout at the pinned revision and the organizer's locked test dependencies, plus coverage.py 7.17.4. Each scratch directory must be new.

1. Run `python tools/build_map.py CHECKOUT COVERAGE_DIR dependencies.json.gz`. It records pytest contexts, file access and process-pool work under the originating test.
2. Run `python tools/build_import_lines.py CHECKOUT COVERAGE_DIR import_lines.json.gz`. Lines executed before or between tests identify functions that can affect collection.
3. Run `python tools/build_file_reads.py CHECKOUT FRESH_DIR dependencies.json.gz file_reads.json.gz`. Each test file gets a fresh interpreter and records the source and fixture paths its process tree opens.

The Docker build downloads Python source from the fixed upstream commit, verifies the content digest, and builds a read-only archive for parsing. The runtime uses the Python standard library.

## Sources and license

The entry code is released under MIT. The shipped maps come from executing the MIT-licensed SQLGlot source and its tests. SQLGlot is copyright its upstream contributors. The starter kit supplied the input/output protocol, image digest and scoring specification. The collectors use pytest, pytest-timeout, coverage.py and SQLGlot's test dependencies during development.
