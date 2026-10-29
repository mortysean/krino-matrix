from ..data_source import DataSource, Query
from .client import SagaxData, sagax
from .events import EventQueries
from .info import InfoQueries
from .macro import MacroQueries
from .markets import MarketQueries
from .stocks import StockQueries


class SagaxSource(DataSource):
    """The sagax data platform: A-share stocks, indices, ETFs, futures, options, special reports,
    macro indicators, news and research, each group of queries in its own module."""

    name = "sagax"
    description = "China market database"

    def __init__(
        self,
        client: SagaxData | None = None
    ):
        self.client = client or sagax()
        self.groups = [
            StockQueries(self.client),
            MarketQueries(self.client),
            EventQueries(self.client),
            MacroQueries(self.client),
            InfoQueries(self.client),
        ]

    def queries(self) -> list[Query]:
        return [query for group in self.groups for query in group.queries()]
