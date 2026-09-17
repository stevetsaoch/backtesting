from trading_signal.manager import ORBSignalManager

SIGNAL_MANAGER_REGISTRY: dict[str, type] = {"orb_signal_manager": ORBSignalManager}
