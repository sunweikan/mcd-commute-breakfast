"""命令行入口。

演示模式（无需 Token）：
    python -m mcb.cli --demo

真实模式：
    set MCD_MCP_TOKEN=你的Token   (Windows)
    export MCD_MCP_TOKEN=你的Token (macOS/Linux)
    python -m mcb.cli --home "北京市朝阳区xx小区" --company "北京市海淀区xx大厦"
"""

from __future__ import annotations

import argparse
import os
import sys

from .card import render_card
from .service import build_plan_demo, build_plan_live, render_markdown


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcd-commute-breakfast",
        description="麦麦顺路早餐管家：通勤路上的麦当劳早餐规划师",
    )
    parser.add_argument("--home", help="住处地址（真实模式必填）")
    parser.add_argument("--company", help="公司地址（真实模式必填）")
    parser.add_argument("--budget", type=float, default=15.0, help="早餐预算（元），默认 15")
    parser.add_argument("--kcal-min", type=float, default=300.0, help="热量下限，默认 300 kcal")
    parser.add_argument("--kcal-max", type=float, default=650.0, help="热量上限，默认 650 kcal")
    parser.add_argument("--top", type=int, default=3, help="推荐几套搭配，默认 3")
    parser.add_argument("--demo", action="store_true", help="演示模式：使用内置样本数据，无需 Token")
    parser.add_argument("--token", help="麦当劳 MCP Token（也可用环境变量 MCD_MCP_TOKEN）")
    parser.add_argument("--card", default="breakfast_card.html", help="早餐卡输出路径")
    parser.add_argument("--md", default="breakfast_plan.md", help="Markdown 报告输出路径")
    args = parser.parse_args(argv)

    if args.demo:
        plan = build_plan_demo(args.budget, args.kcal_min, args.kcal_max, args.top)
    else:
        token = args.token or os.environ.get("MCD_MCP_TOKEN", "")
        if not token:
            print("❌ 缺少 MCP Token。请设置环境变量 MCD_MCP_TOKEN，"
                  "或使用 --token 参数；也可以先用 --demo 体验。", file=sys.stderr)
            return 2
        if not args.home or not args.company:
            print("❌ 真实模式需要 --home 和 --company 两个地址参数。", file=sys.stderr)
            return 2
        plan = build_plan_live(
            token, args.home, args.company,
            args.budget, args.kcal_min, args.kcal_max, args.top,
        )

    render_card(plan, args.card)
    report = render_markdown(plan)
    with open(args.md, "w", encoding="utf-8") as fh:
        fh.write(report)

    print(report)
    print()
    print(f"✅ 早餐卡已生成：{args.card}")
    print(f"✅ 报告已生成：{args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
