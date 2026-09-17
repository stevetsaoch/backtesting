import queue
from schemas import IBConnectionPoolInfo, IBConnectionInfo


class IBConnectionPool:
    def __init__(self, connection_pool_info: IBConnectionPoolInfo):
        self.connection_pool_info = connection_pool_info
        self.pool: queue.Queue = queue.Queue(maxsize=connection_pool_info.size)
        for cid in range(1, connection_pool_info.size + 1):
            self.pool.put(self._new_connection(cid))
        self.count = self.connection_pool_info.size

    def _new_connection(self, client_id: int):
        ib = IBConnectionInfo(
            host=self.connection_pool_info.host,
            port=self.connection_pool_info.port,
            timeout=self.connection_pool_info.timeout,
            readonly=self.connection_pool_info.readonly,
            client_id=client_id,
        )
        return ib

    def get(self) -> IBConnectionInfo | None:
        try:
            conn_info = self.pool.get_nowait()
            self.count -= 1
            return conn_info
        except queue.Empty:
            return

    def release(self, conn_info: IBConnectionInfo):
        self.pool.put(conn_info)
        self.count += 1


if __name__ == "__main__":
    conn_pool = IBConnectionPool(
        IBConnectionPoolInfo(host="127.0.0.1", port=4002, size=10)
    )
    conn = conn_pool.get()
    print(conn)
