"""Explicit serverless routes and single-attempt HTTP, with no execution policy.

Transport returns unparsed bytes. Persist those bytes before provider parsing.
Catalog observations describe advertised metadata, never tested serving identity.
The runner owns authority, reservations, retries and durable sequencing.
"""

import http.client
import json
import re
from http import HTTPStatus
from typing import Annotated, Literal, TypedDict, assert_never
from urllib.parse import urlsplit
lazy from collections.abc import Callable

from pydantic import BaseModel, Field, SecretStr, TypeAdapter

from safety_judge.errors import ConfigurationError, InvalidValueError
from safety_judge.judging import JudgeRole, OrdinalPayload, create_unique_json_object
lazy from safety_judge.judging import JudgeMessage, JudgeRequest
lazy from safety_judge.settings import ApplicationSettings

type ModelRole = JudgeRole | Literal["paraphraser", "reviewer"]
"""Owning judging roles plus the two explicit exploratory H2 functions."""

type OutputMode = Literal["json_schema", "json_object", "prompt"]
"""Explicit frozen provider formatting mode; no response-dependent fallback."""


def create_ordinal_response_format(mode: OutputMode) -> dict[str, object] | None:
    """Render the strict ordinal schema identically for every supported judge.

    Args:
        mode: Explicit schema, object-only, or unchanged prompt-only request mode.

    Returns:
        The provider response_format value, absent only for prompt-only mode.
    """
    if mode == "prompt":
        return None
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "safety_judge_ordinal",
            "strict": True,
            "schema": OrdinalPayload.model_json_schema(),
        },
    }


def create_unsupported_output_mode(result: HttpResult) -> bool:
    """Recognize only explicit provider rejection of the requested format feature.

    Args:
        result: Already durably saved single-attempt response or transport failure.

    Returns:
        True only for HTTP400/422 with explicit unsupported-format error evidence.
        Billing, invalid schema syntax, unknown delivery and HTTP200 never qualify.
    """
    if not isinstance(result, HttpResponse) or result.status not in {400, 422}:
        return False
    try:
        payload = TypeAdapter(dict[str, object]).validate_json(result.body)
        error = payload.get("error")
        facts = TypeAdapter(dict[str, object]).validate_python(error)
    except ValueError:
        return False
    message = facts.get("message")
    if not isinstance(message, str):
        return False
    text = message.lower().replace("'", "").replace('"', "")
    if any(
        marker in text
        for marker in ("invalid schema", "malformed", "keyword", "syntax")
    ):
        return False
    return (
        re.search(
            r"(?:json_schema|json_object)(?: response[_ ]format| format| mode| type)?"
            r"(?: is|:)?[ \t]+(?:not supported|unsupported|unavailable)"
            r"|(?:unsupported|unavailable|does not support|not support)"
            r"(?: response[_ ]format| format| mode| type)?[: \t]+"
            r"(?:json_schema|json_object)",
            text,
        )
        is not None
    )


class ModelRoute(BaseModel, frozen=True, extra="forbid"):
    """Advertised route metadata, independently of execution authorization.

    Attributes:
        role: Study role, selected explicitly by the caller.
        provider: Explicit serving account; never automatically substituted.
        endpoint: Exact permitted chat-completions URL.
        model: Exact advertised official serving identifier.
        precision: Advertised precision; unknown remains explicit.
        observed_on: Date of official metadata evidence.
        runtime_verified: False: no model inference has verified this route.
    """

    role: ModelRole
    provider: Literal["deepinfra", "huggingface"]
    endpoint: Literal[
        "https://api.deepinfra.com/v1/openai/chat/completions",
        "https://router.huggingface.co/v1/chat/completions",
    ]
    model: Annotated[str, Field(min_length=1)]
    precision: Literal["FP8", "BF16", "unknown"]
    observed_on: Literal["2026-10-17"] = "2026-10-17"
    runtime_verified: Literal[False] = False


class GenerationParameters(BaseModel, frozen=True, extra="forbid"):
    """Explicit frozen generation controls; never chosen to fit a budget.

    Attributes:
        maximum_output_tokens: Positive complete output generation bound.
        temperature: Finite sampling value between zero and two.
        timeout_seconds: Finite positive per-attempt timeout.
    """

    maximum_output_tokens: Annotated[int, Field(gt=0, strict=True)]
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)]
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class HttpRequest(BaseModel, frozen=True, extra="forbid"):
    """One outbound call; credential serialization is always excluded.

    Attributes:
        route: Explicit route selected before dispatch.
        api_key: Explicit bearer credential, excluded from serialization.
        body: Exact UTF-8 JSON request bytes, with no authentication fields.
        timeout_seconds: Finite positive single-attempt timeout.
    """

    route: ModelRoute
    api_key: SecretStr = Field(exclude=True, repr=False)
    body: bytes
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class HttpResponse(BaseModel, frozen=True, extra="forbid"):
    """Unparsed HTTP response; errors and redirects are ordinary saved evidence.

    Attributes:
        kind: Transport branch discriminator.
        status: Observed HTTP status.
        body: Exact response bytes, before parsing or secret redaction.
        delivery: Response observed; billing still requires verified settlement.
    """

    kind: Literal["response"] = "response"
    status: Annotated[int, Field(ge=100, le=599)]
    body: bytes
    delivery: Literal["response"] = "response"


class TransportFailure(BaseModel, frozen=True, extra="forbid"):
    """One failed attempt; ordinary timeouts/network errors have unknown delivery.

    Attributes:
        kind: Transport branch discriminator.
        reason: Safe category; exception text/credentials are never retained.
        delivery: Not-delivered requires independent transport certification.
    """

    kind: Literal["failure"] = "failure"
    reason: Literal["timeout", "network"]
    delivery: Literal["unknown", "not_delivered"]


type HttpResult = HttpResponse | TransportFailure
"""One unparsed attempt observation, never an instruction to retry."""

type HttpTransport = Callable[[HttpRequest], HttpResult]
"""Injected one-attempt transport; persistence and retry policy stay outside."""


class TokenUsage(BaseModel, frozen=True, extra="forbid"):
    """Observed billed usage; absent values are never converted to free calls.

    Attributes:
        prompt_tokens: Provider input usage, or None when absent.
        completion_tokens: Provider total output usage, or None when absent.
        reasoning_tokens: Output reasoning subset, or None when absent.
    """

    prompt_tokens: Annotated[int, Field(ge=0, strict=True)] | None
    completion_tokens: Annotated[int, Field(ge=0, strict=True)] | None
    reasoning_tokens: Annotated[int, Field(ge=0, strict=True)] | None


class ProviderObservation(BaseModel, frozen=True, extra="forbid"):
    """Normalized post-persistence content and billing observations.

    Attributes:
        content: Exact message content, or empty when unavailable.
        finish: Complete only for a recognized stop and valid single text choice.
        refused: Explicit provider refusal/content-filter signal.
        usage: Observed usage, or None for absent/malformed observations.
        served_model: Reported model identity, or None when absent.
        response_identifier: Provider response ID, or None when absent.
    """

    content: str
    finish: Literal["complete", "truncated", "unknown"]
    refused: bool
    usage: TokenUsage | None
    served_model: str | None
    response_identifier: str | None


def create_model_route(role: ModelRole) -> ModelRoute:
    """Select one frozen advertised route without fallback or model substitution.

    The 1B missing-roster exception uses the explicit HF Featherless suffix.

    Args:
        role: Exact requested study role.

    Returns:
        Official metadata observation, with runtime compatibility unverified.

    See Also:
        https://docs.deepinfra.com/chat/overview
        https://huggingface.co/docs/inference-providers/providers/featherless-ai
    """
    if role is JudgeRole.GEMMA_ONE:
        return ModelRoute(
            role=role,
            provider="huggingface",
            endpoint="https://router.huggingface.co/v1/chat/completions",
            model="google/gemma-3-1b-it:featherless-ai",
            precision="BF16",
        )
    match role:
        case JudgeRole.GEMMA_TWENTY_SEVEN:
            model = "google/gemma-3-27b-it"
        case JudgeRole.LLAMA_EIGHT:
            model = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
        case JudgeRole.QWEN_THIRTY_TWO:
            model = "Qwen/Qwen3-32B"
        case "paraphraser":
            model = "mistralai/Mistral-Small-3.2-24B-Instruct-2506"
        case "reviewer":
            model = "anthropic/claude-sonnet-4-6"
        case _:
            assert_never(role)
    return ModelRoute(
        role=role,
        provider="deepinfra",
        endpoint="https://api.deepinfra.com/v1/openai/chat/completions",
        model=model,
        precision="unknown" if role == "reviewer" else "FP8",
    )


def create_provider_api_key(
    settings: ApplicationSettings, route: ModelRoute
) -> SecretStr:
    """Select one explicit provider credential from already parsed settings.

    No environment is read here. Missing credentials never trigger fallback.

    Args:
        settings: ApplicationSettings supplied by the sole environment boundary.
        route: Explicit provider route requiring authentication.

    Returns:
        Selected nonempty settings-derived SecretStr.

    Raises:
        ConfigurationError: If the selected provider credential is absent/empty.
    """
    secret = (
        settings.deepinfra_api_key
        if route.provider == "deepinfra"
        else settings.huggingface_api_key
    )
    if secret is None or not secret.get_secret_value().strip():
        message = f"Credential for {route.provider} is missing; configure that account."
        raise ConfigurationError(message)
    return secret


def create_http_request(
    *,
    route: ModelRoute,
    messages: tuple[JudgeMessage, ...],
    api_key: SecretStr,
    parameters: GenerationParameters,
    output_mode: OutputMode = "prompt",
) -> HttpRequest:
    """Render a fixed nonstreaming chat request from explicit values and a secret.

    This constructs bytes only: it grants no execution or funding authority.
    Qwen explicitly disables thinking via chat_template_kwargs; compatibility
    remains execution-held. No unsupported reasoning_effort option is invented.

    Args:
        route: Exact frozen route, not a provider search request.
        messages: Complete frozen visible messages for judging/rewrite/review.
        api_key: Explicit nonempty credential; synthetic values support offline work.
        parameters: Frozen complete generation controls and attempt timeout.
        output_mode: Frozen provider formatting control, never chosen by validity.

    Returns:
        Serialized request with an excluded SecretStr credential.

    Raises:
        ConfigurationError: If the explicit credential is empty.
        InvalidValueError: If output bounds, sampling or route metadata differ.
    """
    if route != create_model_route(route.role):
        message = "Route differs from the roster; resolve metadata before dispatch."
        raise InvalidValueError(message)
    if not messages:
        message = "Request messages are empty; supply the frozen visible text."
        raise InvalidValueError(message)
    if not api_key.get_secret_value().strip():
        message = "API credential is empty; supply an explicit nonempty secret."
        raise ConfigurationError(message)
    payload: dict[str, object] = {
        "model": route.model,
        "messages": [message.model_dump() for message in messages],
        "max_tokens": parameters.maximum_output_tokens,
        "temperature": parameters.temperature,
        "top_p": 1,
        "n": 1,
        "stream": False,
    }
    if route.role is JudgeRole.QWEN_THIRTY_TWO:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    response_format = create_ordinal_response_format(output_mode)
    if response_format is not None:
        payload["response_format"] = response_format
    return HttpRequest(
        route=route,
        api_key=api_key,
        body=json.dumps(payload, separators=(",", ":"), allow_nan=False).encode(),
        timeout_seconds=parameters.timeout_seconds,
    )


def create_judge_http_request(
    *,
    request: JudgeRequest,
    route: ModelRoute,
    api_key: SecretStr,
    parameters: GenerationParameters,
    output_mode: OutputMode = "prompt",
) -> HttpRequest:
    """Adapt the owning blinded judge request without adding source metadata.

    Configuration/validation failures propagate from create_http_request.

    Args:
        request: Owning judge module's frozen visible text.
        route: Explicit nominal judge serving route.
        api_key: Explicit nonempty provider or synthetic offline credential.
        parameters: Frozen complete generation controls and attempt timeout.
        output_mode: Frozen provider formatting control for this judge route.

    Returns:
        Provider wire request with unchanged visible messages.
    """
    return create_http_request(
        route=route,
        messages=request.messages,
        api_key=api_key,
        parameters=parameters,
        output_mode=output_mode,
    )


def select_http_response(request: HttpRequest) -> HttpResult:
    """Perform exactly one HTTPS POST without redirects, retries or fallback.

    Exception text and request headers are never returned or logged. Errors after
    opening the connection have unknown delivery; even DNS failure is treated
    conservatively. An HTTP error response does not certify a free attempt.

    Args:
        request: Fully rendered request; runner must persist intent first.

    Returns:
        Unparsed bytes or a safe failure category with unknown delivery.
    """
    endpoint = urlsplit(request.route.endpoint)
    connection = http.client.HTTPSConnection(
        endpoint.netloc, timeout=request.timeout_seconds
    )
    try:
        connection.request(
            "POST",
            endpoint.path,
            body=request.body,
            headers={
                "Authorization": f"Bearer {request.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        return HttpResponse(status=response.status, body=response.read())
    except TimeoutError:
        return TransportFailure(reason="timeout", delivery="unknown")
    except OSError, http.client.HTTPException:
        return TransportFailure(reason="network", delivery="unknown")
    finally:
        connection.close()


def select_model_attempt(request: HttpRequest, transport: HttpTransport) -> HttpResult:
    """Call the injected transport once, preserving unknown delivery on failure.

    Args:
        request: Rendered request whose intent has already been persisted.
        transport: Explicit single-attempt capability, normally select_http_response.

    Returns:
        Unparsed response/failure; never a parsed judgment or automatic retry.
    """
    try:
        return transport(request)
    except TimeoutError:
        return TransportFailure(reason="timeout", delivery="unknown")
    except OSError:
        return TransportFailure(reason="network", delivery="unknown")


class _WireMessage(TypedDict, total=False):
    """Relevant provider message fields; unknown provider metadata is preserved raw.

    Attributes:
        content: Text message, or None when absent.
        refusal: Explicit refusal text, independent of source response content.
    """

    content: str | None
    refusal: str | None


class _WireChoice(TypedDict, total=False):
    """One choice at the provider boundary.

    Attributes:
        message: Optional returned message.
        finish_reason: Unnormalized finish observation, or None when missing.
    """

    message: _WireMessage | None
    finish_reason: str | None


class _WireReasoning(TypedDict, total=False):
    """Optional output-token details.

    Attributes:
        reasoning_tokens: Strict nonnegative reasoning-token subset when supplied.
    """

    reasoning_tokens: Annotated[int, Field(ge=0, strict=True)] | None


class _WireUsage(TypedDict, total=False):
    """Optional billing fields; malformed observations never default to zero.

    Attributes:
        prompt_tokens: Input usage, or None when not supplied.
        completion_tokens: Output usage, or None when not supplied.
        completion_tokens_details: Optional reasoning-token detail.
    """

    prompt_tokens: Annotated[int, Field(ge=0, strict=True)] | None
    completion_tokens: Annotated[int, Field(ge=0, strict=True)] | None
    completion_tokens_details: _WireReasoning | None


class _WireResponse(TypedDict, total=False):
    """Provider envelope adapter; full unfiltered bytes live in the raw artifact.

    Attributes:
        choices: Returned choices; exactly one is required for usable content.
        usage: Optional billing observation.
        model: Reported served identity, not evidence of exact historical matching.
        id: Provider response identifier, if present.
    """

    choices: tuple[_WireChoice, ...]
    usage: _WireUsage | None
    model: str | None
    id: str | None


def create_provider_observation(response: HttpResponse) -> ProviderObservation:
    """Parse already-persisted bytes without repairing output or inferring usage.

    Args:
        response: Exact HTTP response whose raw evidence is durably saved first.

    Returns:
        Explicit content, finish/refusal and usage observations; malformed bodies
        remain unknown and never become benign predictions or zero-cost bills.
    """
    try:
        _ = json.loads(response.body, object_pairs_hook=create_unique_json_object)
        wire = TypeAdapter(_WireResponse).validate_json(response.body)
    except ValueError, InvalidValueError:
        return ProviderObservation(
            content="",
            finish="unknown",
            refused=False,
            usage=None,
            served_model=None,
            response_identifier=None,
        )
    choices = wire.get("choices", ())
    choice = choices[0] if len(choices) == 1 else None
    message = choice.get("message") if choice else None
    finish: Literal["complete", "truncated", "unknown"] = "unknown"
    refused = bool(
        (message and message.get("refusal") is not None)
        or (choice and choice.get("finish_reason") == "content_filter")
    )
    if (
        HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES
        and choice
        and message
        and message.get("content") is not None
    ):
        if choice.get("finish_reason") == "stop":
            finish = "complete"
        elif choice.get("finish_reason") == "length":
            finish = "truncated"
    usage = None
    wire_usage = wire.get("usage")
    if wire_usage is not None:
        details = wire_usage.get("completion_tokens_details")
        usage = TokenUsage(
            prompt_tokens=wire_usage.get("prompt_tokens"),
            completion_tokens=wire_usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens") if details else None,
        )
    return ProviderObservation(
        content=message.get("content") or "" if message else "",
        finish=finish,
        refused=refused,
        usage=usage,
        served_model=wire.get("model"),
        response_identifier=wire.get("id"),
    )
