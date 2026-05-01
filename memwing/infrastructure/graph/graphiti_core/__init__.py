from typing import Any

__all__ = ['Graphiti']


def __getattr__(name: str) -> Any:
    if name == 'Graphiti':
        from .graphiti import Graphiti

        return Graphiti
    raise AttributeError(name)
