# Run the AI chatbot with Ollama

The chatbot uses a locally running Ollama server; no API key or cloud account is required. Opening `chatbot.html` directly or serving it from a static-only host will not connect it to the backend.

1. Install Ollama and start the Ollama app. Its local API should be available at `http://localhost:11434`.
2. In PowerShell, download the default model:

   ```powershell
   ollama pull llama3.2
   ```

3. Make sure `.env` is in this folder, alongside `server.py` and `chatbot.html`. If needed, copy `.env.example` to `.env`. The default model is `llama3.2`; set `OLLAMA_MODEL` to a different model you have downloaded if desired.
4. Open PowerShell in this folder and start the chatbot backend:

   ```powershell
   py server.py
   ```

5. Open `http://localhost:4174/chatbot.html` in your browser. Keep Ollama and the Python server running while you chat.

If port 4174 is already in use, start the server on another port, for example:

```powershell
$env:PORT=4175
py server.py
```

Then open `http://localhost:4175/chatbot.html`.

If the page says Ollama is unavailable, start the Ollama app and check that `http://localhost:11434` is reachable. If it says the model is missing, run `ollama pull llama3.2` (or pull the model named in `.env`). The chat is a local starter and does not include production hosting protections or abuse prevention.
