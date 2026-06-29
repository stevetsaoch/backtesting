import queue
from ib_async import IB
from pydantic import BaseModel


class ConnectionInfo(BaseModel):
    host: str
    port: int
    timeout: int = 5
    readonly: bool = True


class ConnectionPool:
    def __init__(self, connection_info: ConnectionInfo, size=32):
        self.pool: queue.Queue = queue.Queue(maxsize=size)
        self.connection_info = connection_info
        for cid in range(1, size + 1):
            print(cid)
            self.pool.put(self._new_connection(cid))
            print(cid)

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

    def get(self):
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
            pass

    def release(self, conn):
        if conn.isConnected():
            self.pool.put(conn)
        else:
            self.pool.put(self._new_connection(conn.client.clientId))

    def close_all(self):
        while not self.pool.empty():
            conn = self.pool.get_nowait()
            conn.disconnect()


if __name__ == "__main__":
    conn_pool = ConnectionPool(ConnectionInfo(host="127.0.0.1", port=4002))
    conn = conn_pool.get()
