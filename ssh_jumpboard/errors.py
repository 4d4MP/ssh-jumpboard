"""Custom exception types for ssh-jumpboard."""

class ConfigNotInitialized(RuntimeError):
    """Raised when an operation requires configuration but none is available."""


class ValidationError(ValueError):
    """Raised when user input fails validation."""


class AgentUnavailable(RuntimeError):
    """Raised when no SSH agent is available and none can be started."""


class SshNotFound(FileNotFoundError):
    """Raised when the ``ssh`` binary cannot be located."""
