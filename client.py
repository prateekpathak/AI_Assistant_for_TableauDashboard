"""
LangChain/LangGraph CLI client for the Tableau FastMCP server (server.py).

This does NOT need the Tableau MCP Starter Kit or the Node.js tableau-mcp
server — it talks directly to your existing FastMCP server.py over stdio.

LangSmith tracing needs no code here at all: LangChain auto-detects the
LANGSMITH_* environment variables and traces the agent run, the LLM calls,
and every MCP tool call as nested spans.

Setup:
    pip install langchain-mcp-adapters langgraph langchain-openai python-dotenv

Env vars needed (put these in the same .env your server.py already reads,
or a separate one next to this file — load_dotenv() picks up both):

    # Tableau (already in your server.py .env)
    TABLEAU_SERVER_URL=https://10ax.online.tableau.com
    TABLEAU_SITE=personalsandboxpp
    TABLEAU_TOKEN_NAME=...
    TABLEAU_TOKEN_SECRET=...

    # LLM
    OPENAI_API_KEY=...

    # LangSmith (EU workspace)
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=...
    LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
    LANGSMITH_PROJECT=tableau-fastmcp-chatbot

Run:
    python client.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage

# Path to your Tableau FastMCP server.py — override with an env var if it
# lives somewhere other than alongside this file.
SERVER_PATH = os.environ.get("TABLEAU_MCP_SERVER_PATH", "server.py")

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions about Tableau content "
    "and data. Use the available tools to find data sources, workbooks and "
    "views, and to query data directly. Always call get_datasource_metadata "
    "on a data source before calling query_datasource, so you know the exact "
    "field captions (they are case-sensitive)."
)


async def main() -> None:
    server_params = StdioServerParameters(
        # Use the SAME interpreter running this script (your venv), not
        # whatever "python" happens to resolve to on PATH. On Windows in
        # particular, a bare "python" can point at the Store alias or a
        # different install than the one you pip-installed into, which
        # silently breaks the subprocess and hangs session.initialize().
        command=sys.executable,
        args=[os.path.abspath(SERVER_PATH)],
        # Forward the full environment so the child process sees
        # TABLEAU_SERVER_URL, TABLEAU_SITE, TABLEAU_TOKEN_NAME/SECRET, etc.
        env={**os.environ},
    )

    # errlog=sys.stderr (the default) means the child process's stderr is
    # printed to THIS terminal — if server.py fails to import or crashes on
    # startup, you'll see that traceback here instead of a bare hang.
    async with stdio_client(server_params, errlog=sys.stderr) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await load_mcp_tools(session)
            llm = ChatOpenAI(model="gpt-4.1", temperature=0)
            checkpointer = InMemorySaver()
            agent = create_react_agent(
                model=llm,
                tools=tools,
                prompt=SYSTEM_PROMPT,
                checkpointer=checkpointer,
            )

            # All turns in this run share one thread_id, so the agent (and
            # LangSmith, if you group by thread) treats them as one
            # conversation rather than unrelated one-off calls.
            config = {"configurable": {"thread_id": "cli-session-1"}}

            print(f"Connected to {SERVER_PATH}. Type 'exit' to quit.\n")
            while True:
                question = input("You: ").strip()
                if question.lower() in {"exit", "quit"}:
                    break
                if not question:
                    continue
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=question)]},
                    config=config,
                )
                print(f"\nAssistant: {result['messages'][-1].content}\n")


if __name__ == "__main__":
    asyncio.run(main())