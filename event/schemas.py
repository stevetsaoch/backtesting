import enum
import datetime
import pandas as pd
from typing import Literal
from pydantic import BaseModel, ConfigDict, field_serializer


class EventType(str, enum.Enum):
    #
    RECORD_CONDITION = "record_condition"
    RECORD_SIGNAL_RAW_DATA = "record_signal_raw_data"
    CREATE_SIGNAL_RAW_DATA = "create_signal_raw_data"
    CREATE_WATCHLIST = "create_watchlist"
    FORCED_CLOSE_TRIGGERED = "forced_close_triggered"
    EXIT_SIGNAL_TRIGGERED = "exit_signal_triggered"
    RANK_CANDIDATE = "rank_candidate"
    PRE_ORDER_VALIDATION = "pre_order_validation"
    POST_ORDER_VALIDATION = "post_order_validation"
    COMPOSE_ORDER_TICKET = "compose_order_ticket"
    REGISTER_ORDER_TICKET = "register_order_ticket"

    UPDATE_ON_POST_VALIDATION_FAILED = "update_on_post_validation_failed"
    UPDATE_ON_POST_VALIDATION_SUCCEED = "update_on_post_validation_succeed"
    # order
    UPDATE_ON_ORDER_SUBMITTED = "update_on_order_submitted"
    UPDATE_ON_ORDER_ACCEPTED = "update_on_order_accepted"
    UPDATE_ON_ORDER_FILLED = "update_on_order_filled"
    UPDATE_ON_ORDER_PARTIALLY_FILLED = "update_on_order_partially_filled"
    UPDATE_ON_ORDER_MODIFIED = "update_on_order_modified"
    UPDATE_ON_ORDER_CANCELED = "update_on_order_canceled"
    UPDATE_ON_ORDER_REJECTED = "update_on_order_rejected"
    UPDATE_ON_ORDER_EXPIRED = "update_on_order_expired"
    UPDATE_ON_POSITION_OPENED = "update_on_position_opened"
    UPDATE_ON_POSITION_CLOSED = "update_on_position_closed"
    #
    RECORD_ORDER_TICKET = "record_order_ticket"


class EventPayload(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    condition: str | dict | None = None
    result: list | set | dict | bool | None = None
    description: str | None = None
    reference_file_name: str | None = None
    reference_data: pd.DataFrame | None = None


class Event(BaseModel):
    event_type: EventType
    created_at: datetime.datetime
    payload: EventPayload

    model_config = {"use_enum_values": True}

    @field_serializer("payload")
    def serialize_payload(self, payload, _info):
        out = {}
        for k, v in payload.model_dump().items():
            if isinstance(k, enum.Enum):
                out[k.value] = v
            elif isinstance(k, str):
                out[k] = v
            else:
                out[str(k)] = v
        return out
