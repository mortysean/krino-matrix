import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["KRINO_SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(ROOT / "data" / "test-krino.db"))

from krino.common.schema import Constraint, Problem, State  # noqa: E402
from krino.steps.formulator import Formulator  # noqa: E402
from krino.steps.clarifier import Clarifier  # noqa: E402
from krino.steps.generator import CandidateAction, CandidateSpace, CardGenerator  # noqa: E402
from krino.engine import DecisionEngine  # noqa: E402
from krino.evaluator.base import Evaluator, Evaluation  # noqa: E402
from krino.contract import EvaluatorInfo, Question  # noqa: E402


class FakeFormulator(Formulator):
    def formulate(self, request):
        return Problem(state=State(data={"savings_cny": 50000}), goal="三个月内换到数据分析岗位",
                       constraints=[Constraint(id="no_quit_now", text="不能马上辞职", hard=True)])


class FakeClarifier(Clarifier):
    """Asks one question until it is answered or skipped."""

    def __init__(self):
        pass

    def clarify(self, request, problem, answers, style=None):
        if answers:
            return None
        return Question(id="sql_level", text="你现在的 SQL 水平？", kind="single", options=["入门", "熟练"])


class FakeGenerator(CardGenerator):
    def __init__(self, actions=None):
        self.actions = actions

    def generate(self, state, goal, constraints, style=None):
        actions = self.actions if self.actions is not None else [
            CandidateAction(id="build_portfolio", title="先做两个数据分析作品", description="用公开数据做两个项目。",
                            why="作品最能证明能力。"),
            CandidateAction(id="apply_internal", title="申请内部转岗", description="和主管沟通内部转岗。"),
            CandidateAction(id="quit_and_study", title="辞职全职学习", description="辞职后全职学习三个月。"),
        ]
        return CandidateSpace(actions=actions)


class FakeEvaluator(Evaluator):
    info = EvaluatorInfo(name="fake", version="fake/0", experimental=True)

    def evaluate(self, problem, actions):
        ids = [a.id for a in actions]
        excluded = {"quit_and_study": ["no_quit_now"]} if "quit_and_study" in ids else {}
        order = [i for i in ids if i not in excluded] + [i for i in ids if i in excluded]
        return Evaluation(order=order, choice=order[0] if order[0] not in excluded else None, excluded=excluded,
                       reason="作品集最快建立可信度。", checks_constraints=True)


class FailingFormulator(Formulator):
    def formulate(self, request):
        raise type("APIConnectionError", (Exception,), {})("down")


def fake_engine(**overrides) -> DecisionEngine:
    parts = dict(formulator=FakeFormulator(), clarifier=FakeClarifier(), generator=FakeGenerator(),
                 evaluator=FakeEvaluator(), generator_version=lambda: "fake-llm")
    parts.update(overrides)
    return DecisionEngine(**parts)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.db import Base, engine
    from backend.main import app
    from backend.security import limiter

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    limiter.failures.clear()
    app.state.engine_factory = fake_engine
    with TestClient(app) as c:
        yield c
