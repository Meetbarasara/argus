"""Live smoke (08 #11): one real structured call per configured role, verifying the model
id is servable. Prints tokens/latency/cost and writes llm_calls rows. Needs API keys.

    python -m argus.llm.smoke
"""

from __future__ import annotations

import sys

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from argus.llm.config import load_model_config
from argus.llm.router import LLMRouter


class SmokeReply(BaseModel):
    ok: bool
    service: str


def main() -> int:
    router = LLMRouter(mode="live")
    config = load_model_config()
    failures: list[str] = []

    for role, rm in config.items():
        try:
            reply = router.structured(
                role,
                [HumanMessage(content="Return JSON with ok=true and service set to 'argus'.")],
                SmokeReply,
            )
            print(f"[OK]   {role:<16} {rm.provider}/{rm.model}  -> ok={reply.ok}")
        except Exception as exc:
            print(f"[FAIL] {role:<16} {rm.provider}/{rm.model}  -> {type(exc).__name__}: {exc}")
            failures.append(role)

    if failures:
        print(f"\n{len(failures)} role(s) failed: {failures}")
        print("If a model id is stale, update config/models.yaml (08 #11).")
        return 1
    print(f"\nAll {len(config)} roles OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
