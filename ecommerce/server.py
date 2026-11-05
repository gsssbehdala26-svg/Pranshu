import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 16_384
MAX_CHAT_BODY_BYTES = 81_920
ORDER_LOCK = threading.Lock()
ORDERS = {}
PRODUCTS = {
    "linen-throw": {"name": "Everyday Linen Throw", "price": 88},
    "ceramic-vase": {"name": "Form No. 2 Vase", "price": 54},
    "weekend-tote": {"name": "The Weekend Tote", "price": 68},
    "stoneware-cup": {"name": "Morning Stoneware Cup", "price": 32},
    "market-basket": {"name": "Sunday Market Basket", "price": 74},
    "table-lamp": {"name": "Soft Light Table Lamp", "price": 126},
    "face-oil": {"name": "Daily Ritual Face Oil", "price": 46},
    "linen-napkins": {"name": "Linen Table Napkins", "price": 38},
}
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico"}


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


def razorpay_config():
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    configured = key_id.startswith("rzp_") and bool(key_secret) and "REPLACE" not in key_id and "REPLACE" not in key_secret
    return key_id, key_secret, configured


def ai_config():
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    configured = bool(api_key) and not api_key.lower().startswith("your_")
    return api_key, model, configured


def ai_chat_request(messages, api_key, model):
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
            raise RequestError(503, "The AI provider rejected the API key. Check OPENAI_API_KEY in .env.") from error
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


def razorpay_request(endpoint, method, data, key_id, key_secret):
    auth = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(
        f"https://api.razorpay.com/v1/{endpoint}",
        data=body,
        method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            message = payload.get("error", {}).get("description", "Razorpay could not complete the request.")
        except (ValueError, AttributeError):
            message = "Razorpay could not complete the request."
        raise RequestError(502, message) from error
    except (URLError, TimeoutError) as error:
        raise RequestError(502, "Could not reach Razorpay. Check the server connection and try again.") from error


def valid_text(value, max_length):
    return isinstance(value, str) and 0 < len(value.strip()) <= max_length


def calculate_order(body):
    if not isinstance(body, dict):
        raise RequestError(400, "Invalid order details.")
    customer = body.get("customer")
    if not isinstance(customer, dict):
        raise RequestError(400, "Please provide delivery and contact details.")
    if not all(
        valid_text(customer.get(field), limit)
        for field, limit in (("firstName", 80), ("lastName", 80), ("address", 240), ("city", 100), ("postal", 24))
    ):
        raise RequestError(400, "Please provide valid delivery details.")
    if not isinstance(customer.get("email"), str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", customer["email"]):
        raise RequestError(400, "Please provide a valid email address.")
    if not isinstance(customer.get("phone"), str) or not re.fullmatch(r"\+?[0-9]{10,13}", customer["phone"]):
        raise RequestError(400, "Please provide a valid mobile number.")

    items = body.get("items")
    delivery = body.get("delivery")
    if not isinstance(items, list) or not 1 <= len(items) <= 32:
        raise RequestError(400, "Your bag is empty or contains too many items.")
    if delivery not in ("standard", "express"):
        raise RequestError(400, "Choose a valid delivery speed.")

    quantities = {}
    for item in items:
        if not isinstance(item, dict):
            raise RequestError(400, "Your bag contains an invalid item.")
        product_id = item.get("id")
        quantity = item.get("quantity")
        if not isinstance(product_id, str) or product_id not in PRODUCTS or type(quantity) is not int or not 1 <= quantity <= 20:
            raise RequestError(400, "Your bag contains an invalid item or quantity.")
        quantities[product_id] = quantities.get(product_id, 0) + quantity

    subtotal = sum(PRODUCTS[product_id]["price"] * quantity for product_id, quantity in quantities.items())
    if subtotal > 500_000:
        raise RequestError(400, "Order total is above the checkout limit.")
    shipping = 15 if delivery == "express" else 0 if subtotal >= 100 else 8
    return subtotal, shipping, (subtotal + shipping) * 100


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

    def read_json(self, max_bytes=MAX_BODY_BYTES):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise RequestError(400, "Invalid request length.") from error
        if length < 1 or length > max_bytes:
            raise RequestError(413, "Request body is empty or too large.")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestError(400, "Invalid request body.") from error

    def do_GET(self):
        pathname = urlparse(self.path).path
        if pathname == "/api/config":
            key_id, _, configured = razorpay_config()
            del key_id
            message = "Secure Razorpay test checkout is ready." if configured else "Add your Razorpay test keys to .env, then restart the server."
            self.send_json(200, {"configured": configured, "message": message})
            return
        if pathname == "/api/chat-status":
            _, _, configured = ai_config()
            message = "AI assistant is ready." if configured else "Add your OpenAI API key to .env and restart the server."
            self.send_json(200, {"configured": configured, "message": message})
            return
        try:
            self.serve_file(pathname)
        except RequestError as error:
            self.send_json(error.status, {"error": str(error)})
        except OSError:
            self.send_json(404, {"error": "Page not found."})

    def do_POST(self):
        pathname = urlparse(self.path).path
        try:
            if pathname == "/api/create-order":
                self.create_order()
            elif pathname == "/api/verify-payment":
                self.verify_payment()
            elif pathname == "/api/chat":
                self.chat()
            else:
                self.send_json(404, {"error": "API route not found."})
        except RequestError as error:
            self.send_json(error.status, {"error": str(error)})
        except Exception:
            self.send_json(500, {"error": "The server could not complete the request."})

    def chat(self):
        api_key, model, configured = ai_config()
        if not configured:
            raise RequestError(503, "AI is not configured. Add OPENAI_API_KEY to .env and restart the server.")
        if not model or len(model) > 100 or any(ord(char) < 32 for char in model):
            raise RequestError(503, "OPENAI_MODEL is invalid. Check the model name in .env.")

        body = self.read_json(MAX_CHAT_BODY_BYTES)
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list) or not 1 <= len(messages) <= 16:
            raise RequestError(400, "Provide between 1 and 16 chat messages.")

        conversation = []
        total_characters = 0
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
                raise RequestError(400, "Chat messages must have a user or assistant role.")
            content = message.get("content")
            if not valid_text(content, 4000):
                raise RequestError(400, "Each chat message must contain between 1 and 4000 characters.")
            total_characters += len(content)
            if total_characters > 20_000:
                raise RequestError(413, "This conversation is too long. Start a new chat and try again.")
            conversation.append({"role": message["role"], "content": content.strip()})
        if conversation[-1]["role"] != "user":
            raise RequestError(400, "The latest chat message must be from the user.")

        self.send_json(200, {"reply": ai_chat_request(conversation, api_key, model)})

    def create_order(self):
        key_id, key_secret, configured = razorpay_config()
        if not configured:
            raise RequestError(503, "Razorpay test keys are not configured. Add them to .env and restart the server.")
        body = self.read_json()
        subtotal, shipping, amount = calculate_order(body)
        order = razorpay_request(
            "orders",
            "POST",
            {"amount": amount, "currency": "INR", "receipt": f"forme_{int(time.time())}"},
            key_id,
            key_secret,
        )
        if not isinstance(order.get("id"), str) or order.get("amount") != amount or order.get("currency") != "INR":
            raise RequestError(502, "Razorpay returned an invalid order.")
        with ORDER_LOCK:
            expiry = time.time() - 24 * 60 * 60
            for order_id in [order_id for order_id, saved in ORDERS.items() if saved["created_at"] < expiry]:
                del ORDERS[order_id]
            ORDERS[order["id"]] = {"amount": amount, "currency": "INR", "created_at": time.time()}
            while len(ORDERS) > 1000:
                del ORDERS[next(iter(ORDERS))]
        self.send_json(200, {
            "keyId": key_id,
            "orderId": order["id"],
            "amount": amount,
            "currency": "INR",
            "subtotal": subtotal,
            "shipping": shipping,
            "total": amount // 100,
        })

    def verify_payment(self):
        key_id, key_secret, configured = razorpay_config()
        if not configured:
            raise RequestError(503, "Razorpay keys are not configured.")
        body = self.read_json()
        order_id = body.get("razorpay_order_id") if isinstance(body, dict) else None
        payment_id = body.get("razorpay_payment_id") if isinstance(body, dict) else None
        signature = body.get("razorpay_signature") if isinstance(body, dict) else None
        if not isinstance(order_id, str) or not re.fullmatch(r"order_[A-Za-z0-9]+", order_id):
            raise RequestError(400, "Payment order is invalid.")
        if not isinstance(payment_id, str) or not re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id):
            raise RequestError(400, "Payment ID is invalid.")
        with ORDER_LOCK:
            saved_order = ORDERS.get(order_id)
        if not saved_order:
            raise RequestError(400, "This payment session is invalid or expired. Please start checkout again.")

        expected = hmac.new(key_secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
            raise RequestError(400, "Razorpay payment verification failed.")
        payment = razorpay_request(f"payments/{payment_id}", "GET", None, key_id, key_secret)
        if payment.get("order_id") != order_id or payment.get("amount") != saved_order["amount"] or payment.get("currency") != saved_order["currency"]:
            raise RequestError(400, "Payment details did not match this order.")
        status = payment.get("status")
        if status not in ("captured", "authorized"):
            raise RequestError(409, "Payment is not confirmed. Please check Razorpay Checkout and try again.")
        if status == "captured":
            with ORDER_LOCK:
                ORDERS.pop(order_id, None)
        self.send_json(200, {"verified": True, "captured": status == "captured", "status": status})

    def serve_file(self, pathname):
        relative = unquote(pathname).lstrip("/") or "form_ecommerce.HTML"
        if any(part.startswith(".") for part in Path(relative).parts):
            raise RequestError(404, "Page not found.")
        file_path = (ROOT / relative).resolve()
        try:
            file_path.relative_to(ROOT)
        except ValueError as error:
            raise RequestError(404, "Page not found.") from error
        if file_path.suffix.lower() not in ALLOWED_EXTENSIONS or not file_path.is_file():
            raise RequestError(404, "Page not found.")
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types[file_path.suffix.lower()])
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")


if __name__ == "__main__":
    load_local_environment()
    port = int(os.environ.get("PORT", "4173"))
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"FORME Market is running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()