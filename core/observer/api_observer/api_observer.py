import json
from datetime import date
from typing import Any

from pydantic import ValidationError

from services.llm import LLM, ToolCall
from ...schema import State, Problem, constraints_text
from ...data.data_source import DataSource, Query
from ..observer import Observer


# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
PROMPT = """You are the observer of a decision system. Before candidate actions are generated, use the data \
tools to gather the facts needed to make this decision well.

Requirements:
- Only query data that could change the decision; if no tool is relevant, call none.
- Turn the constraints and preferences into tool parameters (filters, permissions, thresholds), \
so the results only contain options that satisfy them.
- Gather enough options for real alternatives, then look into the most promising ones.
- When you have gathered enough, stop calling tools and reply with one sentence on what you gathered.

Today: {today}

State:
{state}

Goal:
{goal}

Constraints:
{constraints}"""


class APIObserver(Observer):
    """Gathers data by letting a hosted LLM call the queries of the data sources as tools.

    Query results are added to the state as-is under "observations", so no figure passes through the LLM.
    """

    def __init__(
        self,
        sources: list[DataSource],
        llm: LLM | None = None,
        max_rounds: int = 5
    ):
        self.llm = llm or LLM()
        self.max_rounds = max_rounds
        self.queries: dict[str, Query] = {}
        self.tools: list[dict] = []
        for source in sources:
            for query in source.queries():
                name = f"{source.name}_{query.name}"
                self.queries[name] = query
                self.tools.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"{source.description}. {query.description}",
                        "parameters": query.params.model_json_schema(),
                    },
                })

    def observe(
        self,
        problem: Problem
    ) -> State:
        messages: list[dict] = [{"role": "user", "content": PROMPT.format(
            today=date.today().isoformat(),
            state=json.dumps(problem.state.data, ensure_ascii=False, indent=2),
            goal=problem.goal,
            constraints=constraints_text(problem.constraints),
        )}]
        observations = []
        for _ in range(self.max_rounds):
            response = self.llm.chat(messages, tools=self.tools)
            if not response.tool_calls:
                break
            messages.append(response.to_message())
            for call in response.tool_calls:
                result, ok = self._run(call)
                if ok:
                    observations.append({"query": call.name, "params": call.arguments, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        if not observations:
            return problem.state
        return State(data={**problem.state.data, "observations": observations})

    def _run(
        self,
        call: ToolCall
    ) -> tuple[Any, bool]:
        """The query result and whether it succeeded; failures go back to the LLM so it can retry."""
        query = self.queries.get(call.name)
        if query is None:
            return {"error": f"Unknown tool {call.name!r}"}, False
        try:
            params = query.params.model_validate(call.arguments)
        except ValidationError as e:
            return {"error": f"Invalid parameters: {e}"}, False
        try:
            return query.run(params), True
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}, False
