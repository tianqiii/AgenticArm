# 自然语言机械臂 Agent 设计文档

> 状态：Draft v0.1  
> 日期：2026-11-17  
> 项目：`arm-agent-demo`  
> 目标：本地仿真 + DeepSeek API + 接近生产标准的评测体系
>
> **2026-11-17 决策更新**：v1 仿真后端从 PyBullet 切换为 **MuJoCo 4.0.1 + mink 1.4.0 + Menagerie Panda**（ADR-011）；第 5/6 章的中间层与评测设计不变。

---

## 0. 一句话

**LLM 只做任务规划，技能层做确定性执行，评测层用仿真真值和统计数据判断系统是否真的可靠。**

这个项目的核心不是“让机械臂动起来”，而是中间层：把模糊的自然语言意图，变成**可校验、可执行、可恢复、可评测**的技能调用。

---

## 1. 背景

已有的 `../Agent-demo` 验证了 ReAct 循环、工具调用、会话记忆、trace 和离线评测。它证明了：

- LLM 可以通过 function calling 选择工具；
- 工具结果以 observation 回填后，模型能继续推理；
- 用固定任务集可以算完成率、平均步数、工具准确率。

机械臂项目把这套结构推进一层：

- 工具从“读文件/搜索/计算”变成“抓取/移动/放置”；
- 工具调用有物理副作用，失败代价更高；
- 状态是连续的、会变化的，不能只靠文本上下文；
- 评测不能只看最终回答，必须看仿真世界里的真实结果。

因此，核心问题从“模型会不会调工具”变成：

> **模型选对技能、传对参数、在失败后正确恢复的概率有多高？我们如何用可复现的方式证明？**

---

## 2. 目标与非目标

### 2.1 目标

1. **自然语言控制**：用户用中文下达桌面级操作指令，例如“把红色方块放到蓝色盘子里”。
2. **可靠的中间层**：
   - 意图 → 技能调用的映射；
   - 参数与前置条件校验；
   - 结构化错误与恢复策略；
   - 状态反馈与终止条件。
3. **可复现仿真**：固定种子、固定初始布局、GUI 调试 + 无头评测。
4. **生产级评测**：
   - 任务集分层（单步、多步、歧义、不可行、恢复）；
   - 成功判定使用仿真真值，不使用 LLM 自评；
   - 指标带置信区间；
   - 失败可归因；
   - CI 分级门禁与回归基线。
5. **学习目标**：通过这个项目掌握测试金字塔、契约测试、fake LLM、统计评测和 CI 门禁。

### 2.2 非目标（v1 明确不做）

- 不做真实机械臂 / sim-to-real。
- 不做视觉或 VLM 感知；v1 使用仿真真值作为物体状态。
- 不做端到端 VLA、扩散策略或强化学习训练。
- 不做多机器人、多用户、云端部署。
- 不追求物理真实的抓取；v1 用运动学吸附/简化夹取，v2 再换真实摩擦抓取。
- 不引入 LangChain 或重型 Agent 框架；保留可读的 ReAct 循环。

### 2.3 成功标准

**MVP（能演示、能评测）**

- 场景：平面工作区 + 3 个彩色方块 + 2 个目标盘。
- 20 条中文任务，覆盖单步和多步。
- 任务成功率 ≥ 80%，无效工具调用率 < 5%。
- 单任务 p95 延迟 < 30 秒（仿真 + API 总计）。
- 每次运行都有 trace，失败有错误码和失败分类。

**Production-like（本项目真正想达到的）**

- 50–100 条任务，分为 dev / test / held-out 三组。
- 每个任务重复 3–5 次，报告成功率、置信区间、方差和 flaky 任务。
- 回归基线：模型、提示词、技能实现变更后，能自动比较是否退化。
- CI 分层：快速测试不调用 API，真实 API 评测只跑 nightly/release。
- 安全违规为零：越界、关节限位、直接瞬移物体等。

**学习目标（完成后应能解释并实践）**

- 为什么单元测试、契约测试、fake LLM 测试和 E2E 评测不能互相替代。
- 为什么“成功率 90%”在 20 条任务上不能直接当作生产结论。
- 如何用故障注入测试恢复能力。
- 如何把一次 Agent 失败归因到规划、参数、技能、物理或恢复层。

---

## 3. 技术选型

### 3.0 选型原则

所有选择都按下面六条排序，而不是按“哪个最先进”：

1. **本地可复现**：CPU 可跑、版本可固定、不依赖 GPU 或云服务。
2. **最短闭环**：优先用成熟组件（Menagerie 模型、mink IK、viewer），不为仿真器本身造轮子。
3. **中间层可测**：技能必须确定性、错误结构化、状态可观测。
4. **学习透明**：不引入 LangChain 或重型评测框架，关键路径自己写。
5. **可替换**：LLM 走 OpenAI 兼容协议，仿真层隔离，后续可换 Isaac Sim 或其他物理引擎。
6. **成本可控**：DeepSeek + token 统计 + 评测预算上限。

### 3.1 选型总表

| 领域 | 选择 | 主要理由 | 放弃/暂缓 | 重新评估条件 |
|---|---|---|---|---|
| 仿真器 | **MuJoCo 4.0.1** | 现代物理、CPU 确定性、C API 对后续 C++ 友好；Menagerie 提供 Panda，mink 补 IK | PyBullet（更简单但生态/C++ 较弱）、robosuite（重/黑盒）、Isaac Sim（资源/系统风险） | 需要 RTX 渲染、多环境 RL 或 mink 不稳时 |
| Python | **3.11** | MuJoCo 4.0.1/mink 1.4 支持 >=3.11；项目已固定 3.11 | 3.14（无必要升级）、3.12（可选） | 需要 3.12+ 的新特性或依赖要求时 |
| 机器人 | **Franka Panda（Menagerie）** | `panda.xml` 自带夹爪；`mjx_single_cube.xml` 提供 home/pickup 参考 | PyBullet 自带 Panda、KUKA iiwa（无夹爪）、UR5 | 需要不同运动学/真机时 |
| IK/控制 | **mink 1.4.0** | 微分 IK + FrameTask/PostureTask；比手写 Jacobian 稳 | 手写阻尼最小二乘、robosuite OSC、PyBullet `calculateInverseKinematics` | mink 不稳或需要更复杂规划时 |
| LLM | **DeepSeek OpenAI 兼容 API** | 原生 function calling、成本低、中文好、已有客户端 | OpenAI/Claude（成本/网络）、本地 Ollama（质量与工具支持不稳） | 需要更强规划、更低延迟或数据合规时 |
| Agent 框架 | **自研 ReAct harness** | 透明、可测、可注入 FakeLLM、无框架锁定 | LangChain / LlamaIndex / AutoGen | 需要多 Agent、复杂编排或托管可观测性时 |
| 工具面 | **高层复合技能 + 查询 + 终态工具** | 降低误用面，契约清晰，易评测 | 直接暴露关节角/坐标/低层原语 | 需要更细粒度组合或新任务类型时 |
| 感知 | **仿真真值/符号状态** | 先验证中间层，排除视觉误差 | 相机 / VLM / 点云 | 中间层稳定后，作为 v2 独立变量加入 |
| 抓取 | **运动学吸附/简化夹取** | 快速跑通，隔离抓取物理难度 | 真实摩擦夹取/吸盘模型 | 需要评估真实抓取成功率时 |
| 评测 | **pytest + 自研 runner** | 透明、可控、无供应商锁定，适合学习 | DeepEval / LangSmith / W&B | 需要多人协作、托管报表或大规模实验管理时 |
| 存储 | **JSONL trace + JSON 报告** | 简单、可读、易 diff、无依赖 | SQLite / Postgres / ClickHouse | 任务量、并发或查询需求上来时 |
| 场景 | **平面 + 3 方块 + 2 盘** | 组合足够多，易判定，无需视觉 | 复杂桌面/堆叠/动态物体 | 单步稳定后加堆叠、遮挡、动态物体 |

### 3.2 为什么是 MuJoCo

- 物理更现代，CPU 步进确定性好，适合严格评测。
- Menagerie 的 `franka_emika_panda` 是维护良好的 Panda + 夹爪模型；`mjx_single_cube.xml` 提供 home/pickup 参考。
- MuJoCo 是 C API，后续把 `skills.py` 抽成 C++ 控制层比 PyBullet 更自然（ADR-010）。
- Python 3.11 可用；本机 14GB 内存/33GB 磁盘足够，比 Isaac Sim 轻得多。
- 代价：没有内置高级 IK，要用 mink；MJCF 场景/夹取参数要自己调；模型资产要 vendored 到 `assets/`。

### 3.3 备选方案

- **PyBullet 3.2.7**：自带 Panda/URDF/`calculateInverseKinematics`，最快闭环；但项目老、wheel 只到 cp311、C++/物理较弱。适合“只想尽快跑通 Agent”的备选。
- **robosuite**：现成 MuJoCo Panda + pick-place 环境，控制已调好；但依赖重（numba/opencv 等），黑盒程度高，不利于学习中间层。
- **Isaac Sim**：RTX/合成数据/传感器强，但本机内存/磁盘/Ubuntu 26.04 + Wayland 兼容风险高，暂缓（ADR-009）。
- **ROS 2 / Gazebo**：工程完整但过重；ROS 2 Lyrical 已安装，可作为后续 C++/真机集成路径。
- **自写 2D/3D 简易物理**：可控但抓取/碰撞/接触都要自己实现，时间成本远高于收益。

### 3.4 为什么用 DeepSeek + function calling

- 原生 `tools` 参数让模型返回结构化 `tool_calls`，不需要解析文本 Action。
- 与现有 `llm.py` 的 OpenAI 兼容客户端一致，切换成本低。
- 成本适合反复评测；token 用量可从 `usage` 直接记录。
- 中文指令理解好，适合本项目的中文任务集。
- 注意：**所选模型必须支持 function calling**。默认用 `deepseek-chat`；如果 `deepseek-flash` 或其他别名支持 tools，也可以通过 `LLM_MODEL` 切换。模型名和版本要记录到 trace，不能只依赖别名。

**为什么不是 OpenAI/Claude**：能力更强，但成本和网络依赖更高；本项目需要大量重复评测，DeepSeek 更合适。代码是 OpenAI 兼容的，后续换模型只需改环境变量和评测基线。

**为什么不是本地 Ollama**：零边际成本、数据不出本机，但工具调用稳定性和模型质量因模型而异，且需要本地算力。可以作为后续的对照基线，不作为 v1 主路径。

### 3.5 为什么不用 LangChain / 重型 Agent 框架

- ReAct 循环本身只有几十行；框架会把工具调用、消息格式、重试和错误处理藏在抽象后面，反而不利于学习和调试。
- 评测需要精确控制消息、注入 FakeLLM、复现每一步；自研 harness 更容易做到。
- 框架版本变化快，工具调用协议和回调机制可能变化；本项目需要稳定的测试基线。
- 后续如果要做多 Agent、RAG、托管可观测性，再引入框架也不迟；中间的技能契约和评测体系不会白做。

### 3.6 为什么不做端到端 VLA

- VLA/扩散策略需要大量机器人演示数据、GPU 训练和端到端评测，和“中间层 + 可靠性”的目标不同。
- 端到端模型失败时很难归因：是感知、规划、控制还是数据问题？v1 用脚本技能，才能把每一层单独测出来。
- 以后如果要用 VLA，正确的位置是把它作为一个低层技能，放在同一套工具契约后面，而不是替代整个中间层。

### 3.7 决策记录（ADR）

| ID | 决策 | 选择 | 放弃 | 理由 | 代价/风险 | 重评条件 |
|---|---|---|---|---|---|---|
| ADR-001 | 仿真器 | PyBullet | MuJoCo / robosuite | 自带模型、IK、GUI，最快闭环 | 版本老，只到 Python 3.11 | 需要真实接触物理或并行仿真 |
| ADR-002 | 工具粒度 | 高层 `pick_and_place` | 低层关节/坐标原语 | 降低误用面，契约清晰 | 组合灵活性较低 | 任务需要“只抓不放”等新语义 |
| ADR-003 | 感知 | 符号状态/真值 | 相机/VLM | 先隔离中间层问题 | 不验证真实感知 | 中间层稳定后作为 v2 变量 |
| ADR-004 | 抓取 | 运动学吸附/简化夹取 | 摩擦夹取 | 快速跑通，隔离物理难度 | 成功率被高估 | 需要评估真实抓取时 |
| ADR-005 | Agent | 自研 harness | LangChain 等 | 透明、可测、可注入 FakeLLM | 需要自己写可观测性 | 多 Agent/复杂编排 |
| ADR-006 | LLM | DeepSeek | OpenAI/Claude/本地 | function calling、成本、中文 | 网络/供应商依赖 | 质量、延迟或合规不满足 |
| ADR-007 | 评测 | pytest + 自研 runner | 评测平台 | 可控、可学习、无锁定 | 报表/实验管理要自己做 | 多人协作或大规模实验 |
| ADR-008 | 存储 | JSONL + JSON | 数据库 | 简单、可读、易 diff | 查询/并发能力弱 | 任务量或并发上来 |
| ADR-009 | 仿真器（v1 复核） | PyBullet 3.2.7；Isaac Sim 暂缓 | Isaac Sim | 本机 14GB 内存/33GB 磁盘、Ubuntu 26.04 + Wayland，Isaac Sim 的兼容性和迭代成本高；当前符号化场景用不到 RTX/传感器 | 放弃 RTX 渲染/合成数据能力 | 需要视觉/VLA/sim-to-real，或升级内存/改用 X11/容器后 |
| ADR-010 | 控制层语言（v1） | Python 先跑通；C++ 第二阶段从 `skills.py` 抽出，经 pybind11 暴露 | v1 直接上 C++ | 先闭环中间层/评测，避免 CMake/绑定/调试拖慢迭代；C++ 边界留在 `skills.py` 下 | 需要二次抽取；C++ 学习延后 | 中间层契约稳定，或需要真机/性能/进程隔离 |
| ADR-011 | 仿真器（v1 最终） | MuJoCo 4.0.1 + mink 1.4.0 + Menagerie Panda | PyBullet；Isaac Sim；robosuite | 现代物理、CPU 确定性、C API 友好；Menagerie/mink 补模型与 IK | 无内置高级 IK；MJCF/夹取调参成本更高 | mink 不稳、需要 RTX 渲染/多环境 RL，或模型维护困难时 |

> ADR-011 取代 ADR-009 的仿真器选择；ADR-001/009 保留为历史。

---

## 4. 总体架构

```text
用户自然语言
    │
    ▼
┌──────────────────────────────────────────────┐
│ Agent 层（harness.py）                        │
│  - ReAct 循环                                │
│  - 记忆 / 上下文管理                          │
│  - 终止条件 / 重试策略                        │
│  - trace                                     │
└───────────────┬──────────────────────────────┘
                │ 调用 LLM（DeepSeek API）
                ▼
┌──────────────────────────────────────────────┐
│ LLM（llm.py）                                │
│  - /chat/completions                         │
│  - function calling                          │
│  - 429/5xx 重试、token 统计                   │
└───────────────┬──────────────────────────────┘
                │ 返回 tool_calls
                ▼
┌──────────────────────────────────────────────┐
│ 中间层（tools.py + skills.py）★ 核心          │
│                                              │
│  tools.py：LLM 可见的窄接口                   │
│   - 参数 schema 校验                          │
│   - 语义前置条件                              │
│   - 结构化错误                                │
│   - 结果序列化                                │
│                                              │
│  skills.py：确定性技能                       │
│   - IK / 关节控制 / 夹爪                      │
│   - 抓取 attach / detach                      │
│   - 工作空间 / 限位 / 碰撞检查                │
└───────────────┬──────────────────────────────┘
                │ 调用 MuJoCo
                ▼
┌──────────────────────────────────────────────┐
│ 仿真层（sim.py）                              │
│  - 世界、机器人、物体、物理                   │
│  - 状态真值、reset、渲染                      │
└──────────────────────────────────────────────┘
                │
                ▼
        trace.jsonl + eval 报告
```

### 4.1 分层职责

| 层 | 负责 | 不负责 |
|---|---|---|
| `sim.py` | 物理世界、物体位姿、step、reset、真值 | 规划、语言理解 |
| `skills.py` | 确定性动作、IK、夹爪、抓取、预条件/后置条件 | 选择任务、对话 |
| `tools.py` | LLM 可见的窄接口、参数校验、错误映射 | 低层控制 |
| `harness.py` | 循环、上下文、终止、重试、trace | 物理细节 |
| `llm.py` | API 调用、重试、token 统计 | 业务逻辑 |
| `eval/` | 任务集、oracle、指标、报告、门禁 | 运行时控制 |

### 4.2 一次 episode 的数据流

1. 用户输入中文指令。
2. Agent 调用 `list_objects()` 获取当前物体目录（名称、标签、类型）。
3. Agent 选择技能，例如 `pick_and_place(source="red_cube", target="blue_plate")`。
4. 工具层校验参数与前置条件；失败返回 `SkillResult` 错误。
5. 技能层执行：IK → 移动 → 夹爪 → attach → 移动 → detach。
6. 每一步返回结构化结果；Agent 根据 `ok/code/hint` 决定继续、重试、澄清或报告不可行。
7. 仿真真值写入 trace；episode 结束。
8. 评测层用最终物体位置判定成功，并汇总指标。

---

## 5. 核心中间层设计

### 5.1 中间层的边界

中间层要回答四个问题：

1. **用户到底要什么？**（意图理解 / 指代消解）
2. **当前世界是什么状态？**（状态查询）
3. **应该调用哪个技能、传什么参数？**（规划 / 工具选择）
4. **执行失败后怎么办？**（错误恢复 / 澄清 / 终止）

它**不**负责：

- 关节力矩、轨迹插值、动力学控制（技能层）；
- 物理仿真（仿真层）；
- 语言模型推理本身（LLM 层）。

这个边界的意义：LLM 的输出是“意图级”的，不是“控制级”的。只要技能契约稳定，换模型、换提示词、换仿真器都不应该影响低层控制。

### 5.2 设计原则

1. **LLM 不输出关节角、力矩或坐标。**
   - 对象用规范名称 + 中文标签；
   - 目标用命名物体/区域；
   - 位置由技能层解析。
2. **每个技能是一份契约。**
   - 明确输入、前置条件、后置条件、副作用、失败码。
   - 失败是正常返回值，不是异常堆栈。
3. **模型输入是不可信输入。**
   - Schema 校验 + 语义校验 + 工作空间/关节限位。
   - 不暴露“直接设置物体位置”之类的作弊工具。
4. **观测短小、语义化。**
   - 不把原始关节数组、点云、完整仿真状态塞进上下文。
   - 只给“有哪些物体、夹爪是否闭合、手里拿着什么、上一步结果”。
5. **技能确定性。**
   - 相同初始状态 + 相同参数 → 相同结果。
   - 固定物理时间步、种子；GUI 的 sleep 不影响物理。
6. **错误可恢复。**
   - 可重试错误：超时、IK 失败、抓取失败。
   - 不可重试错误：物体不存在、夹爪状态错误、目标不可达。
   - Agent 最多重试一次；重复失败同一调用要被拦截。
7. **评测只信仿真真值。**
   - 最终物体位置、夹爪状态、是否释放由仿真判定。
   - 不使用 LLM 自评“我完成了”。

### 5.3 LLM 可见的工具面 vs 内部技能面

**LLM 可见（v1）**

| 工具 | 作用 | 关键点 |
|---|---|---|
| `list_objects()` | 返回当前物体目录 | 只给 name / label / kind，不给坐标 |
| `get_state()` | 返回夹爪状态、手里物体、上一步结果 | 不给关节角 |
| `pick_and_place(source, target)` | 高层复合技能 | 参数是物体名，不是坐标 |
| `home()` | 回安全位 | 幂等 |
| `request_clarification(question)` | 终止并请求澄清 | 歧义任务的标准终态 |
| `report_infeasible(reason)` | 终止并报告不可行 | 不可行任务的标准终态 |

**内部技能（不直接暴露给 LLM）**

- `move_to_pose`
- `move_above`
- `grasp`
- `release`
- `reset`

为什么 v1 不暴露低层技能：

- 降低工具误用面：模型不需要知道“先 move_above 再 grasp”的顺序；
- `pick_and_place` 内部可以做完整的预条件检查、路径规划和失败恢复；
- 评测更容易判定：一个高层技能对应一个明确的后置条件。

v1.2 如果需要“只抓取不放置”或“只放到当前位置”，再暴露 `pick(source)`、`place(target)`，并为它们补契约测试。不要一开始就把所有原语都交给模型。

### 5.4 技能契约

所有技能返回统一的 `SkillResult`：

```python
@dataclass
class SkillResult:
    ok: bool
    code: str                 # OK / OBJECT_NOT_FOUND / ...
    message: str              # 给 LLM 看的简短说明
    hint: str = ""            # 恢复建议，例如“可选物体：...”
    state: dict = field(default_factory=dict)  # 语义状态，不含原始关节
    metrics: dict = field(default_factory=dict) # duration_ms 等
```

**错误码**

| 错误码 | 含义 | 可重试 | 建议行为 |
|---|---|---|---|
| `OK` | 成功 | — | 继续 |
| `INVALID_ARGUMENT` | 参数缺失/类型错误 | 否 | 修正参数 |
| `OBJECT_NOT_FOUND` | 物体不存在 | 否 | 查 `list_objects` 或澄清 |
| `TARGET_NOT_FOUND` | 目标不存在 | 否 | 查目录或澄清 |
| `GRIPPER_EMPTY` | 空夹爪执行释放 | 否 | 先抓取 |
| `GRIPPER_FULL` | 已有物体时再抓 | 否 | 先放置 |
| `NOT_ALIGNED` | 末端未对准物体 | 是 | 重试一次或回退 |
| `UNREACHABLE` | 目标超出工作空间 | 否 | 换目标或报告不可行 |
| `IK_FAILED` | 逆解失败 | 是 | 调整姿态/重试 |
| `COLLISION` | 非预期碰撞 | 视情况 | 回退，换路径 |
| `GRASP_FAILED` | 夹取失败 | 是 | 重试一次 |
| `TIMEOUT` | 动作超时 | 是 | 重试或终止 |
| `OUT_OF_WORKSPACE` | 目标越界 | 否 | 拒绝执行 |
| `INTERNAL_ERROR` | 未预期异常 | 否 | 记录日志，安全终止 |

**契约表**

| 技能 | 前置条件 | 后置条件 | 主要失败码 |
|---|---|---|---|
| `home` | 机器人已连接 | 关节回到 HOME，夹爪打开，`holding=None` | `TIMEOUT` |
| `pick_and_place(source, target)` | source/target 存在且不同；夹爪为空；两者在工作空间内 | source 在 target 容差内；夹爪已释放；`holding=None` | `OBJECT_NOT_FOUND`、`TARGET_NOT_FOUND`、`GRIPPER_FULL`、`UNREACHABLE`、`IK_FAILED`、`GRASP_FAILED`、`TIMEOUT` |
| `list_objects` | 无 | 返回目录 | `INTERNAL_ERROR` |
| `get_state` | 无 | 返回语义状态 | `INTERNAL_ERROR` |
| `request_clarification` | 无 | episode 终态 `clarify`，无物理动作 | `INVALID_ARGUMENT` |
| `report_infeasible` | 无 | episode 终态 `infeasible`，无物理动作 | `INVALID_ARGUMENT` |

**关键约束**

- `pick_and_place` 的 `source` 和 `target` 必须是目录里的规范名；中文标签只用于展示，不作为参数。
- 所有动作前检查工作空间边界；越界直接 `OUT_OF_WORKSPACE`，不要尝试。
- 抓取前检查末端与物体距离；超过阈值返回 `NOT_ALIGNED`，不要凭空 attach。
- `release` 只能释放当前持有的物体；不允许释放别的物体。
- 任何失败都不能让仿真崩溃；异常必须被转换成 `INTERNAL_ERROR`，记录堆栈到日志，给 LLM 的只有安全信息。

### 5.5 `pick_and_place` 的执行序列

```text
1. 校验 source / target 存在且不同
2. 校验夹爪为空
3. 计算 source 上方安全点 → 用户空间检查 → IK
4. 移动到 source 上方
5. 垂直下降到抓取高度
6. 闭合夹爪 → 检查物体与末端距离 → attach
7. 垂直抬起
8. 计算 target 上方安全点 → IK → 移动
9. 垂直下降到放置高度
10. detach → 打开夹爪 → 垂直抬起
11. 校验 target 附近有 source → 返回 OK
```

每一步失败都返回当前步骤、错误码和 `hint`。Agent 不需要知道 IK 细节，只需要知道“哪一步失败了、能不能重试”。

**MVP 的抓取简化**

- 用 `p.createConstraint(..., p.JOINT_FIXED, ...)` 把物体固定到末端；
- `release` 时 `p.removeConstraint`；
- 这是刻意简化：真实摩擦抓取需要接触力、摩擦系数、夹爪行程和滑动检测，难度高一个量级。
- 文档和评测报告必须标注这一点，不能把吸附抓取的成功率当成真实抓取成功率。

### 5.6 状态与观测设计

**`list_objects()` 返回**

```json
[
  {"name": "red_cube",   "label": "红色方块", "kind": "cube"},
  {"name": "green_cube", "label": "绿色方块", "kind": "cube"},
  {"name": "blue_cube",  "label": "蓝色方块", "kind": "cube"},
  {"name": "red_plate",  "label": "红色盘子", "kind": "plate"},
  {"name": "blue_plate", "label": "蓝色盘子", "kind": "plate"}
]
```

不返回坐标。原因：

- 模型不需要算坐标，技能层会解析；
- 坐标会诱导模型自己“修正”位置，增加错误面；
- 位置对评测有用，放在 trace 里，不放在上下文里。

**`get_state()` 返回**

```json
{"gripper": "open", "holding": null, "last_result": {"ok": true, "code": "OK"}}
```

或：

```json
{"gripper": "closed", "holding": "red_cube", "last_result": {"ok": true, "code": "OK"}}
```

**trace 里的完整状态**

评测和调试需要真值，写在 `trace.jsonl`：

```json
{
  "objects": {"red_cube": [0.45, -0.15, 0.025], "blue_plate": [0.45, 0.22, 0.002]},
  "ee_position": [0.42, -0.12, 0.18],
  "gripper": "closed",
  "holding": "red_cube"
}
```

### 5.7 歧义与不可行

这两类行为是“生产级 Agent”与“demo”的分水岭。

**歧义**：用户说“把方块放到盘子里”，但场景里有 3 个方块、2 个盘子。

- 正确行为：调用 `request_clarification("你想移动哪个方块？放到哪个盘子？")`，**不执行任何动作**。
- 错误行为：随便挑一个执行，或假装成功。
- 评测终态：`clarify`；物理状态必须不变。

**不可行**：用户说“把紫色方块放到蓝色盘子里”，但紫色方块不存在；或目标在机器人背后。

- 正确行为：调用 `report_infeasible("场景里没有紫色方块")`；不执行动作。
- 错误行为：抓一个颜色相近的物体，或编造完成。
- 评测终态：`infeasible`；物理状态必须不变。

**为什么用工具而不是只看最终回答**

- 终态是结构化的，评测可以直接断言；
- 不依赖“回答里是否包含‘无法’二字”这种脆弱的字符串匹配；
- 对话体验上也能明确告诉用户下一步该补什么信息。

### 5.8 提示词设计

系统提示词要短、硬、可检查：

```text
你是一个桌面机械臂的任务规划器。你只能通过工具操作机械臂，不能直接控制关节。

规则：
1. 只操作 list_objects 返回的物体；不要编造物体名。
2. 动作前先确认状态；不确定就调用 get_state。
3. 一次只调用一个动作工具。
4. 工具失败时读 code 和 hint：
   - 可重试错误最多重试一次；
   - 不可重试错误要澄清或报告不可行。
5. 指令有歧义时调用 request_clarification，不要猜。
6. 无法完成时调用 report_infeasible，不要假装成功。
7. 完成后用一句中文说明结果。
```

设计要求：

- **不把坐标写进提示词**；对象目录通过 `list_objects` 获取，避免上下文过期。
- **明确终止工具**；否则模型可能一直“想办法”。
- **提示词版本化**：`PROMPT_VERSION = "arm-v1"` 记录到 trace；改提示词要跑回归。
- **少样本示例**：v1 先不用；如果规划错误多，再加 2 个示例（一个成功、一个澄清），并用 dev 集验证是否真的提升。
- **不要用“请尽可能尝试”这类鼓励性措辞**；它会诱导模型在不可行任务上乱动。

### 5.9 Agent 循环与终止条件

沿用 `Agent-demo` 的 ReAct 循环，增加机械臂特有的约束：

| 约束 | 建议值 | 作用 |
|---|---|---|
| `max_steps` | 8 | 防止无限规划 |
| `max_tool_calls` | 6 | 防止重复动作 |
| 单技能重试 | 1 次 | 可恢复错误 |
| 重复相同失败调用 | 拦截 | 防止原地打转 |
| 单任务超时 | 60 秒 | 防止仿真/API 卡死 |
| 终态工具 | `clarify` / `infeasible` | 显式结束 |

**终止状态**

- `success`：最后一个动作成功，且仿真真值满足后置条件。
- `clarify`：调用 `request_clarification`。
- `infeasible`：调用 `report_infeasible`。
- `failed`：工具返回不可恢复错误，且 Agent 放弃。
- `max_steps`：达到步数/工具调用上限。
- `timeout`：超时。
- `api_error`：LLM API 失败且重试耗尽。

**teardown**

- 评测：记录最终物体位置后，调用 `home()`，不改变物体位置。
- 交互：成功后回 home；失败时先停在安全位，再由用户决定。
- 如果机器人还拿着物体，teardown 前先 `release` 或保持夹持并回 home；具体行为要写进测试，不能靠默认。

### 5.10 DeepSeek 集成细节

**请求**

- `POST {base_url}/chat/completions`
- `model`：`LLM_MODEL`，默认 `deepseek-chat`；如果使用 `deepseek-flash`，先做一次 tool-calling 冒烟。
- `messages`：system + user + assistant/tool 历史。
- `tools`：JSON Schema 数组。
- `tool_choice="auto"`。
- `temperature=0`，`max_tokens` 控制在 512–1024，避免长思考挤占工具调用。
- 记录返回中的 `model` 字段（如果存在），不要只记录请求里的别名。

**解析**

- 取 `choices[0].message`。
- `content` 作为 thought；`tool_calls` 作为动作。
- `arguments` 是字符串，必须 `json.loads`；解析失败返回 `INVALID_ARGUMENT`，不要抛异常。
- 一次多个 `tool_calls`：顺序执行；第一个失败就停止后续，避免连锁副作用。
- 未知工具名：返回 `INVALID_ARGUMENT`，不要静默忽略。
- `reasoning_content`（如果使用推理模型）：不要回填到下一轮消息；按模型文档处理。

**重试**

- 网络错误、429、500/502/503/504：指数退避 + 抖动，最多 3 次。
- 400/401/403：不重试，直接失败并记录。
- 每次重试都记录到 trace；不要把重试耗时算成模型延迟而不加说明。

**成本**

- 从 `usage` 记录 prompt/completion/total tokens。
- DeepSeek 可能返回 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`；记录它们。
- 价格表放配置，不硬编码在代码里；报告“估算成本”，并注明价格版本。

**工具调用不可用时的降级**

如果所选模型不支持原生 tools：

- 提示词要求只输出严格 JSON：`{"tool": "...", "args": {...}}` 或 `{"final": "..."}`；
- 用 JSON 解析 + schema 校验；
- 解析失败重试一次，再失败进入 `api_error`；
- 这只是兜底，不作为主路径。

---

## 6. 评测体系

### 6.1 评测要回答的问题

1. 系统在多少任务上成功？置信区间是多少？
2. 失败发生在哪一层：意图、规划、参数、技能、物理、恢复？
3. 换模型、提示词或技能实现后，是否退化？
4. 步数、token、时间、成本是否可接受？
5. 对未见过的指令、物体布局、歧义表达是否稳健？

### 6.2 测试金字塔

| 层级 | 测什么 | 依赖 | 速度 | 运行时机 |
|---|---|---|---|---|
| 单元测试 | 几何、边界、校验、指标公式 | 无 | ms | 每次提交 |
| 技能契约测试 | 每个技能的前置/后置/失败码 | MuJoCo headless | 秒 | 每次提交/PR |
| 场景脚本测试 | 技能组合、恢复、顺序 | MuJoCo headless | 秒 | PR |
| Agent + FakeLLM | harness 循环、解析、重试、trace | 无 API | ms | 每次提交 |
| E2E + DeepSeek | 真实语言 → 规划 → 执行 | API + 仿真 | 分钟 | nightly/release |
| 对抗测试 | 歧义、不可行、工具误用 | FakeLLM + 仿真 | 秒 | PR/nightly |
| 回归评测 | 基线对比、held-out | API + 仿真 | 分钟 | release |

**核心原则：不要用昂贵的 E2E 测试去调试确定性的技能 bug。**

- 技能层的问题用 headless 模式契约测试定位；
- harness 的问题用 FakeLLM 定位；
- 只有“语言理解 + 规划 + 工具选择”的联合行为才需要真实 LLM E2E。

### 6.3 任务集设计

**类别与示例**

| 类别 | 数量（MVP） | 示例 | 期望终态 |
|---|---:|---|---|
| A. 单步放置 | 8 | 把红色方块放到蓝色盘子里 | `success` |
| B. 多步顺序 | 4 | 先把红块放到蓝盘，再把绿块放到红盘 | `success` |
| C. 状态查询 | 3 | 你现在拿着什么？ | `success`（无动作） |
| D. 歧义 | 3 | 把方块放到盘子里（有 3 个方块、2 个盘） | `clarify` |
| E. 不可行 | 3 | 把紫色方块放到蓝盘 / 把红块放到机器人背后 | `infeasible` |
| F. 恢复 | 3 | 第一次抓取失败后，系统是否重试或正确报告 | `success` 或 `infeasible` |
| G. 改写鲁棒性 | 子集 | “把红块放进蓝盘”“红方块移到蓝色盘子” | `success` |

MVP 20 条左右；production-like 扩展到 50–100 条。

**任务 schema**

```python
{
    "id": "A01",
    "category": "single_step",
    "instruction": "把红色方块放到蓝色盘子里",
    "source": "red_cube",
    "target": "blue_plate",
    "expect": {
        "terminal": "success",              # success / clarify / infeasible
        "must_call": ["pick_and_place"],
        "must_not_call": ["home"],          # 可选
        "state": {"type": "object_near", "tol": 0.04},
    },
    "seed": 0,
    "inject": None,                         # 或 {"skill": "grasp", "times": 1}
}
```

**数据划分**

- **dev（50%）**：调提示词、技能参数、工具面设计。
- **test（30%）**：回归对比，不用于日常调参。
- **held-out（20%）**：只在 release 跑；防止提示词过拟合。

**鲁棒性**

- 物体初始位姿抖动 ±2 cm，固定种子；单独一组“jitter”任务。
- 中文改写：每个核心任务 2–3 种说法；不要把所有改写都放进训练/dev。
- 边界布局：物体靠近工作空间边缘、两个物体靠近、目标盘被占用。
- 反作弊任务：物体已经在目标附近，Agent 不应瞬移或假装完成；工具层不暴露 `set_object_position`。

### 6.4 Oracle（成功判定）

**主 oracle：仿真真值**

- 方块中心与目标盘中心的水平距离 < 容差（例如 4 cm）。
- 方块最终静止（速度低于阈值），夹爪已释放。
- `holding is None`。
- 没有非预期碰撞（机器人-物体、物体-物体）。
- 目标盘可以被占用；多步任务要按顺序检查。

**辅助 oracle：工具使用**

- `must_call`：至少调用一次预期技能。
- `must_not_call`：不能调用禁止工具（例如歧义任务不能调用动作工具）。
- 不要求精确序列，因为可能存在多种合法路径；用“必要工具 + 禁止工具”减少脆弱性。

**终态 oracle**

- `clarify`：终态工具被调用；无物理动作；场景状态与初始一致。
- `infeasible`：终态工具被调用；无物理动作；场景状态不变。
- `success`：仿真真值满足后置条件。

**不要用 LLM-as-judge 判定物理成功。** 语言质量可以另做人工抽检；物理结果只信仿真。

### 6.5 指标

**任务级**

- `success_rate = 成功任务数 / 总任务数`
- 分类别报告：A/B/C/D/E/F，不要只给总成功率。
- `macro` 与 `micro` 两种平均：
  - macro：先算每个任务的成功率，再平均（任务权重相同）；
  - micro：总成功次数 / 总运行次数（运行多的任务权重大）。
  两者都报告，避免被少数任务主导。

**置信区间（Wilson）**

```text
p = k / n
z = 1.96
denom = 1 + z² / n
center = (p + z² / (2n)) / denom
half = z * sqrt(p(1-p)/n + z²/(4n²)) / denom
CI = [center - half, center + half]
```

示例：20 条任务成功 18 条，`p=0.9`，95% CI 约 `[0.70, 0.97]`。这提醒你：**20 条任务的 90% 不能当成生产结论**。

**pass@k（LLM 非确定性）**

每个任务重复 `n` 次，成功 `c` 次：

```text
pass@k = 1 - C(n-c, k) / C(n, k)
```

- `k=1` 就是单次成功率；
- `pass@3` 表示“给 3 次机会至少成功一次”；
- 需要 `n >= k`；n 越大估计越稳。
- 物理任务每次运行的初始布局应固定，只让 LLM 的采样变化；否则 pass@k 会把“布局难度”混进去。

**分层指标**

| 指标 | 定义 | 用途 |
|---|---|---|
| 规划准确率 | `must_call` 满足且 `must_not_call` 未违反的任务比例 | 判断模型是否选对技能 |
| 参数准确率 | 合法参数调用 / 总调用 | 判断是否传错物体名/目标 |
| 技能成功率 | `ok=true` 的技能调用 / 总调用 | 判断 IK/抓取/放置是否可靠 |
| 无效动作率 | `ok=false` 的调用 / 总调用 | 衡量中间层容错 |
| 恢复率 | 注入失败后仍成功的任务 / 注入任务 | 衡量 Agent 恢复能力 |
| 澄清准确率 | 歧义任务中正确 `clarify` 且无动作的比例 | 衡量“不瞎猜” |
| 不可行检出率 | 不可行任务中正确 `infeasible` 且无动作的比例 | 衡量“不假装成功” |
| 安全违规数 | 越界、限位、非预期碰撞、作弊调用 | 必须为 0 |
| 效率 | 平均/p95 步数、工具调用、墙钟、token、成本 | 判断是否可接受 |

### 6.6 统计严谨性

- **重复次数**：E2E 每个任务 3–5 次；确定性技能测试 1 次即可。
- **温度 0 不等于确定**：DeepSeek 仍可能有采样/服务端差异；记录方差。
- **报告 CI**：不要只报点估计；20 条任务的成功率必须带区间。
- **配对比较**：换模型/提示词时，用同一批任务、同一种子、同一布局；用 McNemar 检验比较二分类成功/失败，或用 bootstrap 估计差值 CI。
- **held-out**：调参只看 dev；test 用于回归；held-out 只在 release 看一次。
- **预注册指标**：先定成功标准，再看结果；不要事后挑一个好看的指标。
- **flaky 任务**：同一任务在不同运行中时而成功时而失败，要单独标记并分析；不要用“重跑直到通过”掩盖。

### 6.7 失败分类

每次失败必须归入一类，并附 trace：

| 类别 | 典型原因 | 例子 |
|---|---|---|
| F1 意图/指代 | 指代不清、同义词未映射 | “把方块放到盘子里” |
| F2 规划 | 选错技能、顺序错、不澄清 | 该 `clarify` 却直接抓 |
| F3 参数 | 物体名错、目标不存在 | `purple_cube` |
| F4 技能/IK | 不可达、逆解失败、碰撞 | 目标在背后 |
| F5 抓取/物理 | 未对准、滑落、attach 失败 | 夹爪没夹住 |
| F6 恢复 | 重复失败调用、过早放弃 | 连续两次同样的 `pick_and_place` |
| F7 API/循环 | 超时、畸形响应、max steps | 模型返回坏 JSON |
| F8 评测 | 容差过松/过紧、任务有歧义 | 成功判定误判 |

报告要给出每类的数量和占比，并保留 3–5 条典型 trace 供人工复盘。

### 6.8 CI / 回归门禁

**PR 快速套件（目标 < 2 分钟，不调用 API）**

- 单元测试；
- 少量技能契约测试（headless）；
- 工具参数校验；
- FakeLLM harness 测试；
- 对抗测试（歧义/不可行，用 FakeLLM）；
- 指标公式测试。

**Nightly（目标 < 30 分钟）**

- 20–50 条 E2E 任务 × 3 次；
- 真实 DeepSeek API；
- 对抗与恢复任务；
- 生成报告，和基线比较。

**Release**

- 全量任务 + held-out；
- 5 次重复；
- 门禁建议（初始值，后续校准）：
  - test 集成功率不低于基线 5 个百分点；
  - 无效动作率 ≤ 2%；
  - 安全违规 = 0；
  - 单任务成本不超过预算的 120%；
  - flaky 任务比例 ≤ 5%。

**基线**

- 保存 `reports/baseline.json`：模型、提示词版本、任务集版本、指标、CI。
- 每次 release 生成新报告；差异超过阈值就阻断。
- 记录 git commit（如果纳入版本控制）、Python/MuJoCo/mink/Menagerie 版本、DeepSeek 模型名。

### 6.9 测试替身与故障注入

- **FakeLLM**：按脚本返回 assistant 消息（含 tool_calls），用来测试 harness，不依赖 API。
- **RecordedLLM**：把真实 DeepSeek 响应录成 JSON，CI 回放；用于稳定回归和节省成本。
- **FaultInjector**：包装 `Skills`，让第 N 次 `grasp` 返回 `GRASP_FAILED`；测试恢复路径。
- **SlowSkills**：注入延迟，测试超时和 max steps。
- **Scene fixtures**：固定 `reset()` 后的物体布局；每个测试用独立 Sim 实例或 `reset()`。

**注意**：测试替身只替换边界；技能契约测试仍然用真实 MuJoCo，不用 mock 物理。

### 6.10 示例测试

**单元测试：工作空间边界**

```python
def test_out_of_workspace_rejected(skills):
    result = skills._validate_target([2.0, 0.0, 0.1])
    assert result.ok is False
    assert result.code == "OUT_OF_WORKSPACE"
```

**契约测试：未知物体**

```python
def test_grasp_unknown_object(skills):
    result = skills.grasp("purple_cube")
    assert result.ok is False
    assert result.code == "OBJECT_NOT_FOUND"
    assert skills.held is None
```

**契约测试：放置后置条件**

```python
def test_pick_and_place_reaches_target(sim, skills):
    sim.reset()
    result = skills.pick_and_place("red_cube", "blue_plate")
    assert result.ok is True
    assert distance_xy(sim.object_position("red_cube"),
                       sim.object_position("blue_plate")) < 0.04
    assert skills.held is None
```

**FakeLLM：harness 执行一次工具调用**

```python
class FakeLLM:
    def __init__(self, replies):
        self.replies = iter(replies)

    def chat(self, messages, tools=None):
        return next(self.replies), {"prompt_tokens": 1, "completion_tokens": 1}, 0.0
```

```python
def test_harness_executes_tool_call(fake_tools):
    llm = FakeLLM([
        {"role": "assistant", "content": "我来放置", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "pick_and_place",
                         "arguments": '{"source":"red_cube","target":"blue_plate"}'},
        }]},
        {"role": "assistant", "content": "完成", "tool_calls": []},
    ])
    result = Harness(llm=llm, tool_funcs=fake_tools).run("把红色方块放到蓝色盘子里")
    assert result.tool_calls[0]["name"] == "pick_and_place"
```

**E2E：成功任务**

```python
@pytest.mark.e2e
def test_nl_pick_place(agent, sim):
    result = agent.run("把红色方块放到蓝色盘子里")
    assert result.status == "success"
    assert distance_xy(sim.object_position("red_cube"),
                       sim.object_position("blue_plate")) < 0.04
```

**对抗：歧义任务**

```python
def test_ambiguous_request_clarifies(agent, sim):
    before = sim.snapshot()
    result = agent.run("把方块放到盘子里")
    assert result.status == "clarify"
    assert result.motion_calls == 0
    assert sim.snapshot() == before
```

**指标：Wilson CI**

```python
def test_wilson_ci():
    low, high = wilson_ci(18, 20)
    assert low < 0.9 < high
    assert 0.65 < low < 0.75
```

---

## 7. 可观测性

### 7.1 trace.jsonl

每次 episode 一个 ID；每一步一行 JSON：

```json
{"ts":"...","episode_id":"20261117-A01-0","task_id":"A01","run":0,"model":"deepseek-chat","prompt_version":"arm-v1","step":1,"event":"llm","thought":"我先查看场景。","tool_calls":[{"name":"list_objects","arguments":"{}"}],"usage":{"prompt_tokens":800,"completion_tokens":20},"latency_ms":900}
{"ts":"...","episode_id":"20261117-A01-0","step":1,"event":"tool","name":"list_objects","args":{},"result":{"ok":true,"code":"OK"},"sim_state":{"objects":{"red_cube":[0.45,-0.15,0.025]}},"latency_ms":1}
{"ts":"...","episode_id":"20261117-A01-0","step":2,"event":"tool","name":"pick_and_place","args":{"source":"red_cube","target":"blue_plate"},"result":{"ok":true,"code":"OK"},"latency_ms":1200}
{"ts":"...","episode_id":"20261117-A01-0","event":"episode_end","status":"success","steps":3,"tokens":{"prompt":1200,"completion":80},"cost_usd":0.0003}
```

要求：

- 不记录 API key、完整系统提示词中的敏感信息；
- 工具参数和结果要可复现；
- 失败记录错误码、步骤、堆栈摘要（仅本地）；
- 记录模型名、提示词版本、技能版本、种子。

### 7.2 Episode summary

每条任务单独输出：

```json
{
  "episode_id": "...",
  "task_id": "A01",
  "category": "single_step",
  "status": "success",
  "steps": 3,
  "tool_calls": 2,
  "invalid_actions": 0,
  "tokens": {"prompt": 1200, "completion": 80},
  "cost_usd": 0.0003,
  "latency_ms": 3200,
  "failure_category": null
}
```

### 7.3 报告

- 按类别汇总成功率、CI、平均步数、无效动作率、成本；
- 列出失败任务和典型 trace；
- 与基线对比：成功率差值、成本差值、flaky 任务；
- 报告是 release 的附件，不靠聊天记录。

---

## 8. 安全与护栏

即使是仿真，也要按“真实机器人”的习惯设计：

- **工作空间**：x/y/z 边界检查；越界直接拒绝，不尝试。
- **关节限制**：从 URDF 读取；不要硬编码。
- **速度/力**：位置控制时限制最大关节速度和力；不要瞬间跳到目标。
- **碰撞**：v1 至少检查机器人-物体、物体-物体的非预期接触；允许夹爪与目标物体接触。
- **工具面**：不暴露 `set_object_position`、`teleport`、直接关节控制；只有技能。
- **终止**：max steps、max tool calls、超时、重复失败调用拦截。
- **teardown**：结束后回安全位；如果还夹着物体，先释放或明确保持。
- **作弊检测**：评测检查物体是否在没有抓取的情况下移动；工具层不应提供这种能力。
- **密钥**：API key 只从环境变量读；不写进代码、trace、报告。
- **提示注入**：v1 物体名是固定枚举；如果未来允许用户命名物体，不要把用户文本直接拼进系统提示词。

> 本项目只在仿真中运行，不代表真实机械臂的安全设计。真机还需要急停、看门狗、力矩限制、认证工作空间和风险评估。

---

## 9. 项目结构

实施采用 uv 的 `src/` 布局；模块按职责分在 `src/core`、`src/utils`、`src/eval`、`src/arm_agent_demo`，测试在 `tests/`。

```text
arm-agent-demo/
├── DESIGN.md                 # 本文档
├── README.md                 # 运行方式与实现顺序
├── pyproject.toml            # uv 项目、依赖、脚本入口、pytest 配置
├── .env.example              # DEEPSEEK_API_KEY / LLM_MODEL / ...
├── src/
│   ├── arm_agent_demo/
│   │   ├── __init__.py
│   │   ├── main.py           # CLI：scripted / 自然语言 / 交互
│   │   ├── sim.py            # MuJoCo 世界、物体、reset、状态真值
│   │   └── skills.py         # 重构前副本，可删
│   ├── core/
│   │   ├── harness.py        # ReAct 循环 + 终态工具
│   │   ├── llm.py            # DeepSeek 客户端
│   │   └── memory.py         # 会话存储
│   ├── utils/
│   │   ├── tools.py          # LLM 可见工具 + schema + 校验
│   │   └── skills.py         # 确定性技能契约（active）
│   └── eval/
│       ├── eval_tasks.py     # 任务集与数据划分
│       ├── eval_runner.py    # 运行 episode、记录 trace
│       └── eval_metrics.py   # 成功率、CI、pass@k、失败分类
├── assets/franka_emika_panda/     # Menagerie Panda + scene_pick_place.xml
├── tests/
│   └── test_harness_fake_llm.py  # 已提供：不调用 API 的 harness 测试
├── traces/
└── reports/
```

> 当前骨架已提供 `tests/test_harness_fake_llm.py`；技能契约、工具校验、对抗和 E2E 测试按第 6 章逐步补。

---

## 10. 里程碑

| 阶段 | 交付 | 验收 |
|---|---|---|
| M0 环境 | Python 3.11 venv、MuJoCo、Menagerie Panda、GUI | GUI 能看到 Panda + 3 方块 + 2 盘 |
| M1 技能 | `home/move_to/grasp/release/pick_and_place` | 硬编码脚本完成一次 pick-place；契约测试通过 |
| M2 工具 + Agent | `tools.py`、FakeLLM harness 测试 | 不调用 API 也能测完整循环 |
| M3 DeepSeek E2E | 真实模型、trace | 一条中文指令端到端成功 |
| M4 评测 MVP | 20 条任务、指标、报告、快速 CI | 成功率、CI、无效动作率、失败分类 |
| M5 严苛评测 | 50–100 条、dev/test/held-out、对抗/恢复、基线 | release 门禁可执行 |
| M6 加固 | 重试、成本、超时、文档、回归 | 换模型/提示词能自动比较 |

---

## 11. 风险与开放问题

| 风险/问题 | 影响 | 对策 |
|---|---|---|
| MuJoCo/mink 版本与模型资产 | 环境/加载卡住 | 固定 mujoco/mink/menagerie 版本；模型 vendored 到 `assets/` |
| 运动学吸附/简化抓取不等于真实抓取 | 成功率被高估 | 报告明确标注；v2 换真实夹爪 |
| mink IK 不收敛/姿态不对 | 任务失败 | 设置 q 后调用 `config.update(q)`；默认保持 hand 姿态；工作空间限制 |
| MuJoCo viewer 在 Wayland 下异常 | 调试不便 | 用 Xwayland 或 headless；评测不依赖渲染 |
| DeepSeek tool calling 稳定性 | 调用失败 | 先用 `deepseek-chat` 冒烟；保留严格 JSON 降级 |
| LLM 非确定性 | 评测不可复现 | temperature 0 + 多次重复 + CI + 记录方差 |
| 任务集过拟合 | 指标虚高 | dev/test/held-out；改写任务；held-out 只在 release 用 |
| 歧义/不可行判定脆弱 | 误判 | 用终态工具，不用关键词匹配 |
| E2E 成本/时间 | CI 变慢 | 快速套件用 FakeLLM/RecordedLLM；E2E 只跑 nightly |
| 坐标暴露导致幻觉 | 乱传坐标 | v1 不暴露坐标；技能解析物体名 |
| 安全性被误解 | 以为可上真机 | 文档明确“仅仿真”；真机需额外安全设计 |

**已确认（2026-11-17）**

- v1 仿真器：**MuJoCo 4.0.1 + mink 1.4.0 + Menagerie Panda**；Python 3.11；ADR-011 取代 ADR-009。
- 机器人控制层：**v1 先用 Python 跑通**；C++ 作为第二阶段，从 `skills.py` 抽出，经 pybind11 暴露（ADR-010）。

**需要你确认的开放问题**

1. 模型用 `deepseek-chat` 还是你当前的 `deepseek-flash`？后者是否支持 function calling？
2. v1 是否只做 `pick_and_place`，还是同时暴露 `pick` / `place`？
3. 目标盘是命名物体，还是需要支持“左边/右边”这类空间指代？
4. 评测预算：nightly 能接受多少次 API 调用？20 条 × 3 次是起点。
5. v2 是否要加相机/VLM？如果是，先定感知输出 schema，避免直接把图像塞给 LLM。
6. C++ 控制库第一批抽取什么：只抽 IK/运动原语，还是连技能状态机一起抽？

---

## 附录 A：LLM 可见工具 Schema（v1）

```json
[
  {
    "type": "function",
    "function": {
      "name": "list_objects",
      "description": "列出当前场景中可操作的物体。",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_state",
      "description": "查看夹爪是否闭合、当前拿着什么、上一步结果。",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "pick_and_place",
      "description": "抓起 source 物体并放到 target 目标上。",
      "parameters": {
        "type": "object",
        "properties": {
          "source": {"type": "string", "description": "要抓取的物体规范名，例如 red_cube"},
          "target": {"type": "string", "description": "目标规范名，例如 blue_plate"}
        },
        "required": ["source", "target"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "home",
      "description": "机械臂回到安全初始位，夹爪打开。",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "request_clarification",
      "description": "指令有歧义时使用；提出问题并结束本轮，不执行任何动作。",
      "parameters": {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "report_infeasible",
      "description": "任务无法完成时使用；说明原因并结束本轮，不执行任何动作。",
      "parameters": {
        "type": "object",
        "properties": {"reason": {"type": "string"}},
        "required": ["reason"]
      }
    }
  }
]
```

---

## 附录 B：任务样例

| ID | 指令 | 类别 | 期望 |
|---|---|---|---|
| A01 | 把红色方块放到蓝色盘子里 | 单步 | success；红块在蓝盘 4cm 内 |
| A02 | 把绿色方块放到红色盘子里 | 单步 | success |
| A03 | 把蓝色方块放到蓝色盘子里 | 单步 | success |
| B01 | 先把红块放到蓝盘，再把绿块放到红盘 | 多步 | success；两个物体都在目标附近 |
| B02 | 把三个方块都放到蓝色盘子里 | 多步 | success；三个都在蓝盘附近 |
| C01 | 你现在拿着什么？ | 查询 | success；无动作，回答“没有/red_cube” |
| C02 | 场景里有哪些物体？ | 查询 | success；无动作，列出目录 |
| D01 | 把方块放到盘子里 | 歧义 | clarify；无动作 |
| D02 | 把红色的那个放过去 | 歧义 | clarify 或按上下文消解（需定义规则） |
| E01 | 把紫色方块放到蓝色盘子里 | 不可行 | infeasible；无动作 |
| E02 | 把红色方块放到机器人背后 | 不可行 | infeasible；无动作 |
| F01 | 把红色方块放到蓝色盘子里（注入一次 grasp 失败） | 恢复 | success 或 infeasible；不能崩溃 |
| G01 | 红方块移到蓝盘子 | 改写 | success |
| G02 | 请把红色的积木放进蓝色托盘 | 改写 | success 或 clarify（取决于标签映射） |

---

## 附录 C：指标公式

**Wilson 95% 置信区间**

```text
p = k/n
z = 1.96
denom = 1 + z²/n
center = (p + z²/(2n)) / denom
half = z * sqrt(p(1-p)/n + z²/(4n²)) / denom
CI = [center-half, center+half]
```

**pass@k（无偏估计）**

```text
pass@k = 1 - C(n-c, k) / C(n, k)
```

其中 `n` 是每任务运行次数，`c` 是成功次数，`k` 是允许的尝试次数。

**McNemar（配对二分类比较）**

换模型/提示词时，同一任务在 A/B 两版下的成功/失败构成 2×2 表：

```text
             B 成功   B 失败
A 成功         a        b
A 失败         c        d
```

关注 `b`（A 成功、B 失败）和 `c`（A 失败、B 成功）；用 McNemar 检验判断差异是否显著。不要只看总成功率的差值。

---

## 12. 参考实现顺序（给手敲用）

1. `src/arm_agent_demo/sim.py`：GUI 打开，Panda + 平面 + 3 方块 + 2 盘；`list_objects` / `get_state` 用真值。
2. `src/utils/skills.py`：`home` → `move_to_pose` → `grasp` → `release` → `pick_and_place`。
3. `tests/test_skill_contracts.py`：先把每个技能的失败码测出来。
4. `src/utils/tools.py`：schema + `bind(skills)` + `dispatch`；先只暴露 `pick_and_place`。
5. `tests/test_harness_fake_llm.py`：不调用 API 跑通循环。
6. `src/arm_agent_demo/main.py --scripted`：硬编码一次 pick-place。
7. `src/arm_agent_demo/main.py "把红色方块放到蓝色盘子里"`：接 DeepSeek。
8. `src/eval/eval_tasks.py` + `src/eval/eval_runner.py`：20 条任务。
9. `src/eval/eval_metrics.py`：成功率、CI、无效动作率、失败分类。
10. 对抗/恢复任务；CI 分层；基线。

每一步都先写测试，再写实现；不要在 E2E 里调试确定性 bug。
