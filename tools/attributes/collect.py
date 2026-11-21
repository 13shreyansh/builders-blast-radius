import sitecustomize
import sys
import pytest


class Context:
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        sitecustomize.context = item.nodeid
        try:
            yield
        finally:
            sitecustomize.context = ""


if __name__ == "__main__":
    sys.exit(
        pytest.main(
            ["tests", "-q", "-p", "pytest_timeout", "--timeout=100"],
            plugins=[Context()],
        )
    )
