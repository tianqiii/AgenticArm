"""确定性机械臂技能：LLM 只选技能，不碰关节角。

MuJoCo 没有内置高级 IK；这里用 mink 的微分 IK：
- IK 用机器人本体模型 `panda.xml`（没有物体自由关节，避免 IK 去动物体）；
- 解出的前 7 个 qpos 写回完整场景的 `data.ctrl[:7]`；
- 末端帧是 body `hand`（Menagerie Panda 没有 grasp site）。

已验证：
- mink 1.4 没有 SO3.from_quaternion_xyzw；默认保持当前 hand 姿态最稳。
- `Configuration` 设置 q 后必须调用 `update(q)`，否则运动学还是 qpos0。
"""

from dataclasses import dataclass, field

import mink
import numpy as np

from arm_agent_demo.sim import HOME_FINGERS, HOME_QPOS, Sim

POSITION_TOLERANCE = 0.01
GRASP_TOLERANCE = 0.03
LIFT_HEIGHT = 0.12
MAX_MOVE_STEPS = 240


@dataclass
class SkillResult:
    ok: bool
    code: str = "OK"
    message: str = ""
    hint: str = ""
    state: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)


class Skills:
    def __init__(self, sim: Sim):
        self.sim = sim
        self.ik_config = mink.Configuration(sim.ik_model)
        self.task = mink.FrameTask(
            "hand", "body", position_cost=1.0, orientation_cost=0.1, lm_damping=1.0
        )
        self.held: str | None = None
        self.hold_offset = None  # 运动学吸附时保存 hand 到物体的相对位姿
        self._reset_ik()

    def _reset_ik(self) -> None:
        """把 IK 配置同步到 home；注意 update(q) 不能省。"""
        q = self.ik_config.q.copy()
        q[:7] = HOME_QPOS
        q[7:9] = HOME_FINGERS
        self.ik_config.update(q)

    # 统一的成功/失败构造，保证 tools.py 和 harness 拿到稳定结构
    def _ok(self, message: str = "", **state) -> SkillResult:
        return SkillResult(ok=True, code="OK", message=message, state=state)

    def _err(self, code: str, message: str, hint: str = "") -> SkillResult:
        return SkillResult(ok=False, code=code, message=message, hint=hint)

    def _step(self, n: int = 1) -> None:
        """推进物理；如果启用了运动学吸附，随后同步物体位姿。"""
        self.sim.step(n)
        if self.held is not None:
            self._sync_held()

    def _sync_held(self) -> None:
        """TODO（可选）：把物体位姿写成 hand 位姿 × hold_offset。

        MVP 推荐先用运动学吸附，隔离接触/摩擦调参：
        - grasp 时计算物体相对 hand 的位置/四元数，存到 self.hold_offset；
        - 每步用 sim.hand_position()/hand_quaternion() 组合 offset；
        - 调 sim.set_object_pose(...) 写回物体 free joint。
        如果要用真实夹爪，删掉这条路径，靠闭合夹爪 + 摩擦抓取。
        """
        raise NotImplementedError("Skills._sync_held 待实现（或改用真实夹爪）")

    def _validate_workspace(self, position) -> SkillResult | None:
        # TODO: 检查 x/y/z 是否在 Sim.WORKSPACE 内
        #       越界返回 self._err("OUT_OF_WORKSPACE", "...", hint="换一个可达目标")
        raise NotImplementedError("Skills._validate_workspace 待实现")

    def home(self) -> SkillResult:
        # TODO: self._reset_ik()
        # TODO: self.sim.set_arm_ctrl(HOME_QPOS)
        # TODO: self.sim.set_gripper(True)
        # TODO: self._step(120)；检查 hand 位置误差
        raise NotImplementedError("Skills.home 待实现")

    def move_to_pose(
        self,
        position,
        orientation=None,
        max_steps: int = MAX_MOVE_STEPS,
        tolerance: float = POSITION_TOLERANCE,
    ) -> SkillResult:
        """用 mink 解 IK，并让 7 个手臂关节跟踪目标。

        orientation：mink.SO3 或 None。None 表示保持当前 hand 姿态；
        scene_home 下这个姿态就是自上而下，先不要硬编码四元数。

        TODO:
        1. workspace 校验；
        2. if orientation is None:
               orientation = self.ik_config.get_transform_frame_to_world("hand", "body").rotation()
           target = mink.SE3.from_rotation_and_translation(orientation, np.array(position))
           self.task.set_target(target)
        3. for _ in range(max_steps):
               velocity = mink.solve_ik(
                   self.ik_config, [self.task], dt=self.sim.model.opt.timestep,
                   solver="daqp", damping=1e-3)
               self.ik_config.integrate_inplace(velocity, self.sim.model.opt.timestep)
               self.sim.set_arm_ctrl(self.ik_config.q[:7])
               self._step(1)
               检查 sim.hand_position() 与 position 的误差
        4. 超时返回 TIMEOUT；IK 失败返回 IK_FAILED。
        """
        raise NotImplementedError("Skills.move_to_pose 待实现")

    def move_above(self, name: str, height: float = LIFT_HEIGHT) -> SkillResult:
        # TODO: pos = np.array(self.sim.object_position(name)) + [0, 0, height]
        # TODO: return self.move_to_pose(pos)
        # TODO: 物体不存在时捕获 ValueError，返回 OBJECT_NOT_FOUND
        raise NotImplementedError("Skills.move_above 待实现")

    def grasp(self, name: str) -> SkillResult:
        """抓取。

        前置：物体存在、graspable、夹爪为空、hand 在物体附近。
        TODO:
        1. 校验 self.held is None；
        2. move_above(name) → 下降到抓取高度（先打印 hand 与物体相对位置校准）；
        3. 闭合夹爪：self.sim.set_gripper(False)；self._step()；
        4. 检查物体与 hand 距离（GRASP_TOLERANCE）；
        5. MVP 可改用运动学吸附：
           记录物体相对 hand 的位姿到 self.hold_offset，self.held = name；
        6. 返回 _ok。
        """
        raise NotImplementedError("Skills.grasp 待实现")

    def release(self) -> SkillResult:
        # TODO: 校验 self.held；self.held = None；self.hold_offset = None
        # TODO: self.sim.set_gripper(True)；self._step()
        raise NotImplementedError("Skills.release 待实现")

    def pick_and_place(self, source: str, target: str) -> SkillResult:
        """高层复合技能：抓 source，放到 target。

        前置：source/target 存在且不同；夹爪为空。
        TODO 顺序：
        1. 校验 source/target；
        2. move_above(source) → move_to_pose(抓取高度) → grasp(source)；
        3. 抬起（LIFT_HEIGHT）；
        4. move_above(target) → 下降到放置高度 → release()；
        5. 抬起；用 sim.object_position 检查 source 是否在 target 附近。
        任何一步失败都返回该步的错误，并在 hint/message 里说明步骤。
        """
        raise NotImplementedError("Skills.pick_and_place 待实现")

    def reset(self) -> SkillResult:
        """清空夹持状态并重置场景。"""
        self.held = None
        self.hold_offset = None
        self.sim.reset()
        self._reset_ik()
        return self._ok("场景已重置")

    def get_state(self) -> SkillResult:
        state = self.sim.get_state()
        state["holding"] = self.held
        return SkillResult(ok=True, code="OK", state=state)

    def list_objects(self) -> SkillResult:
        return SkillResult(ok=True, code="OK", state={"objects": self.sim.list_objects()})
