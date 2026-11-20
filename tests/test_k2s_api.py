"""Klient oficiálního API Keep2Share: jen smyšlené odpovědi přes httpx.MockTransport (žádná síť)."""
import json

import httpx
import pytest

from viddown.resolvers import k2s


def client(handler):
    return k2s.Client(transport=httpx.MockTransport(handler), base="https://example.test/api/v2")


def reply(data, status=200):
    return lambda req: httpx.Response(status, json=data)


def test_file_id_from_url():
    assert k2s.file_id_of("https://k2s.cc/file/571354fd80f67/hj4274.rar") == "571354fd80f67"
    assert k2s.file_id_of("https://keep2share.cc/file/abc123") == "abc123"
    assert k2s.file_id_of("https://example.com/file/abc123") is None
    assert k2s.file_id_of("https://k2s.cc/") is None


def test_get_url_success_returns_link_and_sends_only_file_id_when_anonymous():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"status": "success", "url": "https://dl.example.test/x"})

    assert client(handler).get_url("abc") == "https://dl.example.test/x"
    assert seen["body"] == {"file_id": "abc"}


def test_auth_token_is_sent_only_when_given():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"status": "success", "url": "https://dl.example.test/x"})

    c = client(handler)
    c.get_url("abc")
    c.get_url("abc", auth_token="tok")
    assert "auth_token" not in seen[0] and seen[1]["auth_token"] == "tok"


@pytest.mark.parametrize("code,kind", [
    (41, "wait"), (30, "captcha"), (31, "captcha"), (33, "captcha"),
    (20, "gone"), (8, "gone"), (1, "limit_daily"), (2, "limit_daily"),
    (3, "unsupported"), (7, "unsupported"), (999, "other"),
])
def test_error_codes_map_to_kinds(code, kind):
    c = client(reply({"status": "error", "errorCode": code, "message": "x"}))
    with pytest.raises(k2s.K2SError) as e:
        c.get_url("abc")
    assert e.value.kind == kind and e.value.code == code


def test_code_field_name_is_also_understood():
    c = client(reply({"status": "error", "code": 41, "message": "wait"}))
    with pytest.raises(k2s.K2SError) as e:
        c.get_url("abc")
    assert e.value.kind == "wait"


def test_http_429_is_rate_limit_not_a_captcha():
    c = client(lambda req: httpx.Response(429, json={}))
    with pytest.raises(k2s.K2SError) as e:
        c.get_url("abc")
    assert e.value.kind == "rate"


def test_network_error_is_retryable_kind():
    def handler(req):
        raise httpx.ConnectError("nedostupné")

    with pytest.raises(k2s.K2SError) as e:
        client(handler).get_url("abc")
    assert e.value.kind == "network"


def test_captcha_flow_sends_challenge_and_response_back():
    seen = []

    def handler(req):
        if req.url.path.endswith("/requestCaptcha"):
            return httpx.Response(200, json={"status": "success", "challenge": "ch1", "captcha_url": "https://x"})
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"status": "success", "url": "https://dl.example.test/x"})

    c = client(handler)
    ch = c.request_captcha()
    assert ch.challenge == "ch1" and ch.captcha_url == "https://x"
    c.get_url("abc", captcha=ch, captcha_response="odpoved")
    assert seen[0]["captcha_challenge"] == "ch1" and seen[0]["captcha_response"] == "odpoved"


def test_login_returns_token():
    c = client(reply({"status": "success", "auth_token": "t123"}))
    assert c.login("user", "pass") == "t123"


def test_captcha_image_is_fetched_with_id():
    def handler(req):
        assert req.url.params["id"] == "ch1"
        return httpx.Response(200, content=b"\x89PNG-fake")

    assert client(handler).captcha_image(k2s.Challenge("ch1")) == b"\x89PNG-fake"
