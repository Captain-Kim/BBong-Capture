"""Single-instance handling: a newly started instance replaces any older running one."""
import time

from PyQt5.QtCore import QObject
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

NAME = "BBongCapture-single-instance-v1"


def take_over(timeout=4.0) -> bool:
    """Ask a running instance to quit and wait until it is gone."""
    return _ask_quit(NAME, timeout)


def _ask_quit(name, timeout=4.0) -> bool:
    s = QLocalSocket()
    s.connectToServer(name)
    if not s.waitForConnected(300):
        return False
    s.write(b"quit")
    s.flush()
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    end = time.time() + timeout
    while time.time() < end:
        probe = QLocalSocket()
        probe.connectToServer(name)
        if not probe.waitForConnected(150):
            time.sleep(0.35)          # let the old process finish exiting and free its hotkeys
            return True
        probe.abort()
        time.sleep(0.15)
    return True


class SingleServer(QObject):
    def __init__(self, on_quit):
        super().__init__()
        self.on_quit = on_quit
        QLocalServer.removeServer(NAME)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._conn)
        self.server.listen(NAME)

    def _conn(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        sock.waitForReadyRead(300)
        if bytes(sock.readAll()).strip() == b"quit":
            self.on_quit()
