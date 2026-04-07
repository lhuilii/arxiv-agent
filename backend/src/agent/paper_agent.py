"""ReAct Agent with Qwen LLM, streaming, and Redis-backed conversation memory."""
import logging
import os
from typing import AsyncIterator, Optional

from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_classic.memory import ConversationBufferWindowMemory
from langchain_classic.callbacks import AsyncIteratorCallbackHandler
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
            max_iterations=8,
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

        callback = AsyncIteratorCallbackHandler()

        try:
            import asyncio

            task = asyncio.ensure_future(
                self._executor.ainvoke(
                    {
                        "input": user_input,
                        "chat_history": chat_history,
                    },
                    config={
                        "callbacks": [callback],
                        "run_name": f"paper_agent_{session_id[:8]}",
                        "tags": ["arxiv-agent", f"session:{session_id[:8]}"],
                        "metadata": {"session_id": session_id},
                    },
                )
            )

            # Stream tokens as they arrive
            async for token in callback.aiter():
                yield {"type": "token", "content": token}

            result = await task
            final_output = result.get("output", "")

            # Extract intermediate steps for tool trace
            steps = []
            for action, observation in result.get("intermediate_steps", []):
                steps.append(
                    {
                        "tool": action.tool,
                        "input": str(action.tool_input),
                        "output": str(observation)[:500],
                    }
                )
                yield {"type": "tool_end", "tool": action.tool, "output": str(observation)[:200]}

            yield {"type": "final", "content": final_output, "steps": steps}

            # Persist to Redis session history
            await redis.append_session_message(session_id, "human", user_input)
            await redis.append_session_message(session_id, "ai", final_output)

        except Exception as e:
            logger.exception(f"Agent error for session {session_id}: {e}")
            yield {"type": "error", "content": str(e)}
