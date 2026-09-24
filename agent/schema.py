"""
Schema for a single app's research result.

This is the contract the research agent must fill in for every one of the
100 apps. Keeping it as a strict pydantic model means malformed/incomplete
LLM output fails loudly instead of silently corrupting the dataset.
"""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


AuthMethod = Literal[
    "OAuth2", "API key", "Basic", "Token", "OAuth1", "None / public", "Other", "Unknown"
]

SelfServe = Literal[
    "Self-serve (free)", "Self-serve (paid plan required)",
    "Gated (approval/allowlist)", "Gated (partnership/contact-sales)", "Unknown"
]

Verdict = Literal[
    "Buildable today", "Buildable with friction", "Blocked", "Unknown"
]


class AppResearchResult(BaseModel):
    id: int
    app: str
    category: str

    # What it does
    one_liner: str = Field(description="One sentence: what the app is/does")

    # Auth
    auth_methods: list[AuthMethod] = Field(default_factory=list)
    auth_notes: str = Field(default="", description="Specifics, e.g. 'OAuth2 + refresh tokens, PKCE supported'")

    # Access
    self_serve: SelfServe = "Unknown"
    self_serve_notes: str = Field(default="", description="e.g. 'requires paid Business plan for API access'")

    # API surface
    has_public_api: bool = False
    api_style: str = Field(default="", description="e.g. 'REST', 'GraphQL', 'REST + Webhooks'")
    api_breadth: Literal["Broad", "Moderate", "Narrow", "None", "Unknown"] = "Unknown"
    existing_mcp: bool = Field(default=False, description="Does an official or well-known community MCP server exist?")
    mcp_notes: str = ""

    # Composio cross-check (filled in by composio_lookup.py, not the LLM)
    composio_supported: Optional[bool] = None
    composio_notes: str = ""

    # Verdict
    verdict: Verdict = "Unknown"
    blocker: str = Field(default="", description="Main blocker if not cleanly buildable, else empty")

    # Evidence
    evidence_urls: list[str] = Field(default_factory=list)

    # Meta
    confidence: Literal["High", "Medium", "Low"] = "Medium"
    agent_notes: str = Field(default="", description="Anything ambiguous/uncertain the agent flagged for human review")


class VerificationRecord(BaseModel):
    """One row of the human verification pass."""
    id: int
    app: str
    field_checked: str
    agent_said: str
    human_found: str
    correct: bool
    source_checked: str = ""
    reviewer_notes: str = ""
