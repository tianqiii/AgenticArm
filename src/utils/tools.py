"""LLM 可见的工具层：schema + 参数绑定 + 结果序列化。

工具面刻意保持窄：只暴露高层技能、状态查询和终态工具；
不暴露坐标、关节角、直接设置物体位置等底层能力。
"""

from dataclasses import asdict

from .skills import Skills

_skills: Skills | None = None


def bind(skills: Skills) -> None:
    """main.py / eval_runner.py 创建 Skills 后调用一次。"""
    global _skills
    _skills = skills


def _require_skills() -> Skills:
    if _skills is None:
        raise RuntimeError("tools 未绑定：先调用 tools.bind(skills)")
    return _skills


def _call(method: str, *args, **kwargs) -> dict:
    result = getattr(_require_skills(), method)(*args, **kwargs)
    return asdict(result)


def list_objects() -> dict:
    return _call("list_objects")


def get_state() -> dict:
    return _call("get_state")


def pick_and_place(source: str, target: str) -> dict:
    return _call("pick_and_place", source, target)


def home() -> dict:
    return _call("home")


def request_clarification(question: str) -> dict:
    # 终态工具：harness 看到 CLARIFY 后停止本轮，不执行动作
    return {"ok": True, "code": "CLARIFY", "message": question}


def report_infeasible(reason: str) -> dict:
    # 终态工具：harness 看到 INFEASIBLE 后停止本轮，不执行动作
    return {"ok": True, "code": "INFEASIBLE", "message": reason}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_objects",
            "description": "列出当前场景中可操作的物体。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_state",
            "description": "查看夹爪是否闭合、当前拿着什么、上一步结果。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pick_and_place",
            "description": "抓起 source 物体并放到 target 目标上。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "要抓取的物体规范名，例如 red_cube",
                    },
                    "target": {
                        "type": "string",
                        "description": "目标规范名，例如 blue_plate",
                    },
                },
                "required": ["source", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "home",
            "description": "机械臂回到安全初始位，夹爪打开。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_clarification",
            "description": "指令有歧义时使用；提出问题并结束本轮，不执行任何动作。",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_infeasible",
            "description": "任务无法完成时使用；说明原因并结束本轮，不执行任何动作。",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]

TOOL_FUNCS = {
    "list_objects": list_objects,
    "get_state": get_state,
    "pick_and_place": pick_and_place,
    "home": home,
    "request_clarification": request_clarification,
    "report_infeasible": report_infeasible,
}
