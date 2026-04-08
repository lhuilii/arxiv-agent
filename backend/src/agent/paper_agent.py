"""ReAct Agent with Qwen LLM, streaming, and Redis-backed conversation memory."""
import logging
import os
from typing import AsyncIterator, Optional

from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.tools import AGENT_TOOLS
from src.cache.redis_manager import get_redis_manager
from src.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert academic research assistant specialized in analyzing scientific papers from ArXiv.

Your capabilities:
- Search for papers on ArXiv and in the vector knowledge base
- Retrieve and analyze full paper content
- Compare multiple papers on methodology and contributions
- Generate comprehensive research reports

Tool selection strategy (follow this strictly):
- For overview/survey questions ("最新进展", "survey", "what's new in X"): call `generate_report` FIRST — it already aggregates search and context in one call. Do NOT call search_papers separately before generate_report.
- For a specific paper: call `get_paper_detail` or `analyze_paper` once, then answer directly.
- For comparing papers: use `compare_papers` with a comma-separated list — do NOT call analyze_paper for each paper individually.
- Limit `search_papers` to at most 1-2 calls per conversation turn. If the first search returns results, proceed with those.
- After gathering context from tools, synthesize and answer immediately — do NOT call more tools than necessary.

Guidelines:
- Always cite specific paper IDs and titles when referencing papers
- Be precise about technical claims
- When analyzing papers, structure your response clearly
- For comparative analysis, use tables or structured lists
- Always provide ArXiv links when available

Respond in the same language as the user's question (Chinese or English)."""


class PaperAgent:
    """Multi-turn conversational Agent for paper research."""

    def __init__(self):
        self._settings = get_settings()
        self._llm: Optional[ChatTongyi] = None
        self._executor: Optional[AgentExecutor] = None

    def initialize(self) -> None:
        """Set up LLM, tools, memory, and agent executor."""
        os.environ["DASHSCOPE_API_KEY"] = self._settings.dashscope_api_key

        # Configure LangSmith tracing via environment
        if self._settings.langchain_tracing_v2:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = self._settings.langchain_api_key
            os.environ["LANGCHAIN_PROJECT"] = self._settings.langchain_project
            os.environ["LANGCHAIN_ENDPOINT"] = self._settings.langchain_endpoint

        self._llm = ChatTongyi(
            model="qwen-plus",
            streaming=True,
            temperature=0.1,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        agent = create_tool_calling_agent(
            llm=self._llm,
            tools=AGENT_TOOLS,
            prompt=prompt,
        )

        self._executor = AgentExecutor(
            agent=agent,
            tools=AGENT_TOOLS,
            verbose=True,
            max_iterations=15,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )
        logger.info("PaperAgent initialized with qwen-plus and %d tools", len(AGENT_TOOLS))

    async def chat(
        self,
        user_input: str,
        session_id: str,
        stream: bool = True,
    ) -> AsyncIterator[dict]:
        """Process a user message and yield streamed response events.

        Yields dicts of shape:
            {"type": "token", "content": str}
            {"type": "tool_start", "tool": str, "input": str}
            {"type": "tool_end", "tool": str, "output": str}
            {"type": "final", "content": str, "steps": list}
            {"type": "error", "content": str}
        """
        if self._executor is None:
            raise RuntimeError("PaperAgent not initialized. Call initialize() first.")

        redis = get_redis_manager()

        # Load conversation history
        history_raw = await redis.get_session_history(session_id)
        chat_history = []
        for msg in history_raw:
            if msg["role"] == "human":
                chat_history.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "ai":
                chat_history.append(AIMessage(content=msg["content"]))

        try:
            steps = []
            final_output = ""

            async for event in self._executor.astream_events(
                {
                    "input": user_input,
                    "chat_history": chat_history,
                },
                version="v1",
                config={
                    "run_name": f"paper_agent_{session_id[:8]}",
                    "tags": ["arxiv-agent", f"session:{session_id[:8]}"],
                    "metadata": {"session_id": session_id},
                },
            ):
                kind = event["event"]

                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk is not None:
                        content = getattr(chunk, "content", "")
                        if isinstance(content, str) and content:
                            yield {"type": "token", "content": content}
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    text = part.get("text", "")
                                    if text:
                                        yield {"type": "token", "content": text}

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    tool_output = str(event["data"].get("output", ""))[:200]
                    tool_input = str(event["data"].get("input", ""))
                    steps.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "output": tool_output,
                    })
                    yield {"type": "tool_end", "tool": tool_name, "output": tool_output}

                elif kind == "on_chain_end" and event.get("name") == f"paper_agent_{session_id[:8]}":
                    output = event["data"].get("output", {})
                    if isinstance(output, dict):
                        final_output = output.get("output", "")
                    else:
                        final_output = str(output)

            yield {"type": "final", "content": final_output, "steps": steps}

            # Persist to Redis session history
            await redis.append_session_message(session_id, "human", user_input)
            await redis.append_session_message(session_id, "ai", final_output)

        except Exception as e:
            logger.exception(f"Agent error for session {session_id}: {e}")
            yield {"type": "error", "content": str(e)}
