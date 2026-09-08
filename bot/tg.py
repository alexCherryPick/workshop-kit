"""tg.py — тонкий транспорт API мессенджера. Владелец — T1 (D09, глава §5).

Обязательства формы (проверяются грепом в selfcheck T1 и на гейте T6):
  * НОЛЬ политики: здесь нет ни порогов, ни пределов ретраев, ни правил «кому и когда отвечать» —
    это решают вызывающие (T3 — ответы человеку, T4 — ответ о находке секрета, T5 — алярм и
    heartbeat-замер). В модуле нет ни одного числового литерала-настройки.
  * ОДИН хост (API_HOST). Адресат каждого сообщения — параметр вызова (chat_id), не константа.
  * Никаких ретраев внутри: ошибка транспорта поднимается как TransportError с текстом БЕЗ токена.
  * Стандартная библиотека, Python 3.9.

Три метода: get_updates, send_message, answer_callback_query.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["API_HOST", "TransportError", "Transport", "default_opener"]

API_HOST = "api.telegram.org"          # единственный хост транспорта (§5: «число хостов — один»)
_SCHEME = "https"
_TOKEN_MASK = "<token>"


class TransportError(RuntimeError):
    """Ошибка транспорта: сеть, не-JSON ответ, ok=false. Текст никогда не содержит токен."""

    def __init__(self, message, method=None, description=None, error_code=None):
        RuntimeError.__init__(self, message)
        self.method = method
        self.description = description
        self.error_code = error_code


def default_opener(url, data_bytes, timeout_s):
    """Открыватель по умолчанию: один POST application/json. Возвращает байты тела ответа.
    HTTP-ошибка с телом (например, 400 от API) возвращает тело — разбор ok/false делает Transport."""
    req = urllib.request.Request(url, data=data_bytes, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.read()
        except Exception:  # noqa: BLE001 — тело недоступно: отдаём ошибку выше
            raise TransportError("http error %s" % e.code)
    except urllib.error.URLError as e:
        raise TransportError("network error: %s" % _mask(str(e.reason), None))


def _mask(text, token):
    if token and token in text:
        return text.replace(token, _TOKEN_MASK)
    return text


class Transport(object):
    """Адаптер API. token — токен бота; timeout_s — таймаут одного HTTP-вызова (значение даёт
    вызывающий из конфига комплекта, здесь дефолта нет); opener — инъекция для тестов."""

    def __init__(self, token, timeout_s, opener=None, host=API_HOST):
        if not token:
            raise TransportError("token is empty")
        self._token = token
        self._timeout_s = timeout_s
        self._opener = opener or default_opener
        self._host = host
        self.last_url = None

    # --- служебное
    def url_for(self, method):
        return "%s://%s/bot%s/%s" % (_SCHEME, self._host, self._token, method)

    def call(self, method, params):
        """Один вызов метода API. Возвращает поле result. ok=false → TransportError."""
        clean = dict((k, v) for k, v in params.items() if v is not None)
        data = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        url = self.url_for(method)
        self.last_url = _mask(url, self._token)
        try:
            raw = self._opener(url, data, self._timeout_s)
        except TransportError as e:
            raise TransportError("%s: %s" % (method, _mask(str(e), self._token)), method=method)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise TransportError("%s: non-json response (%s)" % (method, e), method=method)
        if not isinstance(payload, dict) or "ok" not in payload:
            raise TransportError("%s: malformed response envelope" % method, method=method)
        if payload["ok"] is not True:
            raise TransportError(
                "%s: api error %s: %s" % (method, payload.get("error_code"), _mask(str(payload.get("description")), self._token)),
                method=method,
                description=payload.get("description"),
                error_code=payload.get("error_code"),
            )
        return payload.get("result")

    # --- три метода API
    def get_updates(self, offset=None, limit=None, timeout_s=None, allowed_updates=None):
        return self.call("getUpdates", {
            "offset": offset,
            "limit": limit,
            "timeout": timeout_s,
            "allowed_updates": allowed_updates,
        })

    def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, disable_notification=None):
        return self.call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "reply_to_message_id": reply_to_message_id,
            "disable_notification": disable_notification,
        })

    def answer_callback_query(self, callback_query_id, text=None, show_alert=None):
        return self.call("answerCallbackQuery", {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        })
