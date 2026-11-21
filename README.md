# Blast Radius

This entry uses test dependencies measured on SQLGlot revision `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. It maps original unified-diff line ranges and observed file reads to pytest node IDs. Child process pool tasks use the context of the submitting test. The scheduler evaluates one to eight workers using the durations supplied with each batch.

Build with `docker build --platform linux/amd64 -t blast-radius .`. Mount the contest test manifest at `/data/tests.json` and the patch directory at `/data/commits`. The program writes one JSON object per patch.

## Sources and license

The selector, collector and scheduling code were written for the event and are released under MIT. The dependency index contains measurements from the MIT-licensed SQLGlot source and test suite. SQLGlot is copyright its upstream contributors. The runtime uses the organizer's digest-pinned Python image and the Python standard library. The offline collector uses pytest, pytest-timeout, and coverage.py with the SQLGlot test dependencies. The starter kit supplied the input/output format, image digest and scoring specification.

To rebuild the index, check out the pinned revision in a clean directory. Install the organizer's locked test dependencies plus coverage.py 7.17.4, then run `python tools/build_map.py /path/to/sqlglot /path/to/new-scratch-directory dependencies.json.gz`. The collector requires a passing base suite.
