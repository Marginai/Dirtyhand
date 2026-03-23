"""LangGraph agent with Playwright tools and RAG context (no MemorySaver / checkpointer)."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from app.exceptions import AgentExecutionError, ConfigurationError
from app.services.browser_service import BrowserService
from app.services.rag_service import RAGService
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[list[Any], add_messages]


def _make_playwright_tools(browser: BrowserService, rag: RAGService, default_url: str) -> list:
    from langchain_core.tools import tool

    @tool
    async def scrape_text(
        url: str | None = None,
        max_chars: int = 20000,
    ) -> str:
        """Scrape a URL with Playwright and return page text (truncated to max_chars).

        This is a single-shot tool (no separate navigate/extract calls), which is safer under concurrency.
        """
        target_url = (url or default_url).strip()
        if not target_url:
            raise ConfigurationError(
                "Missing URL for scrape_text: provide `url` or set ORGANIZATION_URL in .env"
            )
        if "://" not in target_url:
            target_url = f"https://{target_url}"
        text = await browser.navigate_and_extract_text(target_url)
        truncated = len(text) > max_chars
        return (
            f"Scraped {len(text)} chars from {target_url}."
            + (" TRUNCATED." if truncated else "")
            + "\n\n"
            + text[:max_chars]
        )

    @tool
    async def scrape_and_ingest(
        url: str | None = None,
        max_chars: int = 20000,
    ) -> str:
        """Scrape a URL with Playwright and ingest the text into the RAG store.

        Returns truncated scraped text so the LLM can answer in the same request.
        """
        target_url = (url or default_url).strip()
        if not target_url:
            raise ConfigurationError(
                "Missing URL for scrape_and_ingest: provide `url` or set ORGANIZATION_URL in .env"
            )
        if "://" not in target_url:
            target_url = f"https://{target_url}"
        text = await browser.navigate_and_extract_text(target_url)
        truncated = len(text) > max_chars
        ingest_text = text[:max_chars]
        chunks_added = rag.add_text(ingest_text, metadata={"source": target_url})
        suffix = " (truncated)" if truncated else ""
        # Keep tool output bounded for token safety.
        sample = ingest_text[:2000]
        return (
            f"Scraped {len(text)} chars from {target_url}{suffix}. "
            f"Ingested {chunks_added} chunks into RAG. "
            f"Sample (first {len(sample)} chars):\n{sample}"
        )

    return [scrape_text, scrape_and_ingest]


class AgentService:
    """Compiles graph once; stateless between HTTP requests (client sends history)."""

    def __init__(
        self,
        rag: RAGService,
        browser: BrowserService,
        settings: Settings | None = None,
    ):
        self._settings = settings or get_settings()
        self._rag = rag
        self._browser = browser
        if not self._settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is not set")
        self._tools = _make_playwright_tools(browser, rag, default_url=self._settings.organization_url)
        self._llm = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.openai_api_key,
            temperature=0.2,
        )
        self._llm_with_tools = self._llm.bind_tools(self._tools)
        self._graph = self._build_graph()

    def _build_graph(self):
        def chatbot(state: AgentState) -> dict[str, list[BaseMessage]]:
            messages = list(state["messages"])
            response = self._llm_with_tools.invoke(messages)
            return {"messages": [response]}

        graph_builder = StateGraph(AgentState)
        graph_builder.add_node("chatbot", chatbot)
        graph_builder.add_node("tools", ToolNode(self._tools))
        graph_builder.add_conditional_edges("chatbot", tools_condition)
        graph_builder.add_edge("tools", "chatbot")
        graph_builder.add_edge(START, "chatbot")
        return graph_builder.compile()

    def _with_rag_context(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Inject RAG once per request (not on every agent/tool loop)."""
        last_human = _last_human_text(messages)

        if not last_human:
            return list(messages)

        ctx = self._rag.format_context(last_human)
        if not ctx:
            return list(messages)

        rag_msg = SystemMessage(content=f"Retrieved context:\n\n{ctx}")

        insert_at = 0
        for i, m in enumerate(messages):
            if isinstance(m, SystemMessage):
                insert_at = i + 1
            else:
                break
        return list(messages)[:insert_at] + [rag_msg] + list(messages)[insert_at:]

    async def ainvoke(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        config = {"recursion_limit": self._settings.agent_recursion_limit}
        augmented = self._with_rag_context(list(messages))
        try:
            result = await self._graph.ainvoke({"messages": augmented}, config=config)
            return list(result["messages"])
        except Exception as e:
            logger.exception("Agent invocation failed")
            raise AgentExecutionError(str(e), details={"type": type(e).__name__}) from e


def _last_human_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            c = m.content
            return c if isinstance(c, str) else str(c)
    return ""
