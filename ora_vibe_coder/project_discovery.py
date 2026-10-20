"""Isolated filesystem reader, owned and stopped by one project scan."""

from .project import _inventory_reader


if __name__ == "__main__":
    _inventory_reader()
