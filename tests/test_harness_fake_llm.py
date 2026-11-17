"""不调用 API 的 harness 测试：验证工具调用、终态工具和坏参数。"""

import json

from core.harness import Harness


class FakeLLM:
    def __init__(self, replies):
        self.replies = iter(replies)

    def chat(self, messages, tools=None):
        return next(self.replies), {"prompt_tokens": 1, "completion_tokens": 1}, 0.0


def tool_call(name, args, call_id="c1"):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def final(content):
    return {"role": "assistant", "content": content, "tool_calls": []}


def test_tool_then_final(tmp_path):
    seen = []

    def fake_pick(source, target):
        seen.append((source, target))
        return {"ok": True, "code": "OK", "message": "done"}

    harness = Harness(
        llm=FakeLLM([
            tool_call("pick_and_place", {"source": "red_cube", "target": "blue_plate"}),
            final("完成"),
        ]),
        tool_funcs={"pick_and_place": fake_pick},
        tool_schemas=[],
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    result = harness.run("把红色方块放到蓝色盘子里")

    assert result.status == "final"
    assert result.tool_calls[0]["name"] == "pick_and_place"
    assert result.tool_calls[0]["ok"] is True
    assert seen == [("red_cube", "blue_plate")]
    assert result.answer == "完成"


def test_terminal_clarify(tmp_path):
    def clarify(question):
        return {"ok": True, "code": "CLARIFY", "message": question}

    harness = Harness(
        llm=FakeLLM([
            tool_call("request_clarification", {"question": "你想移动哪个方块？"}),
        ]),
        tool_funcs={"request_clarification": clarify},
        tool_schemas=[],
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    result = harness.run("把方块放到盘子里")

    assert result.status == "clarify"
    assert result.answer == "你想移动哪个方块？"


def test_bad_json_args_does_not_crash(tmp_path):
    def fake_pick(**kwargs):
        return {"ok": True, "code": "OK"}

    harness = Harness(
        llm=FakeLLM([
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "pick_and_place",
                            "arguments": "not json",
                        },
                    }
                ],
            },
            final("失败"),
        ]),
        tool_funcs={"pick_and_place": fake_pick},
        tool_schemas=[],
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    result = harness.run("x")

    assert result.tool_calls[0]["ok"] is False
    assert result.tool_calls[0]["code"] == "INVALID_ARGUMENT"
