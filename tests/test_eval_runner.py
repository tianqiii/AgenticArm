"""评测 oracle 测试：不调用 API，用假 LLM 跑完整 episode。"""

import json

import pytest

from arm_agent_demo.sim import Sim
from core.memory import Memory
from eval.eval_runner import check_task, run_episode
from eval.eval_tasks import TASKS
from utils import tools
from utils.skills import Skills


class FakeLLM:
    """第一轮调用 pick_and_place，第二轮给最终回答。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "pick_and_place",
                            "arguments": json.dumps(
                                {"source": "red_cube", "target": "blue_plate"}
                            ),
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "完成"}
        return message, {"prompt_tokens": 1, "completion_tokens": 1}, 0.0


@pytest.fixture()
def env(tmp_path):
    sim = Sim(gui=False)
    skills = Skills(sim)
    tools.bind(skills)
    yield sim, skills, Memory(tmp_path / "sessions.json")
    sim.close()


def test_run_episode_judges_with_simulation(env):
    sim, skills, memory = env

    row = run_episode(sim, skills, FakeLLM(), memory, TASKS[0])

    assert row["passed"] is True
    assert row["status"] == "final"
    assert row["invalid"] == 0


def test_clarify_requires_no_physical_action(env):
    sim, _, _ = env
    before = sim.snapshot()

    class ClarifyResult:
        status = "clarify"

    assert check_task(sim, TASKS[5], ClarifyResult(), before) is True

    sim.set_object_pose("red_cube", (0.60, -0.15, 0.025))
    assert check_task(sim, TASKS[5], ClarifyResult(), before) is False
