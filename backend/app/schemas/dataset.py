"""Dataset API schemas.

Every field here is a *measured* property of the uploaded file — a byte count,
a row count, a column count. Nothing on this surface is estimated, inferred, or
generated. That is the product rule stated in ``CLAUDE.md`` applied at its
first touchpoint: the number the user sees for "rows" is the number pandas
counted, and there is no code path by which it could become anything else.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DatasetUploadResponse(BaseModel):
    """Result of accepting, storing, and parsing one uploaded dataset.

    Returned by ``POST /api/v1/datasets/upload``.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "example": {
                "dataset_id": "0f9c1b2e-6b3a-4a1e-9f0b-2c7d5a8e1234",
                "filename": "january_orders.csv",
                "rows": 4821,
                "columns": 12,
                "file_size": 481_920,
            }
        },
    )

    dataset_id: str = Field(
        description="Identifier for this upload. Use it to request analysis.",
    )
    filename: str = Field(
        description=(
            "The stored filename, sanitised from the client's upload — any "
            "directory component is stripped before storage."
        ),
    )
    rows: int = Field(
        ge=0,
        description="Data rows parsed, excluding the header.",
    )
    columns: int = Field(
        ge=0,
        description="Columns detected in the parsed table.",
    )
    file_size: int = Field(
        ge=0,
        description="Size of the stored file in bytes, counted while writing.",
    )
