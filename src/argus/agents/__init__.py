"""Agent layer (04 §4): thin, testable wrappers over ``argus.llm`` + ``argus.tools``.

Each agent builds messages from ``prompts.py``, calls the router (structured or tool
loop), and returns a validated schema object from ``schemas.py``. Graph glue (spans,
status transitions, budget, state updates) lives in ``argus.graph.nodes`` — agents stay
free of graph/DB concerns so they can be unit-tested against a FakeLLM.
"""
