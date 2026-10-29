"""Explicit safety rules, applied after the evaluator and independent of any model.

They never change the ranking; they mark what the user must confirm themselves.
"""
import re

# Actions that move money, sign something, or cannot be undone: never executed automatically, always confirmed
CONFIRM_PATTERNS = [
    r"付款|支付|转账|汇款|充值|购买|买入|卖出|下单|借款|贷款|杠杆|融资|抵押|签约|签署合同|辞职|退学|注销|删除|起诉",
    r"\b(pay|payment|transfer|wire|purchase|buy|sell|loan|borrow|leverage|margin|mortgage|sign (a|the) contract|"
    r"resign|quit|delete|sue)\b",
]
CONFIRM_RE = re.compile("|".join(CONFIRM_PATTERNS), re.IGNORECASE)


def requires_confirmation(text: str) -> bool:
    return bool(CONFIRM_RE.search(text))


def lang_of(text: str) -> str:
    return "zh" if any("一" <= ch <= "鿿" for ch in text) else "en"


MESSAGES = {
    "zh": {
        "confirm": "涉及资金、签约或不可逆操作，系统不会自动执行；执行前请你本人确认。",
        "unverified": "以下硬约束未经模型逐项验证，请自行确认：{items}",
        "pending": "以下约束模型无法确定是否满足，标记为待确认：{items}",
        "all_excluded": "所有候选都可能违反硬约束，暂无可推荐的行动。可以修改目标或放宽约束后重试。",
        "experimental": "KRINO Matrix 评估模型仍在实验阶段，尚未认定为生产可用。",
    },
    "en": {
        "confirm": "Involves money, a contract or an irreversible step. Nothing is executed automatically; "
                   "confirm it yourself first.",
        "unverified": "These hard constraints were not checked one by one by the model; please confirm: {items}",
        "pending": "The model could not tell whether these constraints hold, marked as pending: {items}",
        "all_excluded": "Every candidate may break a hard constraint, so there is no recommendation. "
                        "Edit the goal or relax a constraint and try again.",
        "experimental": "The KRINO Matrix evaluator is experimental and not yet approved for production.",
    },
}
