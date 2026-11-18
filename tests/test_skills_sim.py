"""headless 技能契约测试：不调用 API，直接跑 MuJoCo。"""

import math

import pytest

from arm_agent_demo.sim import Sim
from utils.skills import Skills


@pytest.fixture()
def skills():
    sim = Sim(gui=False)
    yield Skills(sim)
    sim.close()


def test_home_reaches_home_pose(skills):
    result = skills.home()

    assert result.ok, result
    assert skills.held is None


def test_pick_and_place_uses_sim_ground_truth(skills):
    result = skills.pick_and_place("red_cube", "blue_plate")

    assert result.ok, result
    assert result.state["distance"] < 0.04
    assert skills.held is None

    source = skills.sim.object_position("red_cube")
    target = skills.sim.object_position("blue_plate")
    assert math.dist(source[:2], target[:2]) < 0.04


def test_errors_are_return_values(skills):
    assert skills.release().code == "GRIPPER_EMPTY"
    assert skills.grasp("purple_cube").code == "OBJECT_NOT_FOUND"
    assert skills.pick_and_place("red_cube", "purple_plate").code == "TARGET_NOT_FOUND"
    assert skills.pick_and_place("red_cube", "red_cube").code == "INVALID_ARGUMENT"
