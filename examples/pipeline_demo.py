"""Run the whole pipeline: formulator → observer → generator → evaluator:

    python examples/pipeline_demo.py                 # run REQUEST below
    python examples/pipeline_demo.py "你的请求"       # run your own request

The observer gathers data from the sources below (the sagax source needs SAGAX_API_KEY / SAGAX_SECRET_KEY in .env).
The evaluator is the Krino Matrix model at MATRIX_CHECKPOINT once it has been trained: it reads the whole action space
and the constraints in one pass, excludes the actions that likely break a hard constraint and ranks the rest. Without
the checkpoint a placeholder scores every action the same, so the actions keep the generator's order.
"""
import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.schema import State, Action
from core.formulator.api_formulator import APIFormulator
from core.observer.api_observer import APIObserver
from core.data.sagax import SagaxSource
from core.generator.api_generator import APIGenerator
from core.evaluator.evaluator import Evaluator
from core.evaluator.matrix_evaluator import MatrixEvaluator
from core.pipeline import Pipeline
from services.llm import LLM

# Edit these to try your own scenario
MODEL = None            # None: LLM_DEFAULT in .env; or e.g. "anthropic/claude-opus-5.5"
NUM_ACTIONS = None      # None: 3 to 5 actions
MATRIX_CHECKPOINT = Path(__file__).resolve().parents[1] / "experiments/krino-matrix-v1/checkpoints/multilingual-uncertainty"
REQUEST = (
    "我手上有 20 万闲钱想投 A 股，目前已经持有大概 5 万的沪深300ETF，没开科创板权限。"
    "这笔钱 3 年内用不到，风险承受能力中等。想买 2 到 3 只股票，争取年化 8% 以上。"
    "单只股票别超过 30% 仓位，不碰 ST 和次新股，回撤最好别超过 20%，也不想加杠杆。"
    "你觉得我该买什么股票？"
)


class PlaceholderEvaluator(Evaluator):
    """Stands in for a real evaluator: scores every action the same."""

    def evaluate(
        self,
        state: State,
        goal: str,
        action: Action
    ) -> float:
        return 0.0


if __name__ == "__main__":
    request = " ".join(sys.argv[1:]) or REQUEST
    llm = LLM(MODEL)
    sources = [SagaxSource()]       # add more data sources here
    trained = (MATRIX_CHECKPOINT / "matrix_config.json").exists()
    evaluator = MatrixEvaluator(str(MATRIX_CHECKPOINT)) if trained else PlaceholderEvaluator()
    pipeline = Pipeline(
        APIFormulator(llm),
        APIGenerator(llm, num_actions=NUM_ACTIONS),
        evaluator,
        observer=APIObserver(sources, llm),
    )
    print(f"Model: {llm.model} (via {llm.provider.name})")
    print(f"Evaluator: {MATRIX_CHECKPOINT if trained else 'placeholder, no trained checkpoint'}\n")
    print(f"Request:\n{request}\n")

    result = pipeline.run(request)
    problem = result.problem
    facts = {k: v for k, v in problem.state.data.items() if k != "observations"}
    print("State:")
    print(json.dumps(facts, ensure_ascii=False, indent=2))
    print(f"\nGoal:\n{problem.goal}\n")
    print("Constraints:")
    for c in problem.constraints:
        print(f"- [{c.id}] {c.text}" + ("" if c.hard else " (preference)"))
    if not problem.constraints:
        print("(none)")

    print("\nObservations:")
    for observation in problem.state.data.get("observations", []):
        print(f"- {observation['query']} {json.dumps(observation['params'], ensure_ascii=False)}")

    print("\nDecisions (best first):")
    for i, decision in enumerate(result.decisions, 1):
        excluded = f"  excluded: breaks {', '.join(decision.excluded_by)}" if decision.excluded_by else ""
        print(f"{i}. [{decision.score:.2f}] {decision.action.id}{excluded}\n   {decision.action.description}\n")
    print(f"Chosen: {result.decision.action.id if result.decision else 'none, every action breaks a hard constraint'}")
