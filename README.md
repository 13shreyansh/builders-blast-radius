# Blast Radius

This regression-test selector analyzes independent patches against SQLGlot revision `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. It reconstructs patched Python files in memory. Changes to imports, class settings, signatures and other module structure select the whole manifest. Added, removed, invalid and unrecognized files also select the whole manifest.

For a change inside an existing function, the selector combines whole-function line coverage with calls observed when each test starts in its own interpreter. Fixture setup and teardown count for every test sharing that fixture's scope. Source-reading tests are included for Python edits. Data changes select measured readers, including subprocesses and shared setup. Any manifest test absent from the measurements is selected.

The scheduler tries one to eight workers. It uses the manifest's integer-millisecond durations and charges two seconds per worker. Build with `docker build --platform linux/amd64 -t blast-radius .` and mount the manifest at `/data/tests.json` and the patches at `/data/commits`.

## Rebuilding the maps

Use a clean checkout at the pinned revision with Python 3.12 or later, the organizer's locked test dependencies and coverage.py 7.17.4. Use a new scratch directory for each collection.

```sh
python tools/build_map.py CHECKOUT COVERAGE_DIR dependencies.json.gz
python tools/build_import_lines.py CHECKOUT COVERAGE_DIR import_lines.json.gz
python tools/build_file_reads.py CHECKOUT MODULE_DIR dependencies.json.gz file_reads.json.gz
python tools/build_item_reads.py CHECKOUT ITEM_DIR dependencies.json.gz item_profiles.json.gz
python tools/build_observers.py CHECKOUT dependencies.json.gz observers.txt
```

The first collector runs the suite, records line coverage and traces fixture reads in the parent and its process pool. The second extracts lines executed outside a test. The next two collectors start fresh interpreters for each test module and each individual test. The final collector finds measured contexts that inspect source locations or code objects.

The Docker build downloads Python files from the pinned upstream source archive. It verifies their content digest before placing them in a read-only ZIP file for the selector. The runtime uses the Python standard library.

## Sources and license

The entry code is MIT-licensed. Its dependency maps come from running SQLGlot and its tests, which are also MIT-licensed. The starter kit supplied the input/output protocol, image digest and scoring specification. See LICENSE for the copyright notices.
