"""Typed, validated request parameters for every RPC method (rules.md §2.6)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ItemId = str


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=16 * 1024 * 1024)


class HealthParams(Params):
    protocol_version: int | None = None


class Empty(Params):
    pass


class ImportTextParams(Params):
    text: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=200)


class ImportPathsParams(Params):
    paths: list[str] = Field(min_length=1, max_length=10_000)


class ItemRef(Params):
    item_id: ItemId = Field(pattern=r"^[0-9a-f-]{36}$")


class ListItemsParams(Params):
    status: (
        list[Literal["queued", "processing", "indexed", "failed", "skipped", "deleting", "deleted"]]
        | None
    ) = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class SearchFiltersParams(Params):
    source_types: list[Literal["text", "clipboard", "file", "screenshot", "image", "audio"]] = []
    captured_after: str | None = Field(default=None, max_length=40)
    captured_before: str | None = Field(default=None, max_length=40)
    app: str | None = Field(default=None, max_length=200)
    path_prefix: str | None = Field(default=None, max_length=4096)


class SearchParams(Params):
    query: str = Field(max_length=20_000)
    filters: SearchFiltersParams = SearchFiltersParams()
    limit: int | None = Field(default=None, ge=1, le=200)


class ClearParams(Params):
    confirm: Literal[True]


class SettingsUpdateParams(Params):
    changes: dict[str, Any]


class ModelRef(Params):
    model_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")


class ModelFileParams(ModelRef):
    path: str = Field(min_length=1, max_length=4096)


CaptureSource = Literal["clipboard", "screenshot"]


class CaptureSourceParams(Params):
    source_type: CaptureSource
    enabled: bool | None = None
    paused: bool | None = None


class CapturePauseParams(Params):
    paused: bool


class ClipboardCaptureParams(Params):
    # Oversized copies are measured and dropped by the engine, so the field
    # allows more than the clipboard limit; the protocol caps the message.
    text: str = Field(min_length=1)
    app: str | None = Field(default=None, max_length=256)
    app_known: bool = False


class ExclusionAddParams(Params):
    # Folder rules come only from the shell's folder dialog (exclusions.add_path).
    rule_type: Literal["app", "pattern"]
    rule_value: str = Field(min_length=1, max_length=500)


class ExclusionPathParams(Params):
    rule_type: Literal["path"]
    rule_value: str = Field(min_length=1, max_length=4096)


class ExclusionUpdateParams(Params):
    id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    enabled: bool


class ExclusionRef(Params):
    id: str = Field(pattern=r"^[0-9a-f-]{36}$")


class ExportParams(Params):
    path: str = Field(min_length=1, max_length=4096)
