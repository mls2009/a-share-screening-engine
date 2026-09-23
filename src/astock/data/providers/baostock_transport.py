"""Bound BaoStock's socket operations and turn remote EOF into an explicit failure."""

from contextlib import contextmanager
from socket import create_connection

from baostock.common import context
from baostock.util import socketutil


class GuardedSocket:
    def __init__(self, socket):
        self.socket = socket

    def send(self, payload):
        self.socket.sendall(payload)
        return len(payload)

    def recv(self, size):
        data = self.socket.recv(size)
        if not data:
            raise ConnectionError("BaoStock 服务器已关闭连接，请稍后重试")
        return data

    def __getattr__(self, name):
        return getattr(self.socket, name)


@contextmanager
def bounded_transport():
    # Caller holds BAOSTOCK_SESSION_LOCK for the entire SDK session.
    original = socketutil.SocketUtil.connect
    opened = []

    def connect(_):
        socket = create_connection(
            (socketutil.cons.BAOSTOCK_SERVER_IP, socketutil.cons.BAOSTOCK_SERVER_PORT),
            timeout=20,
        )
        opened.append(socket)
        context.default_socket = GuardedSocket(socket)

    socketutil.SocketUtil.connect = connect
    try:
        yield
    finally:
        socketutil.SocketUtil.connect = original
        for socket in opened:
            socket.close()
        context.default_socket = None
