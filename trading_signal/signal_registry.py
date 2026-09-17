from trading_signal.signal import ORBEntrySignal, ORBExitSignal


SIGNAL_REGISTRY: dict[str, type] = {
    "orb_entry_signal": ORBEntrySignal,
    "orb_exit_signal": ORBExitSignal,
}
