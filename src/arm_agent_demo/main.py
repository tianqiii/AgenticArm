"""CLI：脚本模式 / 自然语言单轮 / 交互模式。"""

import argparse
import json
from dataclasses import asdict

try:
    import readline  # 导入即启用 input() 的行编辑（退格、Ctrl-A/E 等）
except ImportError:  # 非 POSIX 平台没有 readline
    pass
else:
    # 部分终端把 Backspace 发成 Ctrl-H (0x08)，而 libedit 后端默认只绑定
    # DEL (0x7F)，表现为退格键清不掉字符。这里补一条 libedit 绑定。
    if "EditLine" in getattr(readline, "_READLINE_LIBRARY_VERSION", ""):
        readline.parse_and_bind("bind ^H ed-delete-prev-char")

from arm_agent_demo.sim import Sim
from core.harness import Harness
from core.llm import LLM
from core.memory import Memory
from utils import tools
from utils.skills import Skills


def show(event: tuple) -> None:
    kind = event[0]
    if kind == "thought":
        print(f"\n[思考] {event[1]}")
    elif kind == "tool":
        print(f"[工具] {event[1]}({event[2]})")
        print(f"[观察] {event[3]}")
    elif kind == "final":
        print(f"\n[回答] {event[1]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="自然语言机械臂 Agent（MuJoCo）")
    parser.add_argument("question", nargs="?", help="单轮指令；省略则进入交互模式")
    parser.add_argument(
        "--scripted", action="store_true", help="不接 LLM，跑一条硬编码 pick-and-place"
    )
    parser.add_argument("--no-gui", action="store_true", help="无窗口 headless 模式")
    parser.add_argument("-s", "--session", default="arm", help="会话 ID")
    parser.add_argument("--max-steps", type=int, default=8, help="最大 LLM 轮数")
    args = parser.parse_args()

    sim = Sim(gui=not args.no_gui)
    skills = Skills(sim)
    tools.bind(skills)

    try:
        if args.scripted:
            result = skills.pick_and_place("red_cube", "blue_plate")
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return

        agent = Harness(
            llm=LLM(),
            memory=Memory(),
            session_id=args.session,
            max_steps=args.max_steps,
        )

        if args.question:
            result = agent.run(args.question, on_event=show)
            print(
                f"\n[统计] status={result.status} steps={result.steps} "
                f"tools={len(result.tool_calls)} "
                f"tokens={result.prompt_tokens}+{result.completion_tokens} "
                f"{result.latency_ms / 1000:.1f}s"
            )
            return

        print(f"交互模式（会话：{args.session}）。输入指令，exit 退出。")
        while True:
            try:
                question = input("\n指令> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question or question in {"exit", "quit"}:
                break
            agent.run(question, on_event=show)
    finally:
        sim.close()


if __name__ == "__main__":
    main()
