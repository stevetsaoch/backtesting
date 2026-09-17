from psycopg_pool import ConnectionPool
from schemas.config import PostgresConfig


class SyncConnectionPool:
    def __init__(self, config: PostgresConfig):
        self.conn_str = f"dbname={config.database} user={config.username} password={config.password},host={config.host}"
        self.pool = ConnectionPool(
            conninfo=self.conn_str,
            min_size=config.pool_min,
            max_size=config.pool_max,
            check=ConnectionPool.check_connection,
        )
