# Tableau MCP Chat extension

Files: `agent_api.py` (backend + serves the page), `static/index.html` (extension UI), `chat.trex` (manifest).
Put `server.py` and your `.env` in this folder (same variables as before).

1. `pip install fastapi uvicorn langchain-mcp-adapters langgraph langchain-openai python-dotenv`
2. `python agent_api.py`  -> http://localhost:8000
3. Expose over HTTPS: `cloudflared tunnel --url http://localhost:8000` (or ngrok). Copy the https URL.
4. Edit `chat.trex`: set `<url>` to `https://<your-url>/index.html`.
5. Tableau Cloud: Settings > Extensions > add that URL to the allow list (network-enabled).
6. Edit the dashboard > Extension object > Access Local Extensions > pick `chat.trex`.
