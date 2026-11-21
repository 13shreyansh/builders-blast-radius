# Blast Radius

This regression-test selector analyzes independent patches against SQLGlot revision `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. It reconstructs patched Python files in memory. Changes to imports, signatures and unfamiliar module structure select the whole manifest. For a change to a class literal, an entry in a passive literal table, or a scalar override whose removal reveals an inherited scalar of the same type, the selector includes tests that read the member, construct its declaring class, or construct a class that consumed it during startup. For values read only while running tests, the index includes direct readers and tests that inspect the owning class namespace. A direct constant-key lookup in a class namespace records the key. Escaped namespaces retain their whole-class readers. The selector follows class fields used to initialize other class fields. Clean import tracing also records consuming class bodies and module globals. It also includes class consumers observed by runtime calls and constructors when built-in modules were first imported in a separate clean interpreter. Missing measurements widen selection to every test group that loaded the file. Before narrowing a class edit, an isolated interpreter imports the changed module and its recorded startup consumers. A failed or timed-out import selects the full manifest. For two or three modules with class-data changes, the probe loads the substitutions together. The selector also includes the tests that loaded all the affected files. Mixed changes to initialization and executable code use the full manifest. Added, removed, invalid and unrecognized files also select the whole manifest.

For a change inside an existing function, the selector combines whole-function line coverage with calls observed when each test starts in its own interpreter. For a local insertion or replacement in a plain existing function, the selector can use the old entry statement when the unchanged surrounding statements and compiled lexical bindings match. Unanchored control-flow changes retain file-wide coverage. Changed decorators, shared execution, import-time effects and unrecognized structure also widen the schedule. Changes to immutable default arguments also include tests that inspected the defining module’s callable metadata. For in-place expression substitutions, the selector combines per-test line coverage from isolated processes with the shared suite. Changes confined to a lambda body use observed calls of that code object. A comparison can exclude a measured context when its recorded operand pairs have the same result before and after the edit. Shared fixture execution and import-time calls keep their broader coverage. Fixture setup and teardown count for every test sharing that fixture's scope. Source-reading tests are included for Python edits. Data changes select measured readers, including subprocesses and shared setup. Any manifest test absent from the measurements is selected.

The scheduler tries one to eight workers. It uses the manifest's integer-millisecond durations and charges two seconds per worker. It fills spare worker time with additional tests, giving priority to modules observed loading the affected files. Build with `docker build --platform linux/amd64 -t blast-radius .` and mount the manifest at `/data/tests.json` and the patches at `/data/commits`.

## Rebuilding the maps

Use a clean checkout at the pinned revision with Python 3.12 or later, the organizer's locked test dependencies and coverage.py 7.17.4. Use a new scratch directory for each collection.

```sh
python tools/build_map.py CHECKOUT COVERAGE_DIR dependencies.json.gz
python tools/build_import_lines.py CHECKOUT COVERAGE_DIR import_lines.json.gz
python tools/build_file_reads.py CHECKOUT MODULE_DIR dependencies.json.gz file_reads.json.gz
python tools/build_item_reads.py CHECKOUT ITEM_DIR dependencies.json.gz item_profiles.json.gz
python tools/build_observers.py CHECKOUT dependencies.json.gz observers.txt
python tools/build_shared.py CHECKOUT COVERAGE_DIR shared.json.gz
python tools/build_operands.py CHECKOUT OPERAND_DIR dependencies.json.gz operands.json.gz
python tools/build_cold_lines.py CHECKOUT COLD_DIR dependencies.json.gz cold_lines.json.gz
python tools/build_class_usage.py CHECKOUT CLASS_DIR dependencies.json.gz class_usage.json.gz
BLAST_WHOLE_NAMESPACES=1 python tools/build_namespace.py CHECKOUT WHOLE_DIR dependencies.json.gz whole_namespaces.json.gz
python tools/build_namespace.py CHECKOUT REFLECTION_DIR dependencies.json.gz namespaces.json.gz whole_namespaces.json.gz
python tools/build_source_observers.py CHECKOUT METADATA_DIR dependencies.json.gz source_observers.json.gz
python tools/build_symbols.py CHECKOUT symbols.json.gz
python tools/build_types.py CHECKOUT TYPE_DIR dependencies.json.gz types.json.gz
python tools/build_shadows.py CHECKOUT class_usage.json.gz shadowed.json.gz
python tools/build_initialization.py CHECKOUT EAGER_DIR class_usage.json.gz initialization.json.gz
```

The first collector runs the suite, records line coverage and traces fixture reads in the parent and its process pool. The second extracts lines executed outside a test. The next two collectors start fresh interpreters for each test module and each individual test. The final collector finds measured contexts that inspect source locations or code objects.

The Docker build downloads Python files from the pinned upstream source archive. It verifies their content digest before placing them in a read-only ZIP file for the selector. The runtime uses the Python standard library.

## Sources and license

The entry code is MIT-licensed. Its dependency maps come from running SQLGlot and its tests, which are also MIT-licensed. The starter kit supplied the input/output protocol, image digest and scoring specification. See LICENSE for the copyright notices.
