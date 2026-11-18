"""评测 runner：reset → agent → 仿真 oracle → 指标。

单进程常驻 Sim，每个任务 reset；不要每个任务重启仿真。
"""

import argparse
import json
import math
import tempfile
from pathlib import Path

from arm_agent_demo.sim import Sim
from core.harness import Harness
from core.llm import LLM
from core.memory import Memory
from utils import tools
from utils.skills import SkillResult, Skills

from .eval_metrics import summarize
from .eval_tasks import TASKS


def distance_xy(a, b) -> float:
    """水平距离（米）。放置成功只看 xy，不卡 z。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _objects_unchanged(before: dict, after: dict, tol: float = 1e-6) -> bool:
    """终态工具要求“无物理动作”：物体位置必须与 reset 后一致。"""
    for name, position in before["objects"].items():
        if math.dist(position, after["objects"][name]) > tol:
            return False
    return True


def check_task(sim: Sim, task: dict, result, before: dict) -> bool:
    """用仿真真值判定任务是否成功。

    - clarify / infeasible：终态匹配，且场景没有被物理动作改过；
    - success：status=final，且每个 [source, target] 水平距离小于容差。
    """
    expect = task["expect"]
    terminal = expect["terminal"]

    if terminal in ("clarify", "infeasible"):
        if result.status != terminal:
            return False
        return _objects_unchanged(before, sim.snapshot())

    if terminal != "success":
        raise ValueError(f"未知终态：{terminal}")

    if result.status != "final":
        return False

    tol = expect.get("tol", 0.04)
    for source, target in expect.get("placements", []):
        if distance_xy(sim.object_position(source), sim.object_position(target)) >= tol:
            return False
    return True


def _inject_failure(skills: Skills, inject: dict):
    """把某个技能的前 times 次调用替换为失败，用于恢复测试。

    返回恢复函数；episode 结束后必须调用，避免污染后续任务。
    """
    name = inject["skill"]
    remaining = {"times": inject.get("times", 1)}
    original = getattr(skills, name)

    def failing(*args, **kwargs):
        if remaining["times"] > 0:
            remaining["times"] -= 1
            return SkillResult(
                ok=False,
                code="GRASP_FAILED",
                message=f"注入故障：{name} 第一次调用失败",
                hint="重试一次",
            )
        return original(*args, **kwargs)

    setattr(skills, name, failing)
    return lambda: setattr(skills, name, original)


def run_episode(sim: Sim, skills: Skills, llm: LLM, memory: Memory, task: dict) -> dict:
    """跑一条任务，返回一行结果。"""
    skills.reset()
    before = sim.snapshot()

    restore = None
    if task.get("inject"):
        restore = _inject_failure(skills, task["inject"])
    try:
        agent = Harness(
            llm=llm,
            memory=memory,
            session_id=f"eval-{task['id']}",
        )
        result = agent.run(task["instruction"])
    finally:
        if restore is not None:
            restore()

    passed = check_task(sim, task, result, before)
    invalid = sum(1 for call in result.tool_calls if not call["ok"])
    return {
        "task_id": task["id"],
        "category": task["category"],
        "status": result.status,
        "passed": passed,
        "steps": result.steps,
        "tool_calls": len(result.tool_calls),
        "invalid": invalid,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "latency_ms": result.latency_ms,
    }


def run_eval(tasks: list[dict], limit: int = 0) -> list[dict]:
    """跑任务集，返回 rows。

    Sim 常驻、每个任务 reset；会话文件放在临时目录，避免和本地 sessions.json 串味。
    """
    sim = Sim(gui=False)
    skills = Skills(sim)
    tools.bind(skills)

    rows = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            memory = Memory(Path(tmp) / "sessions.json")
            llm = LLM()
            selected = tasks[:limit] if limit else tasks
            for task in selected:
                rows.append(run_episode(sim, skills, llm, memory, task))
    finally:
        sim.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="机械臂 Agent 评测")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    args = parser.parse_args()

    rows = run_eval(TASKS, args.limit)
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
