from psycopg_pool import PoolTimeout
from database.connection import SyncConnectionPool
from config import POSTGRES_CONFIG

SYNC_CONN_POOL = SyncConnectionPool(POSTGRES_CONFIG).pool

try:
    SYNC_CONN_POOL.wait(timeout=3)
except PoolTimeout:
    pass
