"""KRINO Matrix 模型的评估接口；模型本身在 model/。

数据源（DataSource / sagax）在 data/sources/。KRINO WORLD 只把这里当作内部的互动策略后端使用（backend/app/policy.py，KRINO_POLICY=matrix）。
旧的决策导航流程（engine.py、steps/）已归档到 archive/decision-nav/。

  contract.py  评估器信息等数据结构
  evaluator/   Evaluator 接口、Matrix 模型评估器、显式安全规则
  common/      基础数据结构（Problem / Action / Constraint）、LLM 客户端与调用记录
"""
