from typing import Protocol


class Validator(Protocol):
    pass


class OrderValidator(Validator):
    pass


VALIDATOR_REGISTRY = {"order_validator": OrderValidator}
