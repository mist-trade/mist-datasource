"""Unit tests for QmtCommandGateway busy_until lease extension (task 1.3)."""

from src.datasource.qmt.realtime.gateway import QmtCommandGateway


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_gateway(clock: FakeClock, stale_after: float = 15.0) -> QmtCommandGateway:
    return QmtCommandGateway(clock=clock, owner_stale_after_seconds=stale_after)


def test_owner_fresh_within_threshold_without_busy_until():
    clock = FakeClock()
    gateway = make_gateway(clock)
    gateway.register_owner("bridge-a")
    gateway.heartbeat("bridge-a")
    clock.advance(10)
    assert gateway.health()["ownerStale"] is False


def test_owner_stale_after_threshold_without_busy_until():
    clock = FakeClock()
    gateway = make_gateway(clock)
    gateway.register_owner("bridge-a")
    gateway.heartbeat("bridge-a")
    clock.advance(16)
    assert gateway.health()["ownerStale"] is True


def test_in_flight_long_command_extends_lease_deadline():
    clock = FakeClock()
    gateway = make_gateway(clock)
    gateway.register_owner("bridge-a")
    gateway.heartbeat("bridge-a")
    # Simulate an in-flight 600s admin call issued now.
    gateway.extend_busy_until(600)
    clock.advance(30)
    # Heartbeat is 30s stale (> 15s) but busy_until covers the in-flight window.
    assert gateway.health()["ownerStale"] is False


def test_owner_stale_after_busy_until_expires():
    clock = FakeClock()
    gateway = make_gateway(clock)
    gateway.register_owner("bridge-a")
    gateway.heartbeat("bridge-a")
    gateway.extend_busy_until(600)
    clock.advance(700)
    assert gateway.health()["ownerStale"] is True


def test_extend_busy_until_takes_max_of_deadlines():
    clock = FakeClock()
    gateway = make_gateway(clock)
    gateway.register_owner("bridge-a")
    gateway.extend_busy_until(600)
    # A shorter extension must not shorten the existing deadline.
    gateway.extend_busy_until(10)
    clock.advance(60)
    assert gateway.health()["ownerStale"] is False


def test_stale_owner_replacement_still_works_after_busy_until_expiry():
    clock = FakeClock()
    gateway = make_gateway(clock)
    gateway.register_owner("bridge-a")
    gateway.extend_busy_until(600)
    clock.advance(700)
    # Old owner is stale → a new bridge generation can take over.
    owner = gateway.register_owner("bridge-b")
    assert owner.owner_id == "bridge-b"
    assert owner.generation == 2
