"""ReAct 主循环：thought → tool call → observation → final。

在 agent-demo 的基础上增加：
- 机械臂专用系统提示词
- 终态工具（澄清 / 不可行）
- 工具返回 dict 时自动序列化，并记录 ok/code
- 可注入 tool_funcs/tool_schemas，方便 FakeLLM 测试
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from utils.tools import TOOL_FUNCS, TOOL_SCHEMAS

from .llm import LLM

SYSTEM_PROMPT = """你是一个桌面机械臂的任务规划器。你只能通过工具操作机械臂，不能直接控制关节。

规则：
1. 只操作 list_objects 返回的物体；不要编造物体名。
2. 动作前先确认状态；不确定就调用 get_state。
3. 一次只调用一个动作工具。
4. 工具失败时读 code 和 hint：可重试错误最多重试一次；不可重试错误要澄清或报告不可行。
5. 指令有歧义时调用 request_clarification，不要猜。
6. 无法完成时调用 report_infeasible，不要假装成功。
7. 完成后用一句中文说明结果。
"""

TERMINAL_TOOLS = {"request_clarification": "clarify", "report_infeasible": "infeasible"}


@dataclass
class RunResult:
    answer: str
    status: str = "final"
    steps: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


class Harness:
    def __init__(
        self,
        llm=None,
        memory=None,
        session_id="default",
        max_steps=8,
        trace_path="trace.jsonl",
        tool_funcs=None,
        tool_schemas=None,
    ):
        self.llm = llm or LLM()
        self.memory = memory
        self.session_id = session_id
        self.max_steps = max_steps
        self.trace_path = trace_path
        self.tool_funcs = tool_funcs if tool_funcs is not None else TOOL_FUNCS
        self.tool_schemas = tool_schemas if tool_schemas is not None else TOOL_SCHEMAS

    def run(self, user_input: str, on_event=None) -> RunResult:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.memory:
            messages.extend(self.memory.load(self.session_id))
        messages.append({"role": "user", "content": user_input})

        result = RunResult(answer="")
        started = time.perf_counter()
        terminal_status = None

        for step in range(1, self.max_steps + 1):
            message, usage, latency = self.llm.chat(messages, self.tool_schemas)
            result.steps = step
            result.prompt_tokens += usage.get("prompt_tokens", 0)
            result.completion_tokens += usage.get("completion_tokens", 0)

            thought = (message.get("content") or "").strip()
            calls = message.get("tool_calls") or []
            self._trace(
                "llm",
                step,
                {
                    "message_count": len(messages),
                    "thought": thought,
                    "tool_calls": [call.get("function", {}) for call in calls],
                },
                latency,
                usage,
            )

            if on_event and thought:
                on_event(("thought", thought))

            assistant = {"role": "assistant", "content": thought}
            if calls:
                assistant["tool_calls"] = calls
            messages.append(assistant)

            if not calls:
                result.answer = thought or "（模型未返回内容）"
                break

            stop_after_tools = False
            for call in calls:
                function = call.get("function") or {}
                name = function.get("name", "")
                raw_args = function.get("arguments") or "{}"
                tool_started = time.perf_counter()
                args = {}
                raw = None

                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        raise ValueError("参数必须是 JSON 对象")
                    if name not in self.tool_funcs:
                        raise ValueError(f"未知工具：{name}")

                    raw = self.tool_funcs[name](**args)
                    if isinstance(raw, dict):
                        observation = json.dumps(raw, ensure_ascii=False)
                        ok = bool(raw.get("ok", True))
                        code = str(raw.get("code", "OK"))
                    else:
                        observation = str(raw)
                        ok = True
                        code = "OK"
                except json.JSONDecodeError as exc:
                    ok, code = False, "INVALID_ARGUMENT"
                    observation = json.dumps(
                        {
                            "ok": False,
                            "code": code,
                            "message": f"参数不是合法 JSON：{exc}",
                        },
                        ensure_ascii=False,
                    )
                except (ValueError, TypeError) as exc:
                    ok, code = False, "INVALID_ARGUMENT"
                    observation = json.dumps(
                        {"ok": False, "code": code, "message": str(exc)},
                        ensure_ascii=False,
                    )
                except Exception as exc:
                    ok, code = False, "INTERNAL_ERROR"
                    observation = json.dumps(
                        {"ok": False, "code": code, "message": f"工具执行失败：{exc}"},
                        ensure_ascii=False,
                    )

                tool_latency = (time.perf_counter() - tool_started) * 1000
                result.tool_calls.append(
                    {"name": name, "args": raw_args, "ok": ok, "code": code}
                )
                self._trace(
                    "tool",
                    step,
                    {
                        "name": name,
                        "args": raw_args,
                        "ok": ok,
                        "code": code,
                        "observation": observation,
                    },
                    tool_latency,
                )

                if on_event:
                    on_event(("tool", name, raw_args, observation))

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": observation,
                    }
                )

                if ok and name in TERMINAL_TOOLS:
                    terminal_status = TERMINAL_TOOLS[name]
                    result.answer = str(
                        args.get("question")
                        or args.get("reason")
                        or (raw.get("message") if isinstance(raw, dict) else "")
                        or observation
                    )
                    stop_after_tools = True
                    break

            if stop_after_tools:
                result.status = terminal_status or "final"
                break
        else:
            # 达到步数上限：禁用工具，要求模型收尾
            message, usage, latency = self.llm.chat(
                messages
                + [
                    {
                        "role": "user",
                        "content": "已达到最大步数，请停止调用工具，直接给出最终答案。",
                    }
                ],
                None,
            )
            result.prompt_tokens += usage.get("prompt_tokens", 0)
            result.completion_tokens += usage.get("completion_tokens", 0)
            answer = (message.get("content") or "").strip()
            result.answer = answer or "（模型未返回内容）"
            result.status = "max_steps"
            messages.append({"role": "assistant", "content": answer})
            self._trace(
                "llm",
                self.max_steps + 1,
                {"thought": answer, "tool_calls": [], "forced_final": True},
                latency,
                usage,
            )

        result.latency_ms = (time.perf_counter() - started) * 1000
        if self.memory:
            self.memory.save(self.session_id, messages[1:])
        self._trace(
            "final",
            result.steps,
            {
                "input": user_input,
                "answer": result.answer,
                "status": result.status,
                "tool_call_count": len(result.tool_calls),
            },
            result.latency_ms,
        )
        if on_event:
            on_event(("final", result.answer))
        return result

    def _trace(
        self, event: str, step: int, payload: dict, latency_ms: float, usage=None
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": self.session_id,
            "step": step,
            "event": event,
            "latency_ms": latency_ms,
            "usage": usage or {},
            **payload,
        }
        with open(self.trace_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
