"""Pydantic arg schemas for every tool (04 §5). The executor validates raw args against
these before dispatch; they also become the LangChain tool arg schemas in M05."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SearchLogsArgs(BaseModel):
    service: str | None = None
    level: str | None = None
    contains: str | None = None
    since_minutes: int = Field(default=30, ge=1, le=120)
    limit: int = Field(default=50, ge=1, le=50)


class LogErrorSummaryArgs(BaseModel):
    service: str | None = None
    since_minutes: int = Field(default=30, ge=1, le=120)


class QueryMetricsArgs(BaseModel):
    service: str
    metric: str
    since_minutes: int = Field(default=30, ge=1, le=120)
    agg: Literal["raw", "avg", "max", "last"] = "last"


class ServiceHealthArgs(BaseModel):
    pass


class ListDeploysArgs(BaseModel):
    service: str | None = None
    since_minutes: int = Field(default=120, ge=1, le=1440)
    limit: int = Field(default=20, ge=1, le=20)


class DeployDiffArgs(BaseModel):
    deploy_id: str


class RecentActionsArgs(BaseModel):
    since_minutes: int = Field(default=30, ge=1, le=1440)


class RestartServiceArgs(BaseModel):
    service: str


class RollbackDeployArgs(BaseModel):
    deploy_id: str
