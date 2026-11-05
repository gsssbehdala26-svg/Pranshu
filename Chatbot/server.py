import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 81_920
MAX_MESSAGE_LENGTH = 4_000
MAX_CONVERSATION_LENGTH = 20_000
DEFAULT_MODEL = "gpt-4o-mini"


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def load_local_environment():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if not match or match.group(1) in os.environ:
            continue
        value = match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[match.group(1)] = value


def ai_config():
    api_key = os.environ.get("AQ.Ab8RN6JwyHNXGzgyHii_YY2MLWp8pBmBzjn0MGM2Ebf0o9esww", "").strip()
    model = os.environ.get("gemini-4-argon", DEFAULT_MODEL).strip()
    configured = bool(api_key) and not api_key.lower().startswith("your_")
    return api_key, model, configured


def request_ai(messages, api_key, model):
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful, general-purpose AI assistant. Answer clearly and thoughtfully "
                    "across a wide range of topics. Be honest about uncertainty and limitations, do not "
                    "claim to have live information unless it is provided, and advise users to verify "
                    "important medical, legal, financial, or safety decisions with a qualified source."
                ),
            },
            *messages,
        ],
    }
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read(1_048_577).decode("utf-8"))
    except HTTPError as error:
        if error.code in (401, 403):
            raise RequestError(503, "The AI provider rejected this API key or its permissions. Check your API key and account access.") from error
        if error.code == 404:
            raise RequestError(503, "The selected AI model was not found or is unavailable to this account. Check OPENAI_MODEL in .env.") from error
        if error.code == 429:
            raise RequestError(503, "The AI service is busy or its usage limit was reached. Please try again later.") from error
        if error.code >= 500:
            raise RequestError(502, "The AI service is temporarily unavailable. Please try again shortly.") from error
        raise RequestError(502, "The AI service could not process this request.") from error
    except (URLError, TimeoutError) as error:
        raise RequestError(502, "Could not reach the AI service. Check the server connection and try again.") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RequestError(502, "The AI service returned an invalid response.") from error

    try:
        reply = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RequestError(502, "The AI service returned an incomplete response.") from error
    if not isinstance(reply, str) or not reply.strip():
        raise RequestError(502, "The AI service returned an empty response. Please try again.")
    return reply.strip()


class RequestHandler(BaseHTTPRequestHandler):
    def send_json(self, status, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise RequestError(400, "Invalid request length.") from error
        if length < 1 or length > MAX_BODY_BYTES:
            raise RequestError(413, "Request body is empty or too large.")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestError(400, "Invalid request body.") from error

    def do_GET(self):
        pathname = urlparse(self.path).path
        if pathname == "/api/chat-status":
            _, _, configured = ai_config()
            message = "AI assistant is ready." if configured else "Add OPENAI_API_KEY to .env and restart the server."
            self.send_json(200, {"configured": configured, "message": message})
            return
        if pathname not in ("/", "/chatbot.html"):
            self.send_json(404, {"error": "Page not found."})
            return
        try:
            content = (ROOT / "chatbot.html").read_bytes()
        except OSError as error:
            raise RequestError(500, "Could not read chatbot.html.") from error
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self.send_json(404, {"error": "API route not found."})
            return
        try:
            self.chat()
        except RequestError as error:
            self.send_json(error.status, {"error": str(error)})

    def chat(self):
        api_key, model, configured = ai_config()
        if not configured:
            raise RequestError(503, "AI is not configured. Add OPENAI_API_KEY to .env and restart the server.")
        if not model or len(model) > 100 or any(ord(char) < 32 for char in model):
            raise RequestError(503, "OPENAI_MODEL is invalid. Check the model name in .env.")

        body = self.read_json()
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list) or not 1 <= len(messages) <= 16:
            raise RequestError(400, "Provide between 1 and 16 chat messages.")

        conversation = []
        total_characters = 0
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
                raise RequestError(400, "Chat messages must have a user or assistant role.")
            content = message.get("content")
            if not isinstance(content, str) or not 0 < len(content.strip()) <= MAX_MESSAGE_LENGTH:
                raise RequestError(400, "Each chat message must contain between 1 and 4000 characters.")
            total_characters += len(content)
            if total_characters > MAX_CONVERSATION_LENGTH:
                raise RequestError(413, "This conversation is too long. Start a new chat and try again.")
            conversation.append({"role": message["role"], "content": content.strip()})
        if conversation[-1]["role"] != "user":
            raise RequestError(400, "The latest chat message must be from the user.")

        reply = request_ai(conversation, api_key, model)
        self.send_json(200, {"reply": reply})

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")


if __name__ == "__main__":
    load_local_environment()
    port = int(os.environ.get("PORT", "4174"))
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"AI Chat is running at http://localhost:{port}/chatbot.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
