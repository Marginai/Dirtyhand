import logging
import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.api.deps import get_agent, get_app_settings, get_rag, optional_service_auth
from app.evaluation import evaluate_answer
from app.exceptions import AgentExecutionError
from app.observability.langfuse_client import trace_chat_request
from app.schemas.chat import ChatRequest, ChatResponse
from app.security.output_safety import contains_sensitive_output, filter_sensitive_output
from app.security.prompt_injection import sanitize_or_block_prompt_injection
from app.services.agent_service import AgentService
from app.services.rag_service import RAGService
from app.settings import Settings

logger = logging.getLogger(__name__)


def _last_user_message_text(messages: list) -> str:
    """Extract the last user message for validation and tracing."""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            c = m.content
            return c if isinstance(c, str) else str(c)
    return ""


def _to_lc_messages(messages: list) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        role = m["role"] if isinstance(m, dict) else getattr(m, "role", None)
        content = m["content"] if isinstance(m, dict) else getattr(m, "content", "")
        if role in ("user", "system"):
            out.append(HumanMessage(content=content))
        else:  # assistant
            out.append(AIMessage(content=content))
    return out


def _last_assistant_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            c = m.content
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                parts = []
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                return "".join(parts) or str(c)
            return str(c)
    return ""


async def post_chat(
    request: Request,
    body: ChatRequest,
    agent: Annotated[AgentService, Depends(get_agent)],
    rag: Annotated[RAGService, Depends(get_rag)],
    settings: Annotated[Settings, Depends(get_app_settings)],
):
    # Sanitize all client-controlled content before any LLM/tool call.
    sanitized_client_messages = []
    for m in body.messages:
        sanitized_client_messages.append(
            {
                "role": m.role,
                "content": sanitize_or_block_prompt_injection(m.content, log_event=True),
            }
        )

    lc_messages = _to_lc_messages(sanitized_client_messages)
    last_user_text = _last_user_message_text(lc_messages)

    # --- RAG context for pass-rate evaluation ---
    rag_context = rag.format_context(last_user_text) if last_user_text else ""
    empty_retrieval = not rag_context.strip()

    # --- Langfuse: one trace per request ---
    rid = getattr(request.state, "request_id", "-")
    metadata = {"request_id": rid, "empty_retrieval": empty_retrieval}

    with trace_chat_request(input_query=last_user_text, metadata=metadata) as span:
        start = time.perf_counter()
        try:
            result_messages = await agent.ainvoke(lc_messages)
            latency_ms = (time.perf_counter() - start) * 1000
            text = _last_assistant_text(result_messages)
            if not text:
                text = "I could not produce a response."

            # --- Pass-rate evaluation (Langfuse only) ---
            score = evaluate_answer(text, rag_context, settings)

            sensitive_detected = contains_sensitive_output(text)
            filtered_text = filter_sensitive_output(text)

            # --- Langfuse: update trace with final output, latency, pass_rate ---
            _safe_span_update(
                span,
                {**metadata, "ungrounded": score == 0, "sensitive_redacted": sensitive_detected},
                latency_ms,
                "success",
                output={"response": filtered_text[:2000]},
            )
            _safe_span_score(span, score, "1=pass, 0=fail")

            return ChatResponse(message=filtered_text)
        except AgentExecutionError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.exception("Agent execution failed: %s", e.message)
            _safe_span_update(
                span, metadata, latency_ms, "agent_error",
                output={"error": e.message},
            )
            _safe_span_score(span, 0, "agent_execution_error")
            # In production, do not expose internal exception text to clients.
            client_message = (
                "Agent failed to execute."
                if settings.is_production and not settings.debug
                else e.message
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": e.code, "message": client_message},
            ) from e
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.exception("Unhandled chat error")
            _safe_span_update(
                span, metadata, latency_ms, "exception",
                output={"error": str(e)[:500]},
            )
            _safe_span_score(span, 0, "exception")
            raise


def _safe_span_update(span: Any, metadata: dict, latency_ms: float, status: str, **kwargs: Any) -> None:
    """Update span without breaking request on Langfuse errors."""
    try:
        span.update(
            metadata={**metadata, "latency_ms": round(latency_ms, 2), "status": status},
            **kwargs,
        )
    except Exception as ex:
        logger.warning("Langfuse span update failed: %s", ex)


def _safe_span_score(span: Any, value: int | float, comment: str = "") -> None:
    """Add pass_rate score without breaking request on Langfuse errors."""
    try:
        span.score(name="pass_rate", value=float(value), comment=comment)
    except Exception as ex:
        logger.warning("Langfuse span score failed: %s", ex)
