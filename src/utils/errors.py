"""Exception types shared by the whole framework."""


class AmmeterFrameworkError(Exception):
    """Base class of every error the framework raises on purpose."""


class AmmeterConnectionError(AmmeterFrameworkError):
    """The ammeter could not be reached or the connection broke."""


class AmmeterTimeoutError(AmmeterFrameworkError):
    """The ammeter did not answer in time."""


class InvalidResponseError(AmmeterFrameworkError):
    """The ammeter answered with something that is not a reading."""


class EmptyResponseError(InvalidResponseError):
    """The ammeter closed the connection without sending data."""


class NonNumericResponseError(InvalidResponseError):
    """The ammeter replied with text that is not a finite number."""


class ConfigError(AmmeterFrameworkError):
    """The configuration is missing, unreadable or invalid."""


class EmulatorStartError(AmmeterFrameworkError):
    """A managed emulator did not start."""


class ResultsError(AmmeterFrameworkError):
    """Base class of result archive and log folder errors."""


class ResultsWriteError(ResultsError):
    """A result or log file could not be written."""


class ResultsNotFoundError(ResultsError):
    """A requested run does not exist."""


class ResultsCorruptError(ResultsError):
    """A stored run cannot be read back."""
