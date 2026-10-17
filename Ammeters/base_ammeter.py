import logging
import random
import socket
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

NotImplementedErrorMsg = "Subclasses must implement this property."

HOST = "127.0.0.1"
ACCEPT_TIMEOUT_S = 0.2

logger = logging.getLogger(__name__)


class AmmeterEmulatorBase(ABC):
    """A TCP ammeter emulator: answers its exact command with a current reading."""

    def __init__(self, port: int, recv_timeout_s: float = 2.0,
                 fault_injector: Callable[[float, threading.Event], bytes | None] | None = None):
        self.port = port
        self.fault_injector = fault_injector
        self.recv_timeout_s = recv_timeout_s
        self.ready = threading.Event()
        self.start_error: OSError | None = None
        self._stop_event = threading.Event()
        random.seed(time.time())  # Seed the random number generator for each instance

    def start_server(self) -> None:
        """
        Starts the server to listen for client requests.
        Runs until stop() is called, handling one client at a time.
        A bind error propagates to the caller.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, self.port))
            s.listen()
            s.settimeout(ACCEPT_TIMEOUT_S)
            self.port = s.getsockname()[1]
            logger.info("%s is running on port %d", self.__class__.__name__, self.port)
            self.ready.set()
            while not self._stop_event.is_set():
                try:
                    conn, addr = s.accept()
                except TimeoutError:
                    continue
                except OSError:
                    logger.exception("accept failed on port %d", self.port)
                    continue
                self._handle_connection(conn, addr)

    def stop(self) -> None:
        """Ask the server loop to end."""
        self._stop_event.set()

    def _handle_connection(self, conn: socket.socket, addr: tuple) -> None:
        """Serve one client; a failure drops this connection but never the server."""
        with conn:
            try:
                conn.settimeout(self.recv_timeout_s)
                if not self._received_command(conn):
                    return
                try:
                    current = self.measure_current()
                    reply = str(current).encode('utf-8')
                    if self.fault_injector is not None:
                        reply = self.fault_injector(current, self._stop_event)
                except Exception:  # a measurement or fault hook must never kill the server
                    logger.exception("measure_current failed for client %s", addr)
                    return
                if reply is None:
                    return
                conn.sendall(reply)
            except TimeoutError:
                logger.warning("client %s did not send a complete command in %s s",
                               addr, self.recv_timeout_s)
            except OSError:
                logger.exception("connection with %s failed", addr)

    def _received_command(self, conn: socket.socket) -> bool:
        """Read until the buffer equals the command; False if it can never match."""
        command = self.get_current_command
        buffer = b""
        while True:
            data = conn.recv(1024)
            if not data:
                return False
            buffer += data
            if buffer == command:
                return True
            if not command.startswith(buffer):
                return False

    @property
    @abstractmethod
    def get_current_command(self) -> bytes:
        """
        This property must be implemented by each subclass to provide the specific
        command to get the current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

    @abstractmethod
    def measure_current(self) -> float:
        """
        This method must be implemented by each subclass to provide the specific
        logic for current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)
