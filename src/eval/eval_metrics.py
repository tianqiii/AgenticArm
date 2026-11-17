"""评测指标：成功率、Wilson CI、pass@k、汇总。

公式见 DESIGN.md 附录 C。
"""

import math


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项成功率的 Wilson 置信区间。

    TODO:
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2*n)) / denom
    half = z * sqrt(p*(1-p)/n + z**2/(4*n**2)) / denom
    return (center - half, center + half)
    """
    raise NotImplementedError("wilson_ci 待实现")


def pass_at_k(n: int, c: int, k: int) -> float:
    """1 - C(n-c, k) / C(n, k)。

    TODO: 用 math.comb；n < k 时抛 ValueError。
    """
    raise NotImplementedError("pass_at_k 待实现")


def summarize(rows: list[dict]) -> dict:
    """按类别汇总成功率、CI、平均步数、无效动作率、成本。

    TODO: 用 wilson_ci；macro/micro 两种平均都报告。
    """
    raise NotImplementedError("summarize 待实现")
