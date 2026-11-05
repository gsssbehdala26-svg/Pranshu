# Run the AI chatbot locally

The browser page needs the Python server for `/api/chat`. Opening `chatbot.html` directly or serving it from a static-only host will not connect it to the AI service.

1. Make sure `.env` is in this folder, alongside `server.py` and `chatbot.html`. If needed, copy `.env.example` to `.env`.
2. In `.env`, set `OPENAI_API_KEY` to an API key from your OpenAI API account. Keep the key private; do not put it in `chatbot.html` or commit `.env`. API usage may incur charges.
3. Optionally set `OPENAI_MODEL` to a model available to your API account.
4. Open PowerShell in this folder and start the backend:

   ```powershell
   python server.py
   ```

5. Open `http://localhost:4174/chatbot.html` in your browser. Keep the terminal running while you chat.

If port 4174 is already in use, start the server on another port, for example:

```powershell
$env:PORT=4175
python server.py
```

Then open `http://localhost:4175/chatbot.html`.

If you see a provider permission error after the page connects, confirm the API key is active, has access to the selected model, and the account has API billing/usage available. The chat is a local starter and does not include production hosting protections or abuse prevention.
