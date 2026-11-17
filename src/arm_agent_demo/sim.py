"""MuJoCo 仿真世界：加载 Panda 场景、推进物理、提供状态真值。

只做世界和物理，不做规划。

模型事实（Menagerie `franka_emika_panda`）：
- 机器人本体在 `panda.xml`，末端帧用 body `hand`（没有 grasp site）。
- 夹爪由 `actuator8` 通过 tendon 控制，**ctrl 范围 0..255：255 开、0 合**。
- `panda.xml` 里的 home keyframe 只有 9 个 qpos；场景加入物体后，
  `scene_pick_place.xml` 用 `scene_home` keyframe 保存完整 qpos（避免重名）。
"""

import time
from pathlib import Path

import mujoco

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJECT_ROOT / "assets" / "franka_emika_panda"
PANDA_XML = ASSET_DIR / "panda.xml"
SCENE_XML = ASSET_DIR / "scene_pick_place.xml"

ARM_QPOS = slice(0, 7)
GRIPPER_CTRL = 7
GRIPPER_OPEN = 255.0
GRIPPER_CLOSED = 0.0

# 来自 Menagerie mjx_single_cube.xml 的 home 手臂角度
HOME_QPOS = [0.0, 0.3, 0.0, -1.57079, 0.0, 2.0, -0.7853]
HOME_FINGERS = [0.04, 0.04]
SETTLE_STEPS = 100

WORKSPACE = {"x": (0.25, 0.70), "y": (-0.30, 0.30), "z": (0.0, 0.60)}

OBJECTS = {
    "red_cube": {
        "label": "红色方块",
        "kind": "cube",
        "graspable": True,
        "half_extents": [0.025, 0.025, 0.025],
        "color": [0.90, 0.15, 0.15, 1.0],
        "position": [0.50, -0.15, 0.025],
    },
    "green_cube": {
        "label": "绿色方块",
        "kind": "cube",
        "graspable": True,
        "half_extents": [0.025, 0.025, 0.025],
        "color": [0.15, 0.75, 0.25, 1.0],
        "position": [0.45, 0.00, 0.025],
    },
    "blue_cube": {
        "label": "蓝色方块",
        "kind": "cube",
        "graspable": True,
        "half_extents": [0.025, 0.025, 0.025],
        "color": [0.15, 0.35, 0.90, 1.0],
        "position": [0.50, 0.15, 0.025],
    },
}

TARGETS = {
    "red_plate": {
        "label": "红色盘子",
        "kind": "plate",
        "graspable": False,
        "radius": 0.07,
        "height": 0.004,
        "color": [0.90, 0.15, 0.15, 1.0],
        "position": [0.55, -0.15, 0.002],
    },
    "blue_plate": {
        "label": "蓝色盘子",
        "kind": "plate",
        "graspable": False,
        "radius": 0.07,
        "height": 0.004,
        "color": [0.15, 0.35, 0.90, 1.0],
        "position": [0.55, 0.15, 0.002],
    },
}


class Sim:
    def __init__(self, gui=True, seed=0):
        """加载完整场景 + 机器人本体模型（后者给 mink 做 IK）。"""
        if not SCENE_XML.exists():
            raise FileNotFoundError(
                f"缺少 MuJoCo 场景：{SCENE_XML}\n"
                "先按 README 把 Menagerie 的 franka_emika_panda 复制到 assets/ 下。"
            )

        # TODO: self.gui = gui；self.client / self.viewer 初始化
        # TODO: self.model = mujoco.MjModel.from_xml_path(str(SCENE_XML))
        # TODO: self.data = mujoco.MjData(self.model)
        # TODO: self.ik_model = mujoco.MjModel.from_xml_path(str(PANDA_XML))
        # TODO: self.ik_data = mujoco.MjData(self.ik_model)
        # TODO: if gui: self.viewer = mujoco.viewer.launch_passive(self.model, self.data)
        #        else: self.viewer = None
        # TODO: self._inspect_model()
        # TODO: self.initial_poses = {name: spec["position"][:] for name, spec in OBJECTS.items()}
        # TODO: self.reset()
        raise NotImplementedError("Sim.__init__ 待实现（按上面的 TODO 顺序）")

    def _inspect_model(self) -> None:
        """缓存 hand body、物体 body、自由关节 qpos/dof 地址。"""
        # TODO: self.hand_id = mujoco.mj_name2id(
        #           self.model, mujoco.mjtObj.mjOBJ_BODY, "hand")
        # TODO: self.object_body_ids = {
        #           name: mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, name)
        #           for name in OBJECTS}
        # TODO: self.object_joint_qpos = {}
        #       self.object_joint_dof = {}
        #       for name in OBJECTS:
        #           jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, f"{name}_joint")
        #           self.object_joint_qpos[name] = self.model.jnt_qposadr[jid]
        #           self.object_joint_dof[name] = self.model.jnt_dofadr[jid]
        raise NotImplementedError("Sim._inspect_model 待实现")

    def reset(self) -> None:
        """回 home、物体回初始位姿、清速度/外力。"""
        # TODO: mujoco.mj_resetData(self.model, self.data)
        # TODO: self.data.qpos[ARM_QPOS] = HOME_QPOS
        # TODO: self.data.qpos[7:9] = HOME_FINGERS
        # TODO: self.data.ctrl[:7] = HOME_QPOS
        # TODO: self.data.ctrl[GRIPPER_CTRL] = GRIPPER_OPEN
        # TODO: 对每个物体：
        #           adr = self.object_joint_qpos[name]
        #           self.data.qpos[adr:adr+3] = initial_poses[name]
        #           self.data.qpos[adr+3:adr+7] = [1, 0, 0, 0]  # wxyz
        #           self.data.qvel[self.object_joint_dof[name]:+6] = 0
        # TODO: mujoco.mj_forward(self.model, self.data)
        # TODO: self.step(SETTLE_STEPS)
        raise NotImplementedError("Sim.reset 待实现")

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            mujoco.mj_step(self.model, self.data)
            if self.viewer is not None:
                self.viewer.sync()
                time.sleep(self.model.opt.timestep)

    def set_arm_ctrl(self, qpos) -> None:
        """把 7 个手臂关节的目标角写进 ctrl；不影响夹爪。"""
        self.data.ctrl[:7] = qpos

    def set_gripper(self, open_: bool) -> None:
        """MuJoCo 夹爪 ctrl 是 0..255，不是 0..0.04。"""
        self.data.ctrl[GRIPPER_CTRL] = GRIPPER_OPEN if open_ else GRIPPER_CLOSED

    def hand_position(self):
        return tuple(self.data.xpos[self.hand_id])

    def hand_quaternion(self):
        # MuJoCo 四元数是 wxyz
        return tuple(self.data.xquat[self.hand_id])

    def list_objects(self) -> list[dict]:
        """给 LLM 看的目录：只给 name/label/kind/graspable，不给坐标。"""
        items = {**OBJECTS, **TARGETS}
        return [
            {
                "name": name,
                "label": spec["label"],
                "kind": spec["kind"],
                "graspable": spec["graspable"],
            }
            for name, spec in items.items()
        ]

    def object_position(self, name: str) -> tuple[float, float, float]:
        body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, name)
        if body_id < 0:
            raise ValueError(f"未知物体：{name}；可用：{', '.join(OBJECTS)}")
        return tuple(self.data.xpos[body_id])

    def set_object_pose(self, name: str, position, quaternion=(1.0, 0.0, 0.0, 0.0)) -> None:
        """运动学吸附时用：直接写自由关节 qpos。"""
        adr = self.object_joint_qpos[name]
        self.data.qpos[adr:adr + 3] = position
        self.data.qpos[adr + 3:adr + 7] = quaternion
        dof = self.object_joint_dof[name]
        self.data.qvel[dof:dof + 6] = 0.0
        mujoco.mj_forward(self.model, self.data)

    def get_state(self) -> dict:
        """内部状态：末端位姿、夹爪开合。给 skills/trace 用，不直接给 LLM。"""
        gripper_open = self.data.ctrl[GRIPPER_CTRL] > (GRIPPER_OPEN + GRIPPER_CLOSED) / 2
        return {
            "ee_position": list(self.hand_position()),
            "ee_orientation": list(self.hand_quaternion()),
            "gripper": "open" if gripper_open else "closed",
        }

    def snapshot(self) -> dict:
        """评测/调试用快照：所有物体位置 + 机器人语义状态。"""
        return {
            "objects": {name: list(self.object_position(name)) for name in OBJECTS},
            "robot": self.get_state(),
        }

    def close(self) -> None:
        if getattr(self, "viewer", None) is not None:
            self.viewer.close()
