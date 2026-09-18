import pytest

@pytest.fixture(autouse=True)
def configure_matching_version(request, settings):
    filename = request.node.fspath.basename
    if filename in ("test_freight_matching.py", "test_freight_matching_v2.py"):
        settings.MATCHING_ALGORITHM_VERSION = "v2.1"
    else:
        settings.MATCHING_ALGORITHM_VERSION = "v3.0"
