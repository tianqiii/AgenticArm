"""指标公式测试：用 DESIGN.md 里的示例和手算值做基准。"""

import pytest

from eval.eval_metrics import pass_at_k, summarize, wilson_ci


def test_wilson_ci_matches_design_example():
    # DESIGN 6.5：20 条成功 18 条，95% CI 约 [0.70, 0.97]
    low, high = wilson_ci(18, 20)

    assert low == pytest.approx(0.699, abs=1e-3)
    assert high == pytest.approx(0.972, abs=1e-3)


def test_pass_at_k_boundaries():
    assert pass_at_k(10, 5, 1) == pytest.approx(0.5)
    assert pass_at_k(10, 0, 1) == 0.0
    assert pass_at_k(10, 10, 1) == 1.0

    with pytest.raises(ValueError):
        pass_at_k(2, 1, 3)


def test_summarize_reports_macro_and_micro():
    rows = [
        {
            "task_id": "A01",
            "category": "single_step",
            "status": "final",
            "passed": True,
            "steps": 2,
            "tool_calls": 2,
            "invalid": 0,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "latency_ms": 100.0,
        },
        {
            "task_id": "A02",
            "category": "single_step",
            "status": "final",
            "passed": False,
            "steps": 3,
            "tool_calls": 1,
            "invalid": 1,
            "prompt_tokens": 12,
            "completion_tokens": 6,
            "latency_ms": 200.0,
        },
    ]

    summary = summarize(rows)

    assert summary["n"] == 2
    assert summary["success_rate"] == 0.5
    assert summary["micro_success_rate"] == 0.5
    assert summary["macro_success_rate"] == 0.5
    assert summary["invalid_action_rate"] == pytest.approx(1 / 3)
    assert summary["total_tokens"] == 33
    assert summary["status_counts"] == {"final": 2}
