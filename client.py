import queue
from ib_async import IB
from schemas import IBConnectionInfo


class IBConnectionPool:
    def __init__(self, connection_info: IBConnectionInfo):
        self.connection_info = connection_info
        self.pool: queue.Queue = queue.Queue(maxsize=connection_info.size)
        for cid in range(1, connection_info.size + 1):
            self.pool.put(self._new_connection(cid))

    def _new_connection(self, client_id: int):
        ib = IB()
        ib.connect(
            self.connection_info.host,
            self.connection_info.port,
            clientId=client_id,
            timeout=self.connection_info.timeout,
            readonly=self.connection_info.readonly,
        )
        return ib

    def get(self) -> IB | None:
        try:
            conn = self.pool.get_nowait()
            if not conn.isConnected():
                try:
                    conn.disconnect()
                except:
                    pass
                conn = self._new_connection(conn.client.clientId)
            return conn
        except queue.Empty:
            return

    def release(self, conn: IB):
        if conn.isConnected():
            self.pool.put(conn)
        else:
            self.pool.put(self._new_connection(conn.client.clientId))

    def close_all(self):
        while not self.pool.empty():
            conn = self.pool.get_nowait()
            conn.disconnect()


if __name__ == "__main__":
    conn_pool = IBConnectionPool(IBConnectionInfo(host="127.0.0.1", port=4002, size=10))
    conn = conn_pool.get()
