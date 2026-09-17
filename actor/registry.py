from actor.base import BaseCustomActor, BaseCustomActorConfig
from actor.intraday import (
    ConsolidationAndBreakoutIndicatorManageActor,
    ConsolidationAndBreakoutIndicatorManageActorConfig,
)

ACTOR_REGISTRY: dict[str, type[BaseCustomActor]] = {
    "consolidation_and_breakout": ConsolidationAndBreakoutIndicatorManageActor,
}
ACTOR_CONFIG_REGISTRY: dict[str, type[BaseCustomActorConfig]] = {
    "consolidation_and_breakout": ConsolidationAndBreakoutIndicatorManageActorConfig
}
