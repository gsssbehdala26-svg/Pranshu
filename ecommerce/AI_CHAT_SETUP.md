# AI Chat Setup

The general-purpose AI chat runs through the Python server. The OpenAI API key stays on the server and is never sent to the browser.

## Run locally

1. Copy `.env.example` to `.env`.
2. Set `OPENAI_API_KEY` to an API key from your OpenAI account. API usage may incur charges.
3. Optionally change `OPENAI_MODEL` to a chat model available to your account.
4. Run `python server.py` from this folder and open `http://localhost:4173/chatbot.html`.

The chat keeps its conversation in browser memory only; starting a new chat or reloading the page clears it. Configure usage limits with your AI provider before sharing the app publicly. This local starter does not include user accounts, abuse prevention, or production hosting protections. AI responses can be inaccurate and should not replace qualified professional advice.
