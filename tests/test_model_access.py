import http.client
import json
from typing import assert_type

import pytest
from pydantic import SecretStr, ValidationError

from safety_judge.errors import ConfigurationError, InvalidValueError
from safety_judge.judging import (
    FrozenRubric,
    JudgeMessage,
    JudgeRole,
    create_judge_request,
)
from safety_judge.model_access import (
    GenerationParameters,
    HttpRequest,
    HttpResponse,
    ModelRole,
    ModelRoute,
    TransportFailure,
    create_http_request,
    create_judge_http_request,
    create_model_route,
    create_ordinal_response_format,
    create_provider_api_key,
    create_provider_observation,
    create_unsupported_output_mode,
    select_http_response,
    select_model_attempt,
)
from safety_judge.settings import ApplicationSettings, select_application_settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> ApplicationSettings:
    monkeypatch.setenv("SAFETY_JUDGE_DEEPINFRA_API_KEY", "synthetic-di-secret")
    monkeypatch.setenv("SAFETY_JUDGE_HUGGINGFACE_API_KEY", "synthetic-hf-secret")
    return select_application_settings(environment_file_path=None)


@pytest.fixture
def api_key() -> SecretStr:
    return SecretStr("synthetic-di-secret")


@pytest.fixture
def parameters() -> GenerationParameters:
    return GenerationParameters(
        maximum_output_tokens=512, temperature=0, timeout_seconds=30
    )


@pytest.fixture
def outbound_request(
    api_key: SecretStr, parameters: GenerationParameters
) -> HttpRequest:
    return create_http_request(
        route=create_model_route(JudgeRole.QWEN_THIRTY_TWO),
        messages=(JudgeMessage(role="user", content="synthetic visible text"),),
        api_key=api_key,
        parameters=parameters,
    )


@pytest.mark.parametrize(
    ("role", "provider", "model", "precision"),
    [
        (
            JudgeRole.GEMMA_ONE,
            "huggingface",
            "google/gemma-3-1b-it:featherless-ai",
            "BF16",
        ),
        (JudgeRole.GEMMA_TWENTY_SEVEN, "deepinfra", "google/gemma-3-27b-it", "FP8"),
        (
            JudgeRole.LLAMA_EIGHT,
            "deepinfra",
            "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
            "FP8",
        ),
        (JudgeRole.QWEN_THIRTY_TWO, "deepinfra", "Qwen/Qwen3-32B", "FP8"),
        (
            "paraphraser",
            "deepinfra",
            "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
            "FP8",
        ),
        ("reviewer", "deepinfra", "anthropic/claude-sonnet-4-6", "unknown"),
    ],
)
def test_routes_preserve_exact_roster_without_automatic_fallback(
    role: ModelRole,
    provider: str,
    model: str,
    precision: str,
) -> None:
    route = create_model_route(role)
    assert route.provider == provider
    assert route.model == model
    assert route.precision == precision
    assert route.observed_on == "2026-10-17"
    assert route.runtime_verified is False


def test_qwen_request_disables_thinking_without_unverified_reasoning_effort(
    outbound_request: HttpRequest,
) -> None:
    payload = json.loads(outbound_request.body)
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in payload
    assert payload["n"] == 1
    assert payload["stream"] is False
    assert payload["max_tokens"] == 512
    assert payload["top_p"] == 1


def test_secret_is_excluded_from_request_serialization_and_representations(
    outbound_request: HttpRequest,
) -> None:
    assert "synthetic-di-secret" not in outbound_request.model_dump_json()
    assert "synthetic-di-secret" not in repr(outbound_request)
    assert "synthetic-di-secret" not in str(outbound_request)
    assert "Authorization" not in outbound_request.model_dump_json()
    assert isinstance(outbound_request.api_key, SecretStr)


def test_blinded_judge_message_adapter_preserves_the_owning_request(
    parameters: GenerationParameters,
) -> None:
    judge = create_judge_request(
        "synthetic prompt",
        "synthetic generation",
        FrozenRubric(version="test", text="synthetic rubric", source="test fixture"),
    )
    adapted = create_judge_http_request(
        request=judge,
        route=create_model_route(JudgeRole.GEMMA_ONE),
        api_key=SecretStr("synthetic-hf-secret"),
        parameters=parameters,
    )
    payload = json.loads(adapted.body)
    assert payload["messages"] == [message.model_dump() for message in judge.messages]
    assert "rubric_sha256" not in payload
    assert "chat_template_kwargs" not in payload
    assert adapted.api_key.get_secret_value() == "synthetic-hf-secret"


def test_missing_selected_provider_credential_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_JUDGE_DEEPINFRA_API_KEY", "only-this-provider")
    settings = select_application_settings(environment_file_path=None)
    with pytest.raises(ConfigurationError, match="huggingface"):
        _ = create_provider_api_key(settings, create_model_route(JudgeRole.GEMMA_ONE))


def test_one_attempt_returns_raw_bytes_before_any_provider_parsing(
    outbound_request: HttpRequest,
) -> None:
    calls: list[HttpRequest] = []
    raw = HttpResponse(status=200, body=b"not JSON")

    def select_fake_response(outbound: HttpRequest) -> HttpResponse:
        calls.append(outbound)
        return raw

    result = select_model_attempt(outbound_request, select_fake_response)
    _ = assert_type(result, HttpResponse | TransportFailure)
    assert result is raw
    assert calls == [outbound_request]


@pytest.mark.parametrize("failure", [TimeoutError, OSError])
def test_network_failures_have_unknown_delivery_and_no_retry_or_secret_text(
    outbound_request: HttpRequest,
    failure: type[OSError],
) -> None:
    calls: list[HttpRequest] = []

    def select_failed_response(outbound: HttpRequest) -> HttpResponse:
        calls.append(outbound)
        message = "synthetic-di-secret must not enter evidence"
        raise failure(message)

    result = select_model_attempt(outbound_request, select_failed_response)
    assert isinstance(result, TransportFailure)
    assert result.delivery == "unknown"
    assert "synthetic-di-secret" not in result.model_dump_json()
    assert calls == [outbound_request]


def test_certified_not_delivered_is_preserved_without_retry(
    outbound_request: HttpRequest,
) -> None:
    failure = TransportFailure(reason="network", delivery="not_delivered")
    result = select_model_attempt(outbound_request, lambda _request: failure)
    assert result is failure


@pytest.mark.parametrize(
    ("finish_reason", "expected_finish", "refused"),
    [
        ("stop", "complete", False),
        ("length", "truncated", False),
        ("content_filter", "unknown", True),
        ("tool_calls", "unknown", False),
        (None, "unknown", False),
    ],
)
def test_provider_finish_and_usage_are_explicit_observations(
    finish_reason: str | None,
    expected_finish: str,
    *,
    refused: bool,
) -> None:
    body = json.dumps(
        {
            "id": "synthetic-response",
            "model": "reported-model",
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": '{"ordinal": 4}'},
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 12,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        }
    ).encode()
    observation = create_provider_observation(HttpResponse(status=200, body=body))
    assert observation.finish == expected_finish
    assert observation.refused is refused
    assert observation.content == '{"ordinal": 4}'
    assert observation.served_model == "reported-model"
    assert observation.response_identifier == "synthetic-response"
    assert observation.usage is not None
    assert observation.usage.prompt_tokens == 50
    assert observation.usage.completion_tokens == 12
    assert observation.usage.reasoning_tokens == 3


def test_explicit_judge_refusal_does_not_depend_on_source_text_matching() -> None:
    body = (
        b'{"choices":[{"finish_reason":"stop",'
        b'"message":{"refusal":"declined","content":""}}]}'
    )
    observation = create_provider_observation(HttpResponse(status=200, body=body))
    assert observation.refused
    assert observation.usage is None


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not-json",
        b"{}",
        b'{"choices":[]}',
        b'{"choices":[],"choices":[]}',
        b'{"usage":{"prompt_tokens":true}}',
    ],
)
def test_empty_malformed_or_missing_usage_never_becomes_free_or_complete(
    body: bytes,
) -> None:
    observation = create_provider_observation(HttpResponse(status=200, body=body))
    assert observation.finish == "unknown"
    assert observation.usage is None


@pytest.mark.parametrize("status", [301, 401, 429, 500])
def test_http_errors_and_redirects_never_produce_complete_judgments(
    status: int,
) -> None:
    body = (
        b'{"choices":[{"finish_reason":"stop",'
        b'"message":{"content":"{\\"ordinal\\": 4}"}}]}'
    )
    observation = create_provider_observation(HttpResponse(status=status, body=body))
    assert observation.finish == "unknown"


def test_changed_route_cannot_silently_replace_the_selected_model(
    api_key: SecretStr,
    parameters: GenerationParameters,
) -> None:
    original = create_model_route(JudgeRole.GEMMA_ONE)
    changed = ModelRoute.model_validate(
        {**original.model_dump(), "model": "replacement"}
    )
    with pytest.raises(InvalidValueError, match="roster"):
        _ = create_http_request(
            route=changed,
            messages=(JudgeMessage(role="user", content="test"),),
            api_key=api_key,
            parameters=parameters,
        )


@pytest.mark.parametrize("value", [0, -1, True])
def test_missing_or_invalid_output_limits_are_not_defaulted(value: int) -> None:
    with pytest.raises(ValidationError):
        _ = GenerationParameters(
            maximum_output_tokens=value, temperature=0, timeout_seconds=30
        )


class FakeHttpResponse:
    def __init__(self, status: int) -> None:
        """Retain a synthetic response status.

        Args:
            status: HTTP status to expose without network activity.
        """
        super().__init__()
        self.status = status

    def read(self) -> bytes:
        return b"unparsed response"


class FakeHttpsConnection:
    def __init__(self, *, status: int, failure: OSError | None = None) -> None:
        """Record exactly the calls made by the real standard-library adapter.

        Args:
            status: Synthetic HTTP status.
            failure: Optional injected transport failure.
        """
        super().__init__()
        self.status = status
        self.failure = failure
        self.calls: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.closed = False

    def request(
        self, method: str, path: str, *, body: bytes, headers: dict[str, str]
    ) -> None:
        self.calls.append((method, path, body, headers))
        if self.failure is not None:
            raise self.failure

    def getresponse(self) -> FakeHttpResponse:
        return FakeHttpResponse(self.status)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("status", [200, 301, 429])
def test_standard_transport_posts_once_and_never_follows_redirects(
    outbound_request: HttpRequest,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    connection = FakeHttpsConnection(status=status)
    hosts: list[tuple[str, float]] = []

    def create_fake_connection(host: str, *, timeout: float) -> FakeHttpsConnection:
        hosts.append((host, timeout))
        return connection

    monkeypatch.setattr(http.client, "HTTPSConnection", create_fake_connection)
    result = select_http_response(outbound_request)
    assert isinstance(result, HttpResponse)
    assert result.status == status
    assert result.body == b"unparsed response"
    assert hosts == [("api.deepinfra.com", 30)]
    assert len(connection.calls) == 1
    method, path, body, headers = connection.calls[0]
    assert method == "POST"
    assert path == "/v1/openai/chat/completions"
    assert body == outbound_request.body
    assert headers["Authorization"] == "Bearer synthetic-di-secret"
    assert connection.closed


def test_standard_transport_timeout_retains_unknown_delivery_and_closes_connection(
    outbound_request: HttpRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = "synthetic-di-secret was in the outbound headers"
    connection = FakeHttpsConnection(status=200, failure=TimeoutError(message))

    def create_fake_connection(_host: str, *, timeout: float) -> FakeHttpsConnection:
        assert timeout == 30
        return connection

    monkeypatch.setattr(http.client, "HTTPSConnection", create_fake_connection)
    result = select_http_response(outbound_request)
    assert isinstance(result, TransportFailure)
    assert result.reason == "timeout"
    assert result.delivery == "unknown"
    assert "synthetic-di-secret" not in result.model_dump_json()
    assert len(connection.calls) == 1
    assert connection.closed


def test_standard_provider_metadata_is_accepted_without_losing_raw_evidence() -> None:
    body = json.dumps(
        {
            "id": "response",
            "object": "chat.completion",
            "created": 1,
            "model": "reported",
            "system_fingerprint": "advertised-only",
            "choices": [
                {
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"ordinal":4}',
                        "tool_calls": None,
                    },
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        }
    ).encode()
    raw = HttpResponse(status=200, body=body)
    observation = create_provider_observation(raw)
    assert observation.finish == "complete"
    assert observation.usage is not None
    assert observation.usage.completion_tokens == 2
    assert raw.body == body


@pytest.mark.parametrize("role", [JudgeRole.GEMMA_ONE, JudgeRole.QWEN_THIRTY_TWO])
def test_parsed_settings_helper_selects_only_the_explicit_provider(
    settings: ApplicationSettings,
    role: ModelRole,
) -> None:
    route = create_model_route(role)
    key = create_provider_api_key(settings, route)
    expected = (
        "synthetic-hf-secret" if role is JudgeRole.GEMMA_ONE else "synthetic-di-secret"
    )
    assert key.get_secret_value() == expected


@pytest.mark.parametrize("empty", ["", "  "])
def test_pure_rendering_rejects_an_explicit_empty_secret(
    parameters: GenerationParameters,
    empty: str,
) -> None:
    with pytest.raises(ConfigurationError, match="empty"):
        _ = create_http_request(
            route=create_model_route(JudgeRole.QWEN_THIRTY_TWO),
            messages=(JudgeMessage(role="user", content="synthetic"),),
            api_key=SecretStr(empty),
            parameters=parameters,
        )


def test_simulated_rendering_never_constructs_environment_settings(
    parameters: GenerationParameters,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def create_forbidden_settings(
        _self: ApplicationSettings, **_arguments: object
    ) -> None:
        pytest.fail("pure rendering attempted to construct process settings")

    monkeypatch.setattr(ApplicationSettings, "__init__", create_forbidden_settings)
    rendered = create_http_request(
        route=create_model_route(JudgeRole.GEMMA_ONE),
        messages=(JudgeMessage(role="user", content="synthetic offline text"),),
        api_key=SecretStr("synthetic-offline-only"),
        parameters=parameters,
    )
    assert rendered.api_key.get_secret_value() == "synthetic-offline-only"


@pytest.mark.parametrize("role", list(JudgeRole))
def test_same_strict_schema_is_added_without_changing_judge_visible_messages(
    role: JudgeRole, api_key: SecretStr, parameters: GenerationParameters
) -> None:
    messages = (JudgeMessage(role="user", content="Frozen visible JSON instruction"),)
    request = create_http_request(
        route=create_model_route(role),
        messages=messages,
        api_key=api_key,
        parameters=parameters,
        output_mode="json_schema",
    )
    payload = json.loads(request.body)
    assert payload["messages"] == [item.model_dump() for item in messages]
    assert payload["response_format"] == create_ordinal_response_format("json_schema")
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["ordinal"]
    assert schema["properties"]["ordinal"]["type"] == "integer"
    assert schema["properties"]["ordinal"]["minimum"] == 1
    assert schema["properties"]["ordinal"]["maximum"] == 5


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (
            400,
            {"error": {"message": "json_schema is not supported by this model"}},
            True,
        ),
        (422, {"error": {"message": "Unsupported response_format: json_object"}}, True),
        (400, {"error": {"message": "Cold model unavailable"}}, False),
        (
            400,
            {"error": {"message": "unsupported keyword minimum in json_schema"}},
            False,
        ),
        (400, {"error": {"message": "Invalid schema for json_schema"}}, False),
        (
            400,
            {
                "error": {"message": "unsupported image format"},
                "response_format": "json_schema",
            },
            False,
        ),
        (402, {"error": {"message": "json_schema is not supported"}}, False),
        (200, {"error": {"message": "json_schema is not supported"}}, False),
    ],
)
def test_mode_fallback_requires_explicit_format_type_rejection(
    status: int, payload: dict[str, object], *, expected: bool
) -> None:
    assert (
        create_unsupported_output_mode(
            HttpResponse(status=status, body=json.dumps(payload).encode())
        )
        is expected
    )
