"""评测指标：成功率、Wilson CI、pass@k、汇总。

公式见 DESIGN.md 附录 C。
"""

import math


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项成功率的 Wilson 置信区间（95% 对应 z=1.96）。

    小样本（20 条）也能给出比正态近似更可靠的区间；结果夹到 [0, 1]。
    """
    if n <= 0:
        raise ValueError("n 必须大于 0")
    if not 0 <= successes <= n:
        raise ValueError("successes 必须在 [0, n] 内")

    p = successes / n
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return (max(0.0, center - half), min(1.0, center + half))


def pass_at_k(n: int, c: int, k: int) -> float:
    """每个任务重复 n 次、成功 c 次时，k 次采样至少成功一次的概率。

    1 - C(n-c, k) / C(n, k)。n < k 时无定义，抛 ValueError。
    """
    if k <= 0:
        raise ValueError("k 必须大于 0")
    if n < k:
        raise ValueError("n 必须不小于 k")
    if not 0 <= c <= n:
        raise ValueError("c 必须在 [0, n] 内")
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def _rate(successes: int, n: int) -> float:
    return successes / n if n else 0.0


def summarize(rows: list[dict]) -> dict:
    """按类别汇总成功率、CI、平均步数、无效动作率、token 和耗时。

    row 字段由 eval_runner.run_episode 产出：
    task_id / category / status / passed / steps / tool_calls / invalid /
    prompt_tokens / completion_tokens / latency_ms。
    """
    if not rows:
        return {
            "n": 0,
            "success_rate": 0.0,
            "ci95": [0.0, 0.0],
            "macro_success_rate": 0.0,
            "micro_success_rate": 0.0,
            "avg_steps": 0.0,
            "invalid_action_rate": 0.0,
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "by_category": {},
            "status_counts": {},
        }

    by_category: dict[str, dict] = {}
    status_counts: dict[str, int] = {}
    for row in rows:
        bucket = by_category.setdefault(row["category"], {"n": 0, "passed": 0})
        bucket["n"] += 1
        bucket["passed"] += int(bool(row["passed"]))
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    for bucket in by_category.values():
        bucket["success_rate"] = _rate(bucket["passed"], bucket["n"])
        bucket["ci95"] = list(wilson_ci(bucket["passed"], bucket["n"]))

    n = len(rows)
    successes = sum(int(bool(row["passed"])) for row in rows)
    total_tool_calls = sum(row["tool_calls"] for row in rows)
    invalid = sum(row["invalid"] for row in rows)

    return {
        "n": n,
        "success_rate": _rate(successes, n),
        "ci95": list(wilson_ci(successes, n)),
        # macro：每个类别权重相同；micro：每次运行权重相同。两者都报，避免被大类主导
        "macro_success_rate": sum(
            bucket["success_rate"] for bucket in by_category.values()
        )
        / len(by_category),
        "micro_success_rate": _rate(successes, n),
        "avg_steps": sum(row["steps"] for row in rows) / n,
        "invalid_action_rate": _rate(invalid, total_tool_calls),
        "total_tokens": sum(
            row["prompt_tokens"] + row["completion_tokens"] for row in rows
        ),
        "avg_latency_ms": sum(row["latency_ms"] for row in rows) / n,
        "by_category": by_category,
        "status_counts": status_counts,
    }
