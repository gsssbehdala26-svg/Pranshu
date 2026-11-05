# Razorpay UPI Checkout

The storefront and Razorpay order use INR. The browser never receives the Razorpay secret key; the local Python server creates orders and verifies payment signatures.

## Run locally

1. Install Python 3.8 or newer.
2. Copy `.env.example` to `.env` and enter your Razorpay **test** Key ID and Key Secret from the Razorpay Dashboard. Never put the secret in HTML or share it in chat.
3. Run `python server.py` from this folder and open `http://localhost:4173`.
4. Add an item, continue through checkout, and choose UPI in Razorpay Checkout. Test-mode UPI IDs documented by Razorpay include `success@razorpay` and `failure@razorpay`.

The payment page stays disabled until test keys are configured. UPI availability is controlled by the payment methods enabled for your Razorpay account. The page preselects UPI when available; other methods offered by Razorpay remain accessible.

Before accepting live payments, replace test keys with live keys, use HTTPS, enable automatic payment capture, configure Razorpay webhooks, and move the in-memory order records to a persistent database. This starter verifies the Checkout signature and confirms captured status, but it is not a production order-management system.