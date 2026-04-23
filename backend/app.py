"""
ChatKit Demo Backend using OpenAI ChatKit SDK

This backend implements the ChatKit server protocol, providing a chat interface
using the OpenAI ChatKit SDK.
"""

import os
import json
from collections.abc import AsyncIterator
from datetime import datetime
import random
import sys
import uuid
import httpx
import logging
import warnings
from typing import Any, Dict

# ChatKit still emits this deprecation from its internal widget validation path
# even when using WidgetTemplate-backed widgets.
warnings.filterwarnings(
    "ignore",
    message="Direct usage of named widget classes is deprecated.*",
    category=DeprecationWarning,
)

import uvicorn
from agents import (
    Agent,
    FileSearchTool,
    GuardrailFunctionOutput,
    input_guardrail,
    InputGuardrailTripwireTriggered,
    ModelSettings,
    Runner,
    set_default_openai_client,
)
from openai import AsyncOpenAI
from openai.types.responses.response_output_text import (
    AnnotationContainerFileCitation,
    AnnotationFileCitation,
)
from openai.types.shared import Reasoning
from pydantic import BaseModel, Field
from chatkit.agents import (
    AgentContext,
    ResponseStreamConverter,
    simple_to_agent_input,
    stream_agent_response,
)
from chatkit.server import ChatKitServer, StreamingResult
from chatkit.types import (
    Annotation,
    AssistantMessageContent,
    AssistantMessageItem,
    FileSource,
    ThreadItemDoneEvent,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
    WidgetItem,
)
from chatkit.widgets import WidgetTemplate
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from simple_store import SimpleStore

# Load environment variables
load_dotenv()

# TODO: USE WATSON PROJECT ID; USING CONV UI PROJ KEY TEMPORARILY FOR NOW
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID") # old: "proj_hchduxzFJuIYU0P7tOG9sL55"
VECTOR_STORE_ID = os.getenv("OPENAI_VECTOR_STORE_ID") # old: vs_69d679dd6ca8819181d3da3e147f2414

if not OPENAI_PROJECT_ID:
    raise RuntimeError("Missing OPENAI_PROJECT_ID in backend environment")

if not VECTOR_STORE_ID:
    raise RuntimeError("Missing OPENAI_VECTOR_STORE_ID in backend environment")

REFERENCE_CARD_AVATAR_URL = (
    "https://www.cedars-sinai.org/etc.clientlibs/cedars-sinai/clientlibs/"
    "clientlib-react/resources/static/media/provider-avatar.0ff2508b7f1cbabed667.png"
)
SOURCES_WIDGET_TEMPLATE = WidgetTemplate.from_file("sources.widget")

openai_client = AsyncOpenAI(project=OPENAI_PROJECT_ID)
set_default_openai_client(openai_client)


RELEVANCY_GUARD_INSTRUCTIONS = (
    "Determine if the query is relevant to medical diagnosis, finding a doctor, "
    "or the capabilities of the agent. Return is_relevant=False if the query is "
    "not related to these topics."
)

CLARIFICATION_AGENT_INSTRUCTIONS = (
    "You review the full conversation and decide whether the user has given enough "
    "detail to search for doctors. "
    "Only request clarification when the user is asking about symptoms, pain, or a "
    "medical issue and the description is too vague to choose an appropriate doctor "
    "or specialty. "
    "When a symptom description is vague, require the most important missing detail "
    "before doctor lookup. "
    "Minimum detail rules for symptom complaints: "
    "1) require the exact body area or sub-region before lookup; "
    # "2) for limb or joint pain, require laterality when relevant; "
    # "3) require at least one additional discriminator such as duration, onset, "
    # "severity, impact, or injury/context. "
    "Ask only one highest-value follow-up question at a time. "
    "Do not ask for details that are already present anywhere in the conversation. "
    "If the user already named a specific specialty or gave enough detail to search, "
    "set needs_clarification to false. "
    "For clarification turns, you may include a short, broad, tentative specialty "
    "hint, but never a diagnosis and never a specific doctor recommendation. "
    "For example, vague leg pain may tentatively point toward orthopedics or sports "
    "medicine while still requiring the exact location. "
    "If no clarification is needed, return an empty follow_up_question and no hint."
    "Summarize (for the user) the details you have already discerned and put that in the details_summary field. Do not mention details you are missing. Summarize in a conversational manner."
)

RAG_AGENT_INSTRUCTIONS = (
    "You are a doctor-finder assistant. Your job is to help users find doctors who "
    "match their symptoms or health requirements. You have access to a Knowledge "
    "Base of valid doctors and their specialties. "
    "Only use information from the Knowledge Base. "
    "If no answer is found, say 'I don't know' or similar. "
    "If results have address data, make sure to include all of it in the response "
    "and citations. "
    "Do not mention the file store directly, just the references themselves. "
    # "Make sure to cite sources when you use them. "
    "If the input is blank or just regular conversation, you can greet or respond "
    "to the user in a friendly manner. "
    "Use list formatting when appropriate."
    "Don't include languages or gender in the response, unless it is relevant to the user's search."
)

OUT_OF_SCOPE_MESSAGE = "Sorry, this falls outside of the scope I am able to assist with."
DEFAULT_CLARIFICATION_QUESTION = (
    "Can you tell me exactly where the pain or symptom is located and how long "
    "it has been going on?"
)


class RelevancyCheck(BaseModel):
    is_relevant: bool
    reasoning: str


class ClarificationCheck(BaseModel):
    needs_clarification: bool
    follow_up_question: str = ""
    missing_details: list[str] = Field(default_factory=list)
    tentative_specialty_hint: str | None = None
    details_summary: str


class ReferenceSource(BaseModel):
    key: str
    title: str
    destination: str
    filename: str | None = None
    subtitle: str | None = None


guardrail_agent = Agent(
    name="Query Relevance Guard",
    instructions=RELEVANCY_GUARD_INSTRUCTIONS,
    output_type=RelevancyCheck,
)


clarification_agent = Agent(
    name="Symptom Clarification Gate",
    instructions=CLARIFICATION_AGENT_INSTRUCTIONS,
    output_type=ClarificationCheck,
)


@input_guardrail(run_in_parallel=False) # ensures that it finishes before streaming starts
async def relevancy_guard(ctx, agent, input_data):
    result = await Runner.run(guardrail_agent, input_data, context=ctx)
    _log_token_usage("relevancy_guard", result)
    analysis: RelevancyCheck = result.final_output
    print(f"Relevancy check: is_relevant={analysis.is_relevant}, reasoning={analysis.reasoning}")

    return GuardrailFunctionOutput(
        tripwire_triggered=not analysis.is_relevant,
        output_info=analysis.reasoning
    )


rag_agent = Agent(
    name="RAG assistant",
    instructions=RAG_AGENT_INSTRUCTIONS,
    tools=[
        FileSearchTool(
            vector_store_ids=[VECTOR_STORE_ID],
            max_num_results=10,
            include_search_results=True,
        )
    ],
    input_guardrails=[relevancy_guard],
    model="gpt-5-nano",
    model_settings=ModelSettings(
        reasoning=Reasoning(
            effort="low"
        ),
        parallel_tool_calls=True
    )
)

LOG_FORMAT = "%(asctime)s %(message)s"
logging.basicConfig(
    format=LOG_FORMAT,
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
LOGGER = logging.getLogger(__name__)


def build_assistant_message_event(
    store: SimpleStore,
    thread: ThreadMetadata,
    context: dict[str, Any],
    message_text: str,
) -> ThreadItemDoneEvent:
    message = AssistantMessageItem(
        id=store.generate_item_id("message", thread, context),
        thread_id=thread.id,
        created_at=datetime.now(),
        content=[
            AssistantMessageContent(
                text=message_text,
                annotations=[],
            )
        ],
    )
    return ThreadItemDoneEvent(item=message)


def build_reference_source(
    *,
    filename: str,
    display_name: str | None,
    subtitle: str | None,
) -> ReferenceSource:
    normalized_filename = filename.strip()
    normalized_title = (display_name or "").strip() or normalized_filename or "Untitled reference"
    normalized_subtitle = subtitle.strip() if isinstance(subtitle, str) and subtitle.strip() else None
    destination = normalized_filename or normalized_title
    key = f"file|{normalized_title}|{normalized_filename or normalized_subtitle or ''}"

    return ReferenceSource(
        key=key,
        title=normalized_title,
        destination=destination,
        filename=normalized_filename or None,
        subtitle=normalized_subtitle,
    )


def build_sources_widget_event(
    store: SimpleStore,
    thread: ThreadMetadata,
    context: dict[str, Any],
    reference_sources: list[ReferenceSource],
) -> ThreadItemDoneEvent:
    copy_text = "\n".join(
        f"{source.title}: {source.subtitle}" if source.subtitle else source.title
        for source in reference_sources
    )
    widget_item = WidgetItem(
        id=store.generate_item_id("message", thread, context),
        thread_id=thread.id,
        created_at=datetime.now(),
        widget=SOURCES_WIDGET_TEMPLATE.build(
            {
                "avatar_url": REFERENCE_CARD_AVATAR_URL,
                "reference_sources": reference_sources,
            }
        ),
        copy_text=copy_text or None,
    )
    return ThreadItemDoneEvent(item=widget_item)


def format_clarification_message(clarification: ClarificationCheck) -> str:
    follow_up_question = clarification.follow_up_question.strip() or DEFAULT_CLARIFICATION_QUESTION
    details_summary = clarification.details_summary
    tentative_hint = (clarification.tentative_specialty_hint or "").strip()
    if tentative_hint:
        LOGGER.info(f"Tentative guess: {tentative_hint}")
    #     return f"{tentative_hint}\n\n{details_summary}\n\n{follow_up_question}"
    # return follow_up_question
    return f"{details_summary}\n\n{follow_up_question}"


class VectorStoreCitationConverter(ResponseStreamConverter):
    """Enrich file citations with vector-store attributes for frontend display."""

    def __init__(
        self,
        client: AsyncOpenAI,
        vector_store_id: str,
        metadata_cache: dict[str, tuple[str | None, str | None]] | None = None,
    ):
        super().__init__()
        self.client = client
        self.vector_store_id = vector_store_id
        self._citation_metadata_cache = metadata_cache if metadata_cache is not None else {}
        self._reference_sources: dict[str, ReferenceSource] = {}

    def _metadata_from_attributes(
        self, attributes: dict[str, Any] | None
    ) -> tuple[str | None, str | None]:
        attributes = attributes or {}

        display_name: str | None = None
        raw_name = attributes.get("name")
        if isinstance(raw_name, str):
            stripped_name = raw_name.strip()
            if stripped_name:
                display_name = stripped_name

        address_line_1: str | None = None
        raw_address_line_1 = attributes.get("addressLine1")
        if isinstance(raw_address_line_1, str):
            stripped_address_line_1 = raw_address_line_1.strip()
            if stripped_address_line_1:
                address_line_1 = stripped_address_line_1

        locality_parts: list[str] = []
        for key in ("city", "regionCode"):
            raw_value = attributes.get(key)
            if isinstance(raw_value, str):
                stripped_value = raw_value.strip()
                if stripped_value:
                    locality_parts.append(stripped_value)

        locality = ", ".join(locality_parts) if locality_parts else None
        subtitle_lines = [line for line in (address_line_1, locality) if line]
        subtitle = "\n".join(subtitle_lines) if subtitle_lines else None

        return display_name, subtitle

    def _remember_reference_source(
        self,
        *,
        filename: str,
        display_name: str | None,
        subtitle: str | None,
    ) -> None:
        reference_source = build_reference_source(
            filename=filename,
            display_name=display_name,
            subtitle=subtitle,
        )
        if reference_source.key not in self._reference_sources:
            self._reference_sources[reference_source.key] = reference_source

    def cache_file_search_results(self, results: list[Any] | None) -> None:
        if not results:
            return

        for result in results:
            file_id = getattr(result, "file_id", None)
            if not isinstance(file_id, str) or not file_id:
                continue
            self._citation_metadata_cache[file_id] = self._metadata_from_attributes(
                getattr(result, "attributes", None)
            )

    async def _get_citation_metadata(self, file_id: str) -> tuple[str | None, str | None]:
        if file_id in self._citation_metadata_cache:
            return self._citation_metadata_cache[file_id]

        try:
            vector_store_file = await self.client.vector_stores.files.retrieve(
                file_id=file_id,
                vector_store_id=self.vector_store_id,
            )
        except Exception:
            LOGGER.exception(
                "Failed to retrieve vector store metadata for citation file_id=%s",
                file_id,
            )
            self._citation_metadata_cache[file_id] = (None, None)
            return (None, None)

        metadata = self._metadata_from_attributes(vector_store_file.attributes or {})
        self._citation_metadata_cache[file_id] = metadata
        return metadata

    def take_reference_sources(self) -> list[ReferenceSource]:
        return list(self._reference_sources.values())

    async def _build_file_annotation(
        self,
        *,
        file_id: str,
        filename: str,
        index: int,
    ) -> Annotation | None:
        if not filename:
            return None

        display_name, subtitle = await self._get_citation_metadata(file_id)
        self._remember_reference_source(
            filename=filename,
            display_name=display_name,
            subtitle=subtitle,
        )
        return Annotation(
            source=FileSource(
                filename=filename,
                title=display_name or filename,
                description=subtitle,
            ),
            index=index,
        )

    async def file_citation_to_annotation(
        self, file_citation: AnnotationFileCitation
    ) -> Annotation | None:
        return await self._build_file_annotation(
            file_id=file_citation.file_id,
            filename=file_citation.filename,
            index=file_citation.index,
        )

    async def container_file_citation_to_annotation(
        self, container_file_citation: AnnotationContainerFileCitation
    ) -> Annotation | None:
        return await self._build_file_annotation(
            file_id=container_file_citation.file_id,
            filename=container_file_citation.filename,
            index=container_file_citation.end_index,
        )


class MetadataCachingRunResult:
    """Intercept file search tool results so citation metadata can be cached."""

    def __init__(
        self,
        result: Any,
        converter: VectorStoreCitationConverter,
    ):
        self._result = result
        self._converter = converter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._result, name)

    async def stream_events(self) -> AsyncIterator[Any]:
        async for event in self._result.stream_events():
            if event.type == "raw_response_event":
                raw_event = event.data
                if raw_event.type == "response.output_item.done":
                    item = raw_event.item
                    if getattr(item, "type", None) == "file_search_call":
                        self._converter.cache_file_search_results(
                            getattr(item, "results", None)
                        )
            yield event





class DemoChatKitServer(ChatKitServer[Dict[str, Any]]):
    """ChatKit server implementation."""

    def __init__(self, data_store: SimpleStore):
        # Initialize with no attachment store for simplicity
        super().__init__(data_store, attachment_store=None)
        self._citation_metadata_cache: dict[str, tuple[str | None, str | None]] = {}


    async def respond(
        self,
        thread: ThreadMetadata,
        input_user_message: UserMessageItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        """Handle incoming user messages and generate responses."""
        # Run the agent *streamed* with full thread history
        agent_ctx = AgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )

        items_page = await self.store.load_thread_items(
            thread.id,
            after=None,
            limit=1000,
            order="asc",
            context=context,
        )
        agent_input = await simple_to_agent_input(items_page.data)

        try:
            clarification_result = await Runner.run(
                clarification_agent,
                agent_input,
                context=agent_ctx,
            )
            _log_token_usage("clarification_agent", clarification_result)
            clarification: ClarificationCheck = clarification_result.final_output
            LOGGER.info(
                "Clarification gate: needs_clarification=%s missing_details=%s",
                clarification.needs_clarification,
                clarification.missing_details,
            )
            if clarification.needs_clarification:
                yield build_assistant_message_event(
                    self.store,
                    thread,
                    context,
                    format_clarification_message(clarification),
                )
                return

            citation_converter = VectorStoreCitationConverter(
                openai_client,
                VECTOR_STORE_ID,
                metadata_cache=self._citation_metadata_cache,
            )
            result = Runner.run_streamed(rag_agent, agent_input, context=agent_ctx)

            metadata_caching_result = MetadataCachingRunResult(
                result,
                citation_converter,
            )

            # IMPORTANT: this converts Responses/Agents streaming events -> ChatKit ThreadStreamEvents
            # and auto-attaches file/url citations as ChatKit annotations (Sources in UI).
            async for ev in stream_agent_response(
                agent_ctx,
                metadata_caching_result,
                converter=citation_converter,
            ):
                yield ev
            reference_sources = citation_converter.take_reference_sources()
            if reference_sources:
                yield build_sources_widget_event(
                    self.store,
                    thread,
                    context,
                    reference_sources,
                )
            _log_token_usage("rag_agent", result)
        except InputGuardrailTripwireTriggered as exc:
            output_info = exc.guardrail_result.output.output_info
            LOGGER.info("Input guardrail triggered: %s", output_info)
            yield build_assistant_message_event(
                self.store,
                thread,
                context,
                OUT_OF_SCOPE_MESSAGE,
            )




# Create FastAPI app
app = FastAPI(title="ChatKit Demo Backend")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create store and server
data_store = SimpleStore()
chatkit_server = DemoChatKitServer(data_store)


@app.post("/chatkit")
async def chatkit_endpoint(request: Request):
    body = await request.body()
    request_id = str(uuid.uuid4())
    context = {"request_id": request_id}

    LOGGER.info("Processing /chatkit request_id=%s", request_id)

    print("threads: ", chatkit_server.store.threads)
    result = await chatkit_server.process(body, context)

    # STREAMING (SSE)
    if  isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")

    # NON-STREAMING
    else:
        return Response(content=result.json, media_type="application/json")


# @app.post("/chatkit/session")
# async def chatkit_session():
#     session = chatkit_server.create_session(
#         # 👇 THIS is the critical part
#         api_url="https://your-python-api.example.com/chatkit"
#     )

#     return {
#         "client_secret": session.client_secret
#     }


# @app.post("/api/chatkit_session")
# async def create_chatkit_session(request: Request):
#     # Optional: get the frontend's allowed origin
#     origin = request.headers.get("origin")
#     cors_headers = {"Access-Control-Allow-Origin": origin or "*"}

#     try:
#         payload = await request.json()
#     except Exception:
#         return JSONResponse(
#             status_code=400,
#             content={"message": "Invalid JSON body"},
#             headers=cors_headers,
#         )
#     workflow_id = payload.get("workflowId") or payload.get("workflow_id")
#     if not workflow_id:
#         return JSONResponse(
#             status_code=400,
#             content={"message": "Missing workflowId"},
#             headers=cors_headers,
#         )

#     # Optionally, associate the session with a user ID
#     user_id = str(uuid.uuid4())
#     openai_api_key = os.getenv("OPENAI_API_KEY")
#     if not openai_api_key:
#         return JSONResponse(
#             status_code=500,
#             content={"message": "Missing OPENAI_API_KEY"},
#             headers=cors_headers,
#         )

#     url = "https://api.openai.com/v1/chatkit/sessions"
#     session_payload = {
#         "workflow": {"id": workflow_id},
#         "user": user_id,
#         "chatkit_configuration": { "file_upload": { "enabled": True } }
#     }

#     try:
#         async with httpx.AsyncClient(timeout=10.0) as client:
#             upstream_response = await client.post(
#                 url,
#                 headers={
#                     "Content-Type": "application/json",
#                     "Authorization": f"Bearer {openai_api_key}",
#                     "OpenAI-Beta": "chatkit_beta=v1",
#                 },
#                 json=session_payload,
#             )
#     except httpx.HTTPError as exc:
#         LOGGER.exception("Failed to create ChatKit session")
#         return JSONResponse(
#             status_code=502,
#             content={"message": "Failed to reach ChatKit API", "details": str(exc)},
#             headers=cors_headers,
#         )

#     upstream_json = upstream_response.json()
#     if upstream_response.is_error:
#         return JSONResponse(
#             status_code=upstream_response.status_code,
#             content={"message": "Failed to create session", "details": upstream_json},
#             headers=cors_headers,
#         )

#     client_secret = upstream_json.get("client_secret")
#     return JSONResponse(
#         status_code=200,
#         content={"clientSecret": client_secret},
#         headers=cors_headers,
#     )


def _extract_request_id(context: Any) -> str | None:
    current = context
    for _ in range(4):
        if current is None:
            return None
        if isinstance(current, dict):
            request_id = current.get("request_id")
            return request_id if isinstance(request_id, str) else None

        request_context = getattr(current, "request_context", None)
        if isinstance(request_context, dict):
            request_id = request_context.get("request_id")
            if isinstance(request_id, str):
                return request_id

        nested_context = getattr(current, "context", None)
        if nested_context is not None and nested_context is not current:
            current = nested_context
            continue
        if request_context is not None and request_context is not current:
            current = request_context
            continue
        break

    return None


def _log_token_usage(label: str, result: Any) -> None:
    context_wrapper = getattr(result, "context_wrapper", None)
    usage = getattr(context_wrapper, "usage", None)
    request_id = _extract_request_id(getattr(context_wrapper, "context", None))
    request_id_part = f" request_id={request_id}" if request_id else ""

    if usage is None:
        LOGGER.info("---- Token usage [%s]%s unavailable", label, request_id_part)
        return

    request_entries = list(getattr(usage, "request_usage_entries", []))
    if request_entries:
        for index, request_usage in enumerate(request_entries, start=1):
            LOGGER.info(
                "---- Token usage [%s call=%s/%s]%s input=%s output=%s total=%s",
                label,
                index,
                len(request_entries),
                request_id_part,
                request_usage.input_tokens,
                request_usage.output_tokens,
                request_usage.total_tokens,
            )

    LOGGER.info(
        "---- Token usage [%s total]%s input=%s output=%s total=%s requests=%s",
        label,
        request_id_part,
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        usage.requests,
    )



@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    
    print("=" * 60)
    print("🚀 ChatKit Server Starting")
    print("=" * 60)
    print(f"📍 Server: http://localhost:{port}")
    print(f"📡 ChatKit endpoint: http://localhost:{port}/chatkit")
    print(f"🔑 API Key configured: {bool(os.getenv('OPENAI_API_KEY'))}")
    print(f"🗂️ OpenAI project: {OPENAI_PROJECT_ID}")
    print(f"📚 Vector store: {VECTOR_STORE_ID}")
    print("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=port)
