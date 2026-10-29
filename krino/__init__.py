"""KRINO Matrix: one decision turn; the Matrix model behind the ranker lives in model/.

  schema / contract     basic elements; the clarification / decision / error responses clients get
  formulator, clarifier, generator, ranker, rules, engine
                        request → problem → one question or none → candidates → ranking → safety rules → response
  matrix                the labeled case format the model is trained and benchmarked on
  llm, tracing          hosted-LLM access, and per-turn call records
  data/                 DataSource / Query interface and the sagax source
"""
