"""Structured outputs for dual OpenAI + Claude dispute compliance analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AI_DISPUTE_RESPONSE_CODE_LITERAL = Literal["Valid", "Invalid"]
AI_RECOMMENDATION_CODE_LITERAL = Literal["01", "23", "03", "07"]


class ComplianceAIAnalysis(BaseModel):
    """Shared schema for OpenAI primary analysis and Claude validation."""

    aiDisputeResponseCode: AI_RECOMMENDATION_CODE_LITERAL = Field(
        description=(
            "Numeric disposition code: 01 or 23 = invalid dispute; 03 or 07 = valid dispute (delete)."
        ),
    )
    aiRecommendationReason: str = Field(
        description="Evidence-based rationale tied to aiDisputeResponseCode and aiRecommendation.",
    )
    aiConfidenceLevel: int = Field(
        ge=0,
        le=100,
        description="Model confidence in [0, 100] for this disposition.",
    )
    aiSummary: str = Field(description="Concise dispute summary.")
    aiRecommendation: AI_DISPUTE_RESPONSE_CODE_LITERAL = Field(
        description='Overall validity: "Valid" when aiDisputeResponseCode is 03 or 07; '
        '"Invalid" when it is 01 or 23.',
    )
    aiDisputeReason: str = Field(description="Consumer's stated or inferred dispute reason.")
    aiAutomatableResponse: str = Field(
        default="",
        description="OpenAI: automatable guidance text. Claude: leave blank per policy.",
    )
