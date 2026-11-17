"""评测 runner：reset → agent → 仿真 oracle → 指标。

单进程常驻 Sim，每个任务 reset；不要每个任务重启仿真。
"""

import argparse
import json
import tempfile
from pathlib import Path

from arm_agent_demo.sim import Sim
from core.harness import Harness
from core.llm import LLM
from core.memory import Memory
from utils import tools
from utils.skills import Skills

from .eval_metrics import summarize
from .eval_tasks import TASKS


def distance_xy(a, b) -> float:
    """水平距离。TODO: 用 math.dist 或手写 sqrt(dx^2 + dy^2)。"""
    raise NotImplementedError("distance_xy 待实现")


def check_task(sim: Sim, task: dict, result, before: dict) -> bool:
    """用仿真真值判定任务是否成功。

    TODO:
    - expect["terminal"] == "clarify"/"infeasible"：result.status 必须匹配，
      且 sim.snapshot() 与 before 一致（不能有物理动作）。
    - success：result.status == "final"；对每个 [source, target]，
      distance_xy(sim.object_position(source), sim.object_position(target)) < tol。
    """
    raise NotImplementedError("check_task 待实现")


def run_episode(sim: Sim, skills: Skills, llm: LLM, memory: Memory, task: dict) -> dict:
    """跑一条任务，返回一行结果。

    TODO:
    1. skills.reset()；before = sim.snapshot()
    2. agent = Harness(llm=llm, memory=memory, session_id=f"eval-{task['id']}")
    3. result = agent.run(task["instruction"])
    4. passed = check_task(sim, task, result, before)
    5. 返回 task_id/category/status/passed/steps/tool_calls/invalid/tokens/latency
    """
    raise NotImplementedError("run_episode 待实现")


def run_eval(tasks: list[dict], limit: int = 0) -> list[dict]:
    """跑任务集，返回 rows。

    TODO:
    - Sim(gui=False) 常驻；Skills；tools.bind(skills)
    - 用 tempfile.TemporaryDirectory() + Memory(Path(tmp) / "sessions.json")
      隔离每个任务的会话，避免历史串味
    - 遍历 tasks[: limit or None]，调用 run_episode
    - finally sim.close()
    """
    raise NotImplementedError("run_eval 待实现")


def main() -> None:
    parser = argparse.ArgumentParser(description="机械臂 Agent 评测（骨架）")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    args = parser.parse_args()

    rows = run_eval(TASKS[: args.limit or None])
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
