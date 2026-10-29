from abc import ABC, abstractmethod
from typing import Any, Callable

from pydantic import BaseModel


class NoParams(BaseModel):
    pass


class Query(BaseModel):
    """One lookup a data source offers. name, description and params are what an LLM sees when deciding what to fetch."""
    name: str                       # snake_case, unique within the source
    description: str
    params: type[BaseModel]
    run: Callable[[Any], Any]       # takes a params instance, returns JSON-serializable data


class DataSource(ABC):
    """A provider of data that can inform decisions, e.g. a market database or a news feed."""
    name: str                       # snake_case, prefixes the names of the source's queries
    description: str

    @abstractmethod
    def queries(self) -> list[Query]:
        pass
