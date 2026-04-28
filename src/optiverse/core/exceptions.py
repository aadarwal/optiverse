"""
Custom exceptions for Optiverse.

This module defines domain-specific exceptions for better error handling
and more informative error messages.

Usage:
    from optiverse.core.exceptions import (
        OptiverseError,
        SerializationError,
        ComponentLoadError,
    )

    try:
        component = load_component(path)
    except ComponentLoadError as e:
        logger.error(f"Failed to load component: {e}")
"""

from __future__ import annotations


class OptiverseError(Exception):
    """Base exception for all Optiverse errors."""

    def __init__(self, message: str, context: str | None = None):
        self.message = message
        self.context = context
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.context:
            return f"{self.message} (context: {self.context})"
        return self.message


# =============================================================================
# Serialization Errors
# =============================================================================


class SerializationError(OptiverseError):
    """Base class for serialization-related errors."""

    pass


class ComponentLoadError(SerializationError):
    """Raised when a component cannot be loaded from disk."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to load component from '{path}': {reason}", context=path)


class ComponentSaveError(SerializationError):
    """Raised when a component cannot be saved to disk."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to save component to '{path}': {reason}", context=path)


class AssemblyLoadError(SerializationError):
    """Raised when an assembly file cannot be loaded."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to load assembly from '{path}': {reason}", context=path)


class AssemblySaveError(SerializationError):
    """Raised when an assembly file cannot be saved."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to save assembly to '{path}': {reason}", context=path)


class UnknownTypeError(SerializationError):
    """Raised when encountering an unknown item type during deserialization."""

    def __init__(self, type_name: str):
        self.type_name = type_name
        super().__init__(f"Unknown item type: '{type_name}'", context=f"type={type_name}")
