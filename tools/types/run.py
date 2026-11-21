from contextlib import contextmanager
import sys
import pytest
from _pytest.fixtures import FixtureDef
import sitecustomize


@contextmanager
def context(node):
    old = sitecustomize.active
    sitecustomize.active = node
    try:
        yield
    finally:
        sitecustomize.active = old


class Record:
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        with context(item.nodeid):
            yield

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        if fixturedef.scope == "function":
            yield
        else:
            with context("@scope:" + request.node.nodeid):
                yield


original = FixtureDef.finish


def finish(fixturedef, request):
    if fixturedef.scope == "function":
        return original(fixturedef, request)
    with context("@scope:" + request.node.nodeid):
        return original(fixturedef, request)


FixtureDef.finish = finish
if __name__ == "__main__":
    sys.exit(
        pytest.main(
            [
                "tests",
                "-q",
                "-p",
                "pytest_timeout",
                "--timeout=360",
                "-p",
                "no:cacheprovider",
                "--tb=short",
            ],
            plugins=[Record()],
        )
    )
