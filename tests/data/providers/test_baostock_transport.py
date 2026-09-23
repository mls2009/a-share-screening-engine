import pytest

from astock.data.providers.baostock_transport import GuardedSocket


class Socket:
    def __init__(self, data):
        self.data = iter(data)
        self.sent = []

    def recv(self, size):
        return next(self.data)

    def sendall(self, payload):
        self.sent.append(payload)


def test_eof_raises_instead_of_allowing_sdk_infinite_receive_loop():
    transport = GuardedSocket(Socket([b"header", b""]))
    assert transport.recv(8192) == b"header"
    with pytest.raises(ConnectionError, match="关闭"):
        transport.recv(8192)


def test_sdk_send_transmits_complete_message():
    sock = Socket([])
    assert GuardedSocket(sock).send(b"query") == 5
    assert sock.sent == [b"query"]


def test_transport_restores_sdk_hook_and_closes_socket_on_failure(monkeypatch):
    from baostock.common import context
    from baostock.util import socketutil

    from astock.data.providers import baostock_transport as transport

    class Closable(Socket):
        closed = False

        def close(self):
            self.closed = True

    sock = Closable([])
    opened = []

    def connect(address, timeout):
        opened.append(timeout)
        return sock

    monkeypatch.setattr(transport, "create_connection", connect)
    original = socketutil.SocketUtil.connect
    with pytest.raises(RuntimeError), transport.bounded_transport():
        socketutil.SocketUtil().connect()
        assert isinstance(context.default_socket, GuardedSocket)
        raise RuntimeError("login failed")
    assert sock.closed
    assert opened == [20]
    assert context.default_socket is None
    assert socketutil.SocketUtil.connect is original
