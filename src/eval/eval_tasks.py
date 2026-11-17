"""评测任务集：先 8 条；按 DESIGN.md 第 6 章扩到 20/50。

字段：
- terminal: success / clarify / infeasible
- placements: [[source, target], ...]；非 success 为空
- tol: 水平距离容差（米）
- inject: 可选的故障注入，给恢复测试用
"""

TASKS = [
    {
        "id": "A01",
        "category": "single_step",
        "instruction": "把红色方块放到蓝色盘子里",
        "expect": {
            "terminal": "success",
            "placements": [["red_cube", "blue_plate"]],
            "tol": 0.04,
        },
    },
    {
        "id": "A02",
        "category": "single_step",
        "instruction": "把绿色方块放到红色盘子里",
        "expect": {
            "terminal": "success",
            "placements": [["green_cube", "red_plate"]],
            "tol": 0.04,
        },
    },
    {
        "id": "A03",
        "category": "single_step",
        "instruction": "把蓝色方块放到红色盘子里",
        "expect": {
            "terminal": "success",
            "placements": [["blue_cube", "red_plate"]],
            "tol": 0.04,
        },
    },
    {
        "id": "B01",
        "category": "multi_step",
        "instruction": "先把红色方块放到蓝色盘子里，再把绿色方块放到红色盘子里",
        "expect": {
            "terminal": "success",
            "placements": [
                ["red_cube", "blue_plate"],
                ["green_cube", "red_plate"],
            ],
            "tol": 0.04,
        },
    },
    {
        "id": "C01",
        "category": "query",
        "instruction": "场景里有哪些物体？",
        "expect": {"terminal": "success", "placements": [], "tol": 0.04},
    },
    {
        "id": "D01",
        "category": "ambiguous",
        "instruction": "把方块放到盘子里",
        "expect": {"terminal": "clarify", "placements": [], "tol": 0.04},
    },
    {
        "id": "E01",
        "category": "infeasible",
        "instruction": "把紫色方块放到蓝色盘子里",
        "expect": {"terminal": "infeasible", "placements": [], "tol": 0.04},
    },
    {
        "id": "F01",
        "category": "recovery",
        "instruction": "把红色方块放到蓝色盘子里",
        "expect": {
            "terminal": "success",
            "placements": [["red_cube", "blue_plate"]],
            "tol": 0.04,
        },
        "inject": {"skill": "grasp", "times": 1},
    },
    # TODO: 扩到 20/50 条，覆盖更多颜色/目标组合、改写、多步、歧义、不可行和恢复
]
