"""Shared version utility for Tokenxygen."""

from importlib.metadata import version, PackageNotFoundError


def get_version() -> str:
    """Get package version from metadata."""
    try:
        return version("tokenxygen")
    except PackageNotFoundError:
        return "0.5.1"
