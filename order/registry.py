from order.composer import OrderTicketComposer, ORBOrderTicketComposer
from order.validator import ORBLongOrderValidator

ORDER_COMPOSER_REGISTRY: dict[str, type[OrderTicketComposer]] = {
    "orb_order_composer": ORBOrderTicketComposer
}
ORDER_VALIDATOR_REGISTRY = {"orb_long_order_validator": ORBLongOrderValidator}
