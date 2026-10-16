import logging
from datetime import datetime
from pathlib import Path

from src.utils.errors import ResultsWriteError

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


class TestLogger:
    """Logs one test run to its own file and to stderr."""

    __test__ = False  # not a pytest test class

    def __init__(self, test_name: str, log_dir: str | Path = "results/logs"):
        self._test_name = test_name
        self._log_dir = Path(log_dir)
        self.log_file = self._log_dir / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{test_name}.log"
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """
        Create the log folder, drop handlers left by an earlier logger with the
        same name, and attach a file handler and a stderr handler.
        """
        logger = logging.getLogger(f"test_{self._test_name}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        self._remove_handlers(logger)
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
        except OSError as exc:
            raise ResultsWriteError(f"cannot create log file in {self._log_dir}: {exc}") from exc
        formatter = logging.Formatter(LOG_FORMAT)
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        return logger

    @staticmethod
    def _remove_handlers(logger: logging.Logger) -> None:
        """Close and detach every handler of the logger."""
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def close(self) -> None:
        """Close and remove the handlers so the log file is released."""
        self._remove_handlers(self.logger)

    def info(self, message: str) -> None:
        """Log at INFO level."""
        self.logger.info(message)

    def error(self, message: str) -> None:
        """Log at ERROR level."""
        self.logger.error(message)

    def debug(self, message: str) -> None:
        """Log at DEBUG level."""
        self.logger.debug(message)

    def warning(self, message: str) -> None:
        """Log at WARNING level."""
        self.logger.warning(message)
