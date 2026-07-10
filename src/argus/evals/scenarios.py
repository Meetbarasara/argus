"""Load the versioned eval suite (evals/scenarios/*.yaml, schema 03 §3). The suite ships with
the repo — same commit, same cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SCENARIO_DIR = "evals/scenarios"


def load_scenario(scenario_id: str, directory: str = SCENARIO_DIR) -> dict[str, Any]:
    return dict(
        yaml.safe_load((Path(directory) / f"{scenario_id}.yaml").read_text(encoding="utf-8"))
    )


def suite_ids(selector: str = "all", directory: str = SCENARIO_DIR) -> list[str]:
    """Resolve a selector to case ids: ``all`` → every case; ``S3`` → S3-v1/v2/v3; ``S3-v2`` →
    just that case. Deterministic order (sorted) so a run is reproducible."""
    ids = sorted(p.stem for p in Path(directory).glob("*.yaml"))
    if not selector or selector == "all":
        return ids
    return [i for i in ids if i == selector or i.startswith(f"{selector}-")]
