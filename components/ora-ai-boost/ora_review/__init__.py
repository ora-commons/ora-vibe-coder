"""Standalone Ora adversarial review and external validation."""

from .adapters import ANALYTICAL_ENGINES
from .runner import ReviewRunner, RunRequest, RunResult

#: Release identity of this copy. Kept in step with ``pyproject.toml``.
VERSION = "0.3.0"

#: This component's machine-readable facts: its identity and version, the
#: analytical roles each of the six tools can hold, which engines keep a
#: native adapter, and the Agent Bridge transport it requires (Format 2 and
#: the ``check``/``record``/``run`` actions it invokes). Hermes, Qwen and
#: MiniMax hold analytical roles only; no project-editing work mode is
#: claimed or implemented for them.
COMPONENT_FACTS = {
    "component": "ora-adversarial-review",
    "version": VERSION,
    "analytical_roles": {
        "primary": ANALYTICAL_ENGINES,
        "peer": ANALYTICAL_ENGINES,
    },
    "native_adapter_engines": ("codex", "claude"),
    "bridge_transport": {
        "format": 2,
        "actions": ("check", "record", "run"),
    },
}

__all__ = [
    "ANALYTICAL_ENGINES",
    "COMPONENT_FACTS",
    "ReviewRunner",
    "RunRequest",
    "RunResult",
    "VERSION",
]
