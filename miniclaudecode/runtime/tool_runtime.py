"""Central tool execution runtime.

This module will become the single place where AgentLoop invokes tools. The
first version only defines the module boundary; execution logic still lives in
AgentLoop until the runtime is wired in.
"""

from __future__ import annotations


class ToolRuntime:
    """Coordinates validation, permission checks, execution, and tracing."""

    pass

