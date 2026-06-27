from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.datasource.contracts import DatasourceError, ResponseMeta, normalize_beijing_iso


class TdxModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class TdxBar(TdxModel):
    symbol: str
    period: str
    bar_time: str = Field(alias="barTime")
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    provider: str = "tdx"
    received_at: str = Field(alias="receivedAt")

    @property
    def barTime(self) -> str:
        return self.bar_time

    @property
    def receivedAt(self) -> str:
        return self.received_at

    @field_validator("bar_time", "received_at", mode="before")
    @classmethod
    def normalize_time_fields(cls, value: str) -> str:
        normalized = normalize_beijing_iso(value)
        if normalized is None:
            msg = "barTime and receivedAt are required"
            raise ValueError(msg)
        return normalized


class TdxSnapshot(TdxModel):
    symbol: str
    last: float
    open: float
    high: float
    low: float
    last_close: float = Field(alias="lastClose")
    volume: float
    amount: float
    provider: str = "tdx"
    as_of: str = Field(alias="asOf")

    @property
    def lastClose(self) -> float:
        return self.last_close

    @property
    def asOf(self) -> str:
        return self.as_of

    @field_validator("as_of", mode="before")
    @classmethod
    def normalize_as_of(cls, value: str) -> str:
        normalized = normalize_beijing_iso(value)
        if normalized is None:
            msg = "asOf is required"
            raise ValueError(msg)
        return normalized


class TdxBarQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbols: list[str]
    period: str
    start_time: str | None = Field(default=None, alias="startTime")
    end_time: str | None = Field(default=None, alias="endTime")
    count: int | None = None
    include_raw: bool = Field(default=False, alias="includeRaw")

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def normalize_time_filters(cls, value: str | None) -> str | None:
        return normalize_beijing_iso(value)


class TdxSnapshotQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbols: list[str]
    fields: list[str] | None = None
    include_raw: bool = Field(default=False, alias="includeRaw")


class TdxPriceVolumeQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbols: list[str]
    fields: list[str] | None = None
    include_raw: bool = Field(default=False, alias="includeRaw")


class TdxTradingDatesQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    market: str = "SH"
    start_time: str | None = Field(default=None, alias="startTime")
    end_time: str | None = Field(default=None, alias="endTime")
    count: int | None = None


class TdxSecuritiesQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    market: str = "5"


class TdxSecurityInfoQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbols: list[str]
    include_raw: bool = Field(default=True, alias="includeRaw")


class TdxSectorListQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    list_type: int = Field(default=0, alias="listType")


class TdxSecurityRelationsQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbol: str


class TdxIpoInfoQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    ipo_type: int = Field(default=0, alias="ipoType")
    ipo_date: int = Field(default=0, alias="ipoDate")


class TdxShareCapitalQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbol: str
    date_list: list[str] = Field(default_factory=list, alias="dateList")
    count: int = 1
    start_date: str | None = Field(default=None, alias="startDate")
    end_date: str | None = Field(default=None, alias="endDate")


class TdxDividendFactorsQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbol: str
    start_time: str | None = Field(default=None, alias="startTime")
    end_time: str | None = Field(default=None, alias="endTime")


class TdxConvertibleBondInfoQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    symbol: str
    fields: list[str] | None = None
    native_method: Literal["get_kzz_info", "get_cb_info"] = Field(
        default="get_kzz_info",
        alias="nativeMethod",
    )


class TdxTrackingEtfsQueryRequest(TdxModel):
    provider: Literal["tdx", "qmt"] = "tdx"
    index_symbol: str = Field(alias="indexSymbol")


class RawTdxCallRequest(TdxModel):
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class TdxWsMessage(TdxModel):
    type: str
    request_id: str | None = Field(default=None, alias="requestId")
    event_id: str | None = Field(default=None, alias="eventId")
    provider: str = "tdx"
    data: Any | None = None
    meta: ResponseMeta | None = None
    error: DatasourceError | None = None
