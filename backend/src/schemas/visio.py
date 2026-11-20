"""
Schemas for the read-only Visio (.vsdx) viewer.

The file never leaves the request: VSDX is parsed into an SVG string per page
and returned to the browser for display only. Nothing is stored.
"""
from typing import List

from pydantic import BaseModel, Field


class VsdxPage(BaseModel):
    """One Visio page rendered as a standalone SVG document."""

    index: int = Field(..., description="Zero-based page position in the document")
    name: str = Field("", description="Page name as shown in Visio")
    width: float = Field(..., description="Page width in px (96 px per inch)")
    height: float = Field(..., description="Page height in px (96 px per inch)")
    shape_count: int = Field(0, description="Number of shapes rendered on this page")
    svg: str = Field(..., description="Complete SVG markup for this page")


class VsdxParseResponse(BaseModel):
    """Read-only parse result for an uploaded .vsdx file."""

    file_name: str = Field(..., description="Original file name (basename only)")
    pages: List[VsdxPage] = Field(default_factory=list)
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal issues, e.g. approximated curves or skipped shapes",
    )
