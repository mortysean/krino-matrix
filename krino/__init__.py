"""KRINO Matrix decision flow; the Matrix model behind the evaluator lives in model/.

  engine.py   one decision turn through every step, and build_engine() for the web app
  steps/      the three hosted-LLM steps: formulator (request → problem), clarifier (one question or none),
              generator (candidate actions)
  evaluator/  the Evaluator interface, the Matrix-model evaluator, and the explicit safety rules
  common/     shared structures (schema, client contract, labeled case format), LLM client and call tracing
  data/       DataSource / Query interface and the sagax source
"""
