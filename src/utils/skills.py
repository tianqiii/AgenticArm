"""确定性机械臂技能：LLM 只选技能，不碰关节角。

MuJoCo 没有内置高级 IK；这里用 mink 的微分 IK：
- IK 用机器人本体模型 `panda.xml`（没有物体自由关节，避免 IK 去动物体）；
- 解出的前 7 个 qpos 写回完整场景的 `data.ctrl[:7]`；
- 末端帧是 body `hand`（Menagerie Panda 没有 grasp site）。

已验证：
- mink 1.4 没有 SO3.from_quaternion_xyzw；默认保持当前 hand 姿态最稳。
- `Configuration` 设置 q 后必须调用 `update(q)`，否则运动学还是 qpos0。
- hand 局部 z 轴在 home 姿态下朝下；指尖中心（TCP）在 hand 局部 z≈0.10 处，
  由 finger body 偏移 0.0584 + 指垫长度约 0.04 得到（见 panda.xml）。
"""

from dataclasses import dataclass, field

import mink
import numpy as np

from arm_agent_demo.sim import HOME_FINGERS, HOME_QPOS, OBJECTS, TARGETS, WORKSPACE, Sim

POSITION_TOLERANCE = 0.01
HOME_TOLERANCE = 0.05
GRASP_TOLERANCE = 0.03
LIFT_HEIGHT = 0.12
MAX_MOVE_STEPS = 240
GRIPPER_SETTLE_STEPS = 20
PLACE_HEIGHT = 0.03
PLACE_TOLERANCE = 0.04

# hand body 到指尖（TCP）的局部偏移。抓取/放置都用 TCP 判断位置，
# 这样 IK 目标、抓取距离和放置高度都是“指尖到物体”的直观距离。
TCP_OFFSET_LOCAL = np.array([0.0, 0.0, 0.10])


# ---------------------------------------------------------------------------
# 四元数工具（MuJoCo 统一用 wxyz）。只用 numpy，避免引入 scipy 依赖。
# 这几个函数假设输入是单位四元数（MuJoCo 的 xquat/qpos 满足）。
# ---------------------------------------------------------------------------
def _quat_conjugate(q: np.ndarray) -> np.ndarray:
    """单位四元数的逆。"""
    return np.array([q[0], -q[1], -q[2], -q[3]])


def _quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton 积：先转 a 再转 b 的合成旋转。"""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ]
    )


def _quat_rotate(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    """用四元数旋转向量：v' = q · (v,0) · q*。

    展开成 t = 2·q_vec×v 的形式，比构造纯四元数再做两次乘法少一半运算。
    """
    w = q[0]
    vec = q[1:]
    t = 2.0 * np.cross(vec, v)
    return v + w * t + np.cross(vec, t)


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

    def _sync_ik(self) -> None:
        """解决 IK 前先让配置追上仿真里的实际关节角，避免从旧状态起解。"""
        q = self.ik_config.q.copy()
        q[:9] = self.sim.data.qpos[:9]
        self.ik_config.update(q)

    # 统一的成功/失败构造，保证 tools.py 和 harness 拿到稳定结构
    def _ok(self, message: str = "", **state) -> SkillResult:
        return SkillResult(ok=True, code="OK", message=message, state=state)

    def _err(self, code: str, message: str, hint: str = "") -> SkillResult:
        return SkillResult(ok=False, code=code, message=message, hint=hint)

    def _step(self, n: int = 1) -> None:
        """推进物理；如果启用了运动学吸附，随后同步物体位姿。"""
        for _ in range(n):
            self.sim.step(1)
            if self.held is not None:
                self._sync_held()

    def _sync_held(self) -> None:
        """把物体位姿写成 hand 位姿 × hold_offset。

        运动学吸附：物体不再受碰撞/摩擦影响，只跟着 hand 走。
        shortcut: 这不是真实抓取，抓取成功率会被高估；v2 换真实夹爪时删掉这条路径。
        """
        if self.held is None or self.hold_offset is None:
            return

        offset_position, offset_quaternion = self.hold_offset
        hand_position = np.asarray(self.sim.hand_position())
        hand_quaternion = np.asarray(self.sim.hand_quaternion())
        self.sim.set_object_pose(
            self.held,
            hand_position + _quat_rotate(hand_quaternion, offset_position),
            _quat_multiply(hand_quaternion, offset_quaternion),
        )

    # ------------------------------------------------------------------
    # 位置/工作空间辅助
    # ------------------------------------------------------------------
    def _tcp_position(self) -> np.ndarray:
        """当前指尖中心的世界坐标。"""
        hand_position = np.asarray(self.sim.hand_position())
        hand_quaternion = np.asarray(self.sim.hand_quaternion())
        return hand_position + _quat_rotate(hand_quaternion, TCP_OFFSET_LOCAL)

    def _hand_target_for_tcp(self, tcp: np.ndarray) -> np.ndarray:
        """把“指尖要到哪”换算成“hand body 要到哪”。

        保持当前 hand 姿态（scene_home 下是自上而下），只换算位置，
        因为 move_to_pose 的契约是 hand body 的位置。
        """
        hand_quaternion = np.asarray(self.sim.hand_quaternion())
        return np.asarray(tcp, dtype=float) - _quat_rotate(
            hand_quaternion, TCP_OFFSET_LOCAL
        )

    def _validate_workspace(self, position) -> SkillResult | None:
        """越界直接拒绝，不做“试试看”的动作。"""
        position = np.asarray(position, dtype=float)
        for index, axis in enumerate(("x", "y", "z")):
            low, high = WORKSPACE[axis]
            if not low <= position[index] <= high:
                return self._err(
                    "OUT_OF_WORKSPACE",
                    f"{axis}={position[index]:.3f} 超出工作空间 [{low}, {high}]",
                    hint="换一个可达目标",
                )
        return None

    def _move_tcp_to(self, tcp: np.ndarray) -> SkillResult:
        """把指尖移动到指定点；先校验工作空间，再换算成 hand 目标。"""
        tcp = np.asarray(tcp, dtype=float)
        workspace_error = self._validate_workspace(tcp)
        if workspace_error is not None:
            return workspace_error
        return self.move_to_pose(self._hand_target_for_tcp(tcp))

    def _lift(self) -> SkillResult:
        """垂直抬起 LIFT_HEIGHT；用于抓取后和放置后。"""
        return self._move_tcp_to(
            self._tcp_position() + np.array([0.0, 0.0, LIFT_HEIGHT])
        )

    # ------------------------------------------------------------------
    # 内部技能
    # ------------------------------------------------------------------
    def home(self) -> SkillResult:
        """回安全位。契约：夹爪打开且不持有物体，所以先清吸附状态。"""
        self.held = None
        self.hold_offset = None
        self._reset_ik()
        self.sim.set_arm_ctrl(HOME_QPOS)
        self.sim.set_gripper(True)
        self._step(120)

        error = float(np.linalg.norm(np.asarray(self.sim.data.qpos[:7]) - HOME_QPOS))
        if error > HOME_TOLERANCE:
            return self._err(
                "TIMEOUT",
                f"回 home 未收敛（关节误差 {error:.3f} rad）",
                hint="重试 home",
            )
        return self._ok(
            "已回到安全位", holding=None, ee_position=list(self.sim.hand_position())
        )

    def move_to_pose(
        self,
        position,
        orientation=None,
        max_steps: int = MAX_MOVE_STEPS,
        tolerance: float = POSITION_TOLERANCE,
    ) -> SkillResult:
        """用 mink 解 IK，并让 7 个手臂关节跟踪目标。

        position：目标 hand body 位置；orientation 为 None 时保持当前姿态。
        每一步：解速度 → 积分到 IK 配置 → 写关节目标 → 推进一步物理。
        """
        target_position = np.asarray(position, dtype=float)
        workspace_error = self._validate_workspace(target_position)
        if workspace_error is not None:
            return workspace_error

        self._sync_ik()
        if orientation is None:
            orientation = self.ik_config.get_transform_frame_to_world(
                "hand", "body"
            ).rotation()
        self.task.set_target(
            mink.SE3.from_rotation_and_translation(orientation, target_position)
        )

        dt = self.sim.model.opt.timestep
        error = float("inf")
        for _ in range(max_steps):
            velocity = mink.solve_ik(
                self.ik_config, [self.task], dt=dt, solver="daqp", damping=1e-3
            )
            if not np.all(np.isfinite(velocity)):
                return self._err(
                    "IK_FAILED", "mink 返回非有限速度", hint="换一个目标或姿态后重试"
                )

            self.ik_config.integrate_inplace(velocity, dt)
            self.sim.set_arm_ctrl(self.ik_config.q[:7])
            self._step(1)

            error = float(
                np.linalg.norm(np.asarray(self.sim.hand_position()) - target_position)
            )
            if error <= tolerance:
                return self._ok(
                    f"已到达目标 {np.round(target_position, 3).tolist()}",
                    error=round(error, 4),
                )

        return self._err(
            "TIMEOUT",
            f"移动超时，末端位置误差 {error:.3f} m",
            hint="重试一次，或换一个更近的目标",
        )

    def move_above(self, name: str, height: float = LIFT_HEIGHT) -> SkillResult:
        """移动到物体正上方 height 米处（按 TCP 算）。"""
        try:
            object_position = np.asarray(self.sim.object_position(name))
        except ValueError:
            return self._err(
                "OBJECT_NOT_FOUND",
                f"未知物体：{name}",
                hint=f"可用物体：{', '.join([*OBJECTS, *TARGETS])}",
            )
        return self._move_tcp_to(object_position + np.array([0.0, 0.0, height]))

    def grasp(self, name: str) -> SkillResult:
        """抓取：先到物体上方，再下降到物体中心，闭合夹爪后运动学吸附。"""
        if self.held is not None:
            return self._err(
                "GRIPPER_FULL", f"夹爪已持有 {self.held}", hint="先放置或释放"
            )
        if name not in OBJECTS:
            return self._err(
                "OBJECT_NOT_FOUND",
                f"未知物体：{name}",
                hint=f"可选：{', '.join(OBJECTS)}",
            )
        if not OBJECTS[name].get("graspable", False):
            return self._err(
                "INVALID_ARGUMENT", f"{name} 不可抓取", hint="选择一个 graspable 的方块"
            )

        # 1. 上方接近 → 垂直下降到物体中心（TCP 对准方块中心）
        result = self.move_above(name)
        if not result.ok:
            return result
        result = self.move_to_pose(
            self._hand_target_for_tcp(np.asarray(self.sim.object_position(name)))
        )
        if not result.ok:
            return result

        # 2. 闭合夹爪，让画面和接触状态一致；真正的抓取用下面的运动学吸附
        self.sim.set_gripper(False)
        self._step(GRIPPER_SETTLE_STEPS)

        # 3. 对准检查：距离超阈值就拒绝凭空吸附
        error = float(
            np.linalg.norm(
                self._tcp_position() - np.asarray(self.sim.object_position(name))
            )
        )
        if error > GRASP_TOLERANCE:
            self.sim.set_gripper(True)
            return self._err(
                "NOT_ALIGNED",
                f"末端与 {name} 距离 {error:.3f} m，超过抓取阈值",
                hint="重试抓取",
            )

        # 4. 记录物体相对 hand 的位姿（位置 + 朝向），之后每步跟随 hand
        hand_position = np.asarray(self.sim.hand_position())
        hand_quaternion = np.asarray(self.sim.hand_quaternion())
        object_position = np.asarray(self.sim.object_position(name))
        object_quaternion = np.asarray(self.sim.object_quaternion(name))
        self.hold_offset = (
            _quat_rotate(
                _quat_conjugate(hand_quaternion), object_position - hand_position
            ),
            _quat_multiply(_quat_conjugate(hand_quaternion), object_quaternion),
        )
        self.held = name
        return self._ok(f"已抓取 {name}", holding=name, grasp_error=round(error, 4))

    def release(self) -> SkillResult:
        """释放当前持有的物体。先清吸附状态，再打开夹爪，让物体自由落下。"""
        if self.held is None:
            return self._err("GRIPPER_EMPTY", "夹爪里没有物体", hint="先 grasp")
        released = self.held
        self.held = None
        self.hold_offset = None
        self.sim.set_gripper(True)
        self._step(GRIPPER_SETTLE_STEPS)
        return self._ok(f"已释放 {released}", holding=None)

    def pick_and_place(self, source: str, target: str) -> SkillResult:
        """高层复合技能：抓 source，放到 target。

        任何一步失败都立即返回该步的错误，并在 message 里标注步骤。
        每一步内部只依赖公开契约，方便以后替换成真实夹爪或 C++ 控制层。
        """
        if source == target:
            return self._err("INVALID_ARGUMENT", "source 和 target 不能相同")
        if source not in OBJECTS or not OBJECTS[source].get("graspable", False):
            return self._err(
                "OBJECT_NOT_FOUND",
                f"未知或不可抓取的 source：{source}",
                hint=f"可选：{', '.join(OBJECTS)}",
            )
        if target not in TARGETS:
            return self._err(
                "TARGET_NOT_FOUND",
                f"未知 target：{target}",
                hint=f"可选：{', '.join(TARGETS)}",
            )
        if self.held is not None:
            return self._err(
                "GRIPPER_FULL", f"夹爪已持有 {self.held}", hint="先放置或释放"
            )

        steps = [
            ("抓取 source", lambda: self.grasp(source)),
            ("抬起 source", self._lift),
            ("移动到 target 上方", lambda: self.move_above(target)),
            (
                "下降到放置高度",
                lambda: self._move_tcp_to(
                    np.asarray(self.sim.object_position(target))
                    + np.array([0.0, 0.0, PLACE_HEIGHT])
                ),
            ),
            ("释放 source", self.release),
            ("抬起", self._lift),
        ]
        for label, action in steps:
            result = action()
            if not result.ok:
                return self._err(
                    result.code, f"{label}失败：{result.message}", result.hint
                )

        # 后置条件：只信仿真真值，水平距离进入容差才算完成
        delta = np.asarray(self.sim.object_position(source)) - np.asarray(
            self.sim.object_position(target)
        )
        distance = float(np.linalg.norm(delta[:2]))
        if distance > PLACE_TOLERANCE:
            return self._err(
                "NOT_ALIGNED",
                f"{source} 距 {target} 水平 {distance:.3f} m，"
                f"超过放置容差 {PLACE_TOLERANCE} m",
                hint="重试放置",
            )
        return self._ok(
            f"已把 {OBJECTS[source]['label']} 放到 {TARGETS[target]['label']} 上",
            source=source,
            target=target,
            distance=round(distance, 4),
            holding=None,
        )

    # ------------------------------------------------------------------
    # 状态查询 / 重置
    # ------------------------------------------------------------------
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
        return SkillResult(
            ok=True, code="OK", state={"objects": self.sim.list_objects()}
        )
