from __future__ import annotations

from typing import Any, Protocol


class ParsedBlock(Protocol):
    ordinal: int
    block_type: str
    text: str
    page_no: int | None
    section_path: tuple[str, ...]
    locator: dict[str, Any]

    @property
    def text_hash(self) -> str: ...


class DocumentParser(Protocol):
    contract_version: str
    parser_build: str

    def parse(self, filename: str, media_type: str, content: bytes) -> list[ParsedBlock]: ...
