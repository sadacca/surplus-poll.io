from poller.adapters import ADAPTERS, register
from tests.fakes import FakeAdapter


def test_register_adds_to_registry():
    ADAPTERS.clear()
    fake = FakeAdapter("dummy-site")
    register(fake)
    assert ADAPTERS["dummy-site"] is fake
