"""User-facing errors. The CLI prints these without a traceback."""


class DoesItFireError(Exception):
    """An error with a message that tells the user what to do next."""

    exit_code = 2


class BudgetExceeded(DoesItFireError):
    """Raised when --max-cost would be exceeded; carries the partial results."""

    exit_code = 3

    def __init__(self, message: str, results: dict | None = None):
        super().__init__(message)
        self.results = results
