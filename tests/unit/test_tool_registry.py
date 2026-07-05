import pytest

from argus.tools.langchain_bridge import tool_names_for_agent
from argus.tools.registry import _truncate, build_registry

pytestmark = pytest.mark.unit

# 04 §5 tool matrix — asserted literally.
EXPECTED = {
    "search_logs": ({"log_analyst"}, "read"),
    "log_error_summary": ({"log_analyst"}, "read"),
    "query_metrics": ({"metrics_analyst"}, "read"),
    "service_health": ({"metrics_analyst"}, "read"),
    "list_deploys": ({"change_analyst"}, "read"),
    "deploy_diff": ({"change_analyst"}, "read"),
    "recent_actions": ({"change_analyst"}, "read"),
    "restart_service": ({"remediate"}, "mutating"),
    "rollback_deploy": ({"remediate"}, "mutating"),
}


def test_registry_matches_spec_matrix():
    reg = build_registry()
    assert set(reg) == set(EXPECTED)
    for name, (agents, risk) in EXPECTED.items():
        assert set(reg[name].allowed_agents) == agents
        assert reg[name].risk == risk


def test_toolset_per_agent_matches_matrix():
    reg = build_registry()
    assert tool_names_for_agent("log_analyst", reg) == {"search_logs", "log_error_summary"}
    assert tool_names_for_agent("metrics_analyst", reg) == {"query_metrics", "service_health"}
    assert tool_names_for_agent("change_analyst", reg) == {
        "list_deploys",
        "deploy_diff",
        "recent_actions",
    }
    assert tool_names_for_agent("remediate", reg) == {"restart_service", "rollback_deploy"}


def test_truncate_caps_long_list():
    result, truncated = _truncate(list(range(200)))
    assert truncated is True and len(result) == 50


def test_truncate_leaves_small_result():
    result, truncated = _truncate([1, 2, 3])
    assert truncated is False and result == [1, 2, 3]
