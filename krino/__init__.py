"""KRINO Matrix decision flow; the Matrix model behind the ranker lives in model/.

  engine.py   one decision turn through every step, and build_engine() for the web app
  steps/      the three hosted-LLM steps: formulator (request → problem), clarifier (one question or none),
              generator (candidate actions)
  ranker/     ranking: the Ranker interface, the Matrix ranker, and the explicit safety rules
  common/     shared structures (schema, client contract, labeled case format), LLM client and call tracing
  data/       DataSource / Query interface and the sagax source
"""
