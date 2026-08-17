from typing import Protocol


class Provider(Protocol):
    pass


class FactorProvider(Provider):
    def get_snapshot_intraday_high(self, instrument_id: str) -> float: ...


PROVIDER_REGISTRY = {"factor_provider": FactorProvider}
