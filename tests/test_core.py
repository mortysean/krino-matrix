from conftest import FailingFormulator, FakeGenerator, fake_engine
from krino.contract import Answer, CoreInput
from krino.steps.generator import CandidateAction
from krino.evaluator.rules import requires_confirmation


def test_asks_one_question_first():
    response = fake_engine().run(CoreInput(objective="我想转行做数据分析"))
    assert response.type == "clarification"
    assert response.asked == 1 and response.question.kind == "single"


def test_decides_after_answer_and_excludes_hard_constraint_breakers():
    answer = Answer(question_id="sql_level", question="你现在的 SQL 水平？", values=["入门"])
    stages = []
    response = fake_engine().run(CoreInput(objective="我想转行做数据分析", answers=[answer]), stages.append)
    assert stages == ["understand", "clarify", "compare"]
    assert response.type == "decision"
    assert response.best_action == "build_portfolio"
    assert response.headline == "先做两个数据分析作品"
    assert [a.id for a in response.actions][-1] == "quit_and_study"
    assert response.actions[-1].excluded_by == ["no_quit_now"]
    # the evaluator gave no numbers, so none may be shown
    assert response.action_scores is None and response.confidence is None
    assert any("KRINO Matrix" in w for w in response.warnings)


def test_decide_now_skips_questions():
    response = fake_engine().run(CoreInput(objective="我想转行做数据分析", max_questions=0))
    assert response.type == "decision"


def test_model_down_is_an_error_not_a_conclusion():
    response = fake_engine(formulator=FailingFormulator()).run(CoreInput(objective="我想转行"))
    assert response.type == "error" and response.code == "model_unavailable"


def test_no_actions():
    response = fake_engine(generator=FakeGenerator(actions=[])).run(CoreInput(objective="x", max_questions=0))
    assert response.type == "error" and response.code == "no_actions"


def test_money_actions_need_confirmation():
    assert requires_confirmation("买入 2 只银行股")
    assert requires_confirmation("Transfer the deposit")
    assert not requires_confirmation("先做两个数据分析作品")
    action = CandidateAction(id="buy_index_fund", title="买入指数基金", description="分批买入沪深300ETF。")
    response = fake_engine(generator=FakeGenerator(actions=[action])).run(CoreInput(objective="理财", max_questions=0))
    assert response.actions[0].requires_confirmation
    assert any("确认" in w for w in response.warnings)
