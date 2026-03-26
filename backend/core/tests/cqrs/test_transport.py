"""Тесты TransportRequest и TransportResponse."""

from core.utils.cqrs.transport import TransportRequest, TransportResponse

from .conftest import PingMessage, PingResult


class TestTransportRequestSerialize:
    """Тесты TransportRequest.serialize."""

    def test_creates_request_id(self, ping_message: PingMessage):
        request: TransportRequest = TransportRequest.serialize(
            message=ping_message,
        )
        assert request.request_id
        assert len(request.request_id) == 32

    def test_sets_message_class_name(self, ping_message: PingMessage):
        request: TransportRequest = TransportRequest.serialize(
            message=ping_message,
        )
        assert request.message_class_name == "PingMessage"

    def test_serializes_payload(self, ping_message: PingMessage):
        request: TransportRequest = TransportRequest.serialize(
            message=ping_message,
        )
        assert request.payload == {"value": "hello"}

    def test_default_timeout(self, ping_message: PingMessage):
        request: TransportRequest = TransportRequest.serialize(
            message=ping_message,
        )
        assert request.timeout == 30.0

    def test_custom_timeout(self, ping_message: PingMessage):
        request: TransportRequest = TransportRequest.serialize(
            message=ping_message,
            timeout=10.0,
        )
        assert request.timeout == 10.0

    def test_unique_request_ids(self, ping_message: PingMessage):
        r1: TransportRequest = TransportRequest.serialize(message=ping_message)
        r2: TransportRequest = TransportRequest.serialize(message=ping_message)
        assert r1.request_id != r2.request_id


class TestTransportRequestDeserialize:
    """Тесты TransportRequest.deserialize."""

    def test_restores_message(self, ping_request: TransportRequest):
        message = ping_request.deserialize()
        assert isinstance(message, PingMessage)
        assert message.value == "hello"

    def test_unknown_message_returns_none(self):
        request = TransportRequest(
            request_id="abc",
            message_class_name="UnknownMessage",
            payload={},
        )
        assert request.deserialize() is None


class TestTransportResponseSerialize:
    """Тесты TransportResponse.serialize."""

    def test_success_response(self, ping_request: TransportRequest):
        result = PingResult(pong="world")
        response: TransportResponse = TransportResponse.serialize(
            request=ping_request,
            result=result,
        )
        assert response.success is True
        assert response.payload == {"pong": "world"}
        assert response.error is None
        assert response.error_type is None
        assert response.message_class_name == "PingMessage"

    def test_error_response(self, ping_request: TransportRequest):
        response: TransportResponse = TransportResponse.serialize(
            request=ping_request,
            exception=ValueError("bad value"),
        )
        assert response.success is False
        assert response.error == "bad value"
        assert response.error_type == "ValueError"
        assert response.payload is None

    def test_none_result(self, ping_request: TransportRequest):
        response: TransportResponse = TransportResponse.serialize(
            request=ping_request,
            result=None,
        )
        assert response.success is True
        assert response.payload is None


class TestTransportResponseDeserialize:
    """Тесты TransportResponse.deserialize."""

    def test_restores_result(self, ping_response: TransportResponse):
        result = ping_response.deserialize()
        assert isinstance(result, PingResult)
        assert result.pong == "hello"

    def test_none_payload_returns_none(self, ping_request: TransportRequest):
        response = TransportResponse.serialize(
            request=ping_request,
            result=None,
        )
        assert response.deserialize() is None
