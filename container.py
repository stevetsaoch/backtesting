from client import IBConnectionPool
from config import IB_CONFIG, PROJECT_CONFIG
from util import PacingController, RequestIdManager

IB_CONNECTION_POOL = IBConnectionPool(connection_pool_info=IB_CONFIG)
PACING_CONTROLLER = PacingController(cooldown=PROJECT_CONFIG.cooldown)
REQUEST_ID_MANAGER = RequestIdManager()
