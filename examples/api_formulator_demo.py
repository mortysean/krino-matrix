"""Try the API formulator:

    python examples/api_formulator_demo.py                 # formulate REQUEST below
    python examples/api_formulator_demo.py "你的请求"       # formulate your own request
"""
import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.formulator.api_formulator import APIFormulator
from services.llm import LLM

# Edit these to try your own scenario
MODEL = None            # None: LLM_DEFAULT in .env; or e.g. "anthropic/claude-opus-5.5"
REQUEST = (
    "我手上有 20 万闲钱想投 A 股，目前已经持有大概 5 万的沪深300ETF，没开科创板权限。"
    "这笔钱 3 年内用不到，风险承受能力中等。想买 2 到 3 只股票，争取年化 8% 以上。"
    "单只股票别超过 30% 仓位，不碰 ST 和次新股，回撤最好别超过 20%，也不想加杠杆。"
    "你觉得我该买什么股票？"
)


if __name__ == "__main__":
    request = " ".join(sys.argv[1:]) or REQUEST
    llm = LLM(MODEL)
    print(f"Model: {llm.model} (via {llm.provider.name})\n")
    print(f"Request:\n{request}\n")

    problem = APIFormulator(llm).formulate(request)
    print("State:")
    print(json.dumps(problem.state.data, ensure_ascii=False, indent=2))
    print(f"\nGoal:\n{problem.goal}\n")
    print("Constraints:")
    for c in problem.constraints:
        print(f"- [{c.id}] {c.text}" + ("" if c.hard else " (preference)"))
    if not problem.constraints:
        print("(none)")
