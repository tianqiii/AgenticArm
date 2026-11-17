# arm-agent-demo

本地仿真的自然语言机械臂 Agent：DeepSeek 做任务规划，**MuJoCo** 做物理仿真，技能层负责确定性的抓取/移动/放置。

当前是**骨架状态**：`sim.py / skills.py / eval_*.py` 的核心函数留了 TODO，按注释手敲；Agent 层（`llm.py / memory.py / harness.py`）已复用并适配。

设计文档见 **[DESIGN.md](./DESIGN.md)**，核心是第 5 章（中间层契约）和第 6 章（评测体系）。

## 技术栈

- Python 3.11（`.python-version` 已固定）
- **MuJoCo 4.0.1** + **mink 1.4.0**（微分 IK）+ **Menagerie Panda**
- numpy / requests；pytest（dev）

## 环境与模型

```bash
cd arm-agent-demo
uv sync
export DEEPSEEK_API_KEY=sk-xxx   # 或复制 .env.example 为 .env
```

Panda 模型已经放在 `assets/franka_emika_panda/`（约 36MB），场景文件是
`assets/franka_emika_panda/scene_pick_place.xml`。如果需要重新拉取模型：

```bash
rm -rf /tmp/mujoco_menagerie
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/google-deepmind/mujoco_menagerie.git /tmp/mujoco_menagerie
cd /tmp/mujoco_menagerie && git sparse-checkout set franka_emika_panda
cp -r franka_emika_panda/. /home/bao-nini/Documents/bao/arm-agent-demo/assets/franka_emika_panda/
```

> 不要覆盖 `scene_pick_place.xml`：它是本项目的场景，复制命令不会覆盖它。

## 已验证的模型事实

- `nq=30`、`nu=8`；keyframe 有两个：Panda 自带的 `home`（9 个 qpos）和本项目的 `scene_home`（完整 30 个 qpos）。
- 夹爪 actuator 的 ctrl 是 **0–255**：**255 开，0 合**（不是 0.04）。
- 末端帧用 body `hand`；Menagerie 没有 grasp site。
- mink 1.4 没有 `SO3.from_quaternion_xyzw`；默认保持当前 `hand` 姿态即可精确到达目标。
- 设置 IK 的 q 后必须调用 `config.update(q)`，否则运动学还是 qpos0。
- 场景空跑 500 步稳定，三个方块 z≈0.025。

## 快速命令

```bash
uv run arm-agent-demo --help
uv run arm-agent-demo --scripted        # 不接 LLM，跑硬编码 pick-and-place
uv run arm-agent-demo "把红色方块放到蓝色盘子里"
uv run arm-agent-demo                   # 交互模式
uv run arm-agent-eval --limit 3         # 评测（待 eval_runner 实现）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q -m "not e2e"   # 快速测试
```

## 文件职责

| 文件 | 职责 | 状态 |
|---|---|---|
| `src/arm_agent_demo/sim.py` | MuJoCo 场景、Panda、物体、reset、真值 | 骨架 |
| `src/utils/skills.py` | mink IK + home / grasp / release / pick_and_place | 骨架 |
| `src/utils/tools.py` | LLM 可见工具 + schema + bind | 接口已定 |
| `src/core/harness.py` | ReAct 循环 + 终态工具 + trace | 已适配 |
| `src/core/llm.py` | DeepSeek / OpenAI 兼容客户端 | 已复用 |
| `src/core/memory.py` | JSON 会话记忆 | 已复用 |
| `src/arm_agent_demo/main.py` | CLI | 已接好 |
| `src/eval/eval_tasks.py` | 8 条示例任务 | 骨架 |
| `src/eval/eval_runner.py` | 评测 runner | 骨架 |
| `src/eval/eval_metrics.py` | Wilson CI / pass@k / 汇总 | 骨架 |
| `assets/franka_emika_panda/` | Menagerie Panda + 本项目场景 | 已就位 |

> `src/arm_agent_demo/skills.py` 是重构前留下的 MuJoCo 副本；当前 active 的是 `src/utils/skills.py`，可删除。

## 建议实现顺序

1. **`src/arm_agent_demo/sim.py`**：`__init__` → `_inspect_model` → `reset`；GUI 里看到 Panda + 3 方块 + 2 盘。
   - 物体位置在 `OBJECTS` 和 `scene_pick_place.xml` 里要一致。
2. **`src/utils/skills.py`**：`home → move_to_pose → move_above → grasp → release → pick_and_place`。
   - 先用 `--scripted` 跑通红块→蓝盘。
   - 抓取高度先打印 `hand` 与物体的相对位置校准；MVP 可用运动学吸附，别一开始调摩擦。
3. **`src/utils/tools.py`**：schema 已给全，按需调整；`bind` 已接好。
4. **`src/core/harness.py`**：FakeLLM 测试已提供，先跑通再接 DeepSeek。
5. **`src/eval/eval_runner.py` + `src/eval/eval_metrics.py`**：先 8 条，再扩到 20/50；成功判定只信 MuJoCo 真值。

## 设计约束

- LLM 只选技能和对象名，**不输出关节角或坐标**。
- 工具面只暴露 `list_objects / get_state / pick_and_place / home / request_clarification / report_infeasible`。
- 所有技能返回 `SkillResult(ok, code, message, hint, state)`；失败是正常返回值。
- 歧义任务必须 `request_clarification`，不可行任务必须 `report_infeasible`；评测看终态，不靠关键词。
- v1 抓取优先用运动学吸附/真实夹爪二选一；报告里必须标注抓取简化。
- 仅仿真，不代表真机安全设计。

## 已知限制

- `assets/` 里的 36MB 模型是 vendored；可以提交，也可以加到 `.gitignore` 后用上面的命令重建。
- 当前 `sim.py` 未实现前，`--scripted` 和自然语言模式都会抛 `NotImplementedError`，这是骨架的预期行为。
- MuJoCo viewer 走 GLFW；Wayland/niri 下可能要 Xwayland，headless 评测不受影响。
- 系统 ROS 2 Lyrical 的 pytest 插件（Python 3.14 的 `launch_testing`）会被自动加载，和 3.11 venv 冲突；测试时用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。
- `src/arm_agent_demo/skills.py` 是重构前副本，active 文件是 `src/utils/skills.py`。
- C++ 控制层是第二阶段；v1 全 Python，边界留在 `skills.py`。
