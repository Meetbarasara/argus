"""Deterministic policy layer (ADR-04): the LLM never authorizes its own remediation.
The risk gate maps a proposed action + confidence to an escalation level via policy.yaml."""
