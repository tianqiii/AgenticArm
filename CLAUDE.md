# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

自然语言机械臂 Agent：DeepSeek 负责规划（function calling），MuJoCo 做物理仿真，技能层用 mink 微分 IK 执行确定性的抓取/放置。设计依据是 `DESIGN.md`，核心为第 5 章（中间层契约）和第 6 章（评测体系）。

核心链路已实现：`sim.py`、`utils/skills.py`、`eval_*.py` 均可用；`uv run arm-agent-demo --no-gui --scripted` 可在 headless 下跑通红块→蓝盘（约 1 秒）。自然语言模式需要 `DEEPSEEK_API_KEY`。抓取目前是**运动学吸附**（直接写物体 qpos），不是摩擦抓取。

代码注释、docstring、CLI 提示、设计文档统一用中文。

## 常用命令

```bash
uv sync
cp .env.example .env               # 填 DEEPSEEK_API_KEY；已存在的同名环境变量优先

uv run arm-agent-demo --help
uv run arm-agent-demo --scripted                    # 不接 LLM，硬编码 red_cube -> blue_plate
uv run arm-agent-demo "把红色方块放到蓝色盘子里"
uv run arm-agent-demo                               # 交互模式
uv run arm-agent-demo --no-gui --scripted           # headless

uv run arm-agent-eval --limit 3

# 测试：必须禁用插件自动加载（系统 ROS 2 的 pytest 插件与 3.11 venv 冲突）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q -m "not e2e"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/test_harness_fake_llm.py::test_tool_then_final -q
```

pytest 标记：`e2e`（真实 DeepSeek API）、`slow`；`pythonpath = ["src"]` 已在 `pyproject.toml` 配置。

## 架构

请求流：`main.py` → `Harness`（ReAct 循环）→ `LLM`（DeepSeek `/chat/completions`）→ `tools.py`（LLM 可见工具）→ `Skills` → `Sim`（MuJoCo）。

- `arm_agent_demo/sim.py`：MuJoCo 世界与真值。加载两个模型——完整场景 `scene_pick_place.xml` 用于物理，`panda.xml` 仅机器人本体用于 mink IK（避免 IK 移动自由物体）。物体/目标定义在 `OBJECTS`/`TARGETS`，必须与场景 XML 中的名称和位置一致。
- `utils/tools.py`：工具面刻意窄——`list_objects / get_state / pick_and_place / home / request_clarification / report_infeasible`。通过模块级 `bind(skills)` 注入 Skills 单例，`main.py` 和 eval runner 必须先 bind；`Harness` 默认使用这里的 `TOOL_FUNCS/TOOL_SCHEMAS`。
- `utils/skills.py`：确定性技能，统一返回 `SkillResult(ok, code, message, hint, state, metrics)`；失败是正常返回值，不是异常。`move_to_pose / move_above / grasp / release / reset` 是内部技能，不暴露给 LLM。
- `core/harness.py`：ReAct 循环。`request_clarification`/`report_infeasible` 是终态工具，命中后 `status` 变为 `clarify`/`infeasible` 并结束本轮；达到 `max_steps` 时禁用工具强制收尾（`status=max_steps`）。工具结果自动 JSON 序列化并记录 `ok/code`；每次运行追加写 `trace.jsonl`。
- `core/llm.py`：DeepSeek/OpenAI 兼容客户端，429/5xx 指数退避重试；从 `.env` 读 `DEEPSEEK_API_KEY`（或 `LLM_API_KEY`），环境变量优先；`LLM_BASE_URL` / `LLM_MODEL` 可覆盖。
- `core/memory.py`：JSON 文件按 session_id 存消息；原子写，文件损坏时先备份。
- `eval/`：任务集 → `run_episode` → 仿真真值 oracle → `summarize`（Wilson CI、pass@k、分类别 macro/micro 成功率）。评测只信 MuJoCo 真值，禁止 LLM-as-judge。

## 设计约束（改代码时必须保持）

- LLM 只选技能和物体规范名，**不输出坐标或关节角**；工具层不得新增 `set_object_position`、teleport 之类的能力。
- 歧义任务必须走 `request_clarification`，不可行任务走 `report_infeasible`；评测按终态判定，不靠关键词匹配。
- 所有动作先校验工作空间和前置条件，越界直接返回 `OUT_OF_WORKSPACE`，不要尝试。
- 仅仿真，不代表真机安全设计。

## MuJoCo/mink 易踩坑（已验证）

- `nq=30`、`nu=8`；keyframe：Menagerie 的 `home` 只有 9 个 qpos，本项目的 `scene_home` 有完整 30 个。
- 夹爪 ctrl 范围是 **0–255：255 开、0 合**（不是 0–0.04）。
- 末端帧用 body `hand`，Menagerie Panda 没有 grasp site；指尖 TCP 在 hand 局部 z≈0.10 m 处（finger body 0.0584 + 指垫约 0.04）。
- 抓取用运动学吸附：`Skills._sync_held` 每步把物体位姿写成 hand 位姿 × offset，物体不受碰撞/摩擦影响。这是 MVP 简化，报告里必须标注。
- mink 1.4 没有 `SO3.from_quaternion_xyzw`；默认保持当前 `hand` 姿态最稳。
- 修改 `mink.Configuration` 的 q 后必须 `config.update(q)`，否则运动学仍是 qpos0。
- GUI 走 GLFW；Wayland/niri 下可能需要 Xwayland，headless 评测不受影响。

## 现状说明

- 评测任务集目前 8 条（`eval_tasks.py`），后续按 DESIGN 第 6 章扩到 20/50 条；技能契约、对抗和 E2E 测试仍需补。
- `core/`、`utils/`、`eval/` 没有 `__init__.py`（命名空间包），导入方式是 `from core.harness import ...`、`from utils import tools`、`from eval.eval_runner import ...`。
- `sessions.json`、`trace.jsonl`、`.env`、`reports/` 均被 gitignore。
