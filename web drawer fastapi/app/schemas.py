"""Validated drawing settings (sent as query parameters)."""
from typing import Literal

from pydantic import BaseModel, Field


class Settings(BaseModel):
    sharpness: int = Field(50, ge=0, le=100)      # edge strength
    colors: int = Field(12, ge=2, le=24)          # number of colours
    texture: int = Field(50, ge=0, le=100)        # low = grainy, high = flat colours
    detail: int = Field(50, ge=0, le=100)         # region size, simplification, edge length
    outline_mode: Literal["image", "black"] = "image"
    outline_darken: float = Field(0.65, ge=0.2, le=1.0)
    edge_order: Literal["as_found", "top_to_bottom", "left_to_right"] = "as_found"
