"""
HTTP wrapper around your LangGraph agent + Tableau FastMCP server.

Serves BOTH the API (/chat) and the extension files (/index.html), so one
HTTPS tunnel/URL is all Tableau needs (same origin = no CORS headaches).

Run:
    pip install fastapi uvicorn langchain-mcp-adapters langgraph langchain-openai python-dotenv
    python agent_api.py

"""
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage

SERVER_PATH = os.environ.get("TABLEAU_MCP_SERVER_PATH", "server.py")

SYSTEM_PROMPT = (
    "You are an assistant embedded in a Tableau dashboard. Answer questions "
    "about Tableau content and data. Use the tools to find data sources, "
    "workbooks and views, and to query data directly. Always call "
    "get_datasource_metadata before query_datasource so you know the exact "
    "field captions (they are case-sensitive). The user's message may start "
    "with a [Dashboard context] block describing the dashboard they are "
    "looking at; use it to resolve phrases like 'this dashboard'. Keep "
    "answers concise. " 
    "If a query_datasource call returns an error, read the error message, "
    "correct the filter or fields yourself, and retry (up to 3 times) before "
    "asking the user anything. "
    "For month, quarter or year requests, convert the period to a "
    "QUANTITATIVE_DATE range from its first to its last day."
)

state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.abspath(SERVER_PATH)],
        env={**os.environ},
    )
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(
            stdio_client(params, errlog=sys.stderr)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = await load_mcp_tools(session)
        state["agent"] = create_react_agent(
            model=ChatOpenAI(model="gpt-4.1", temperature=0),
            tools=tools,
            prompt=SYSTEM_PROMPT,
            checkpointer=InMemorySaver(),
        )
        print(f"Agent ready with {len(tools)} tools")
        yield


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"
    context: str = ""


@app.post("/chat")
async def chat(req: ChatRequest):
    text = f"[Dashboard context]\n{req.context}\n\n{req.message}" if req.context else req.message
    try:
        result = await state["agent"].ainvoke(
            {"messages": [HumanMessage(content=text)]},
            config={"configurable": {"thread_id": req.thread_id}},
        )
        return {"reply": result["messages"][-1].content}
    except Exception as e:  # surface errors to the panel
        return {"reply": f"Error: {e}", "error": True}


# Must be mounted last so it doesn't shadow /chat
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    # uvicorn.run(app, host="0.0.0.0", port=8000) 
       
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))