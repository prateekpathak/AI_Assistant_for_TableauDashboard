# Architecture

This diagram describes the tracked application entrypoints: `server.py`,
`agent_api.py`, `client.py`, and the Tableau extension in `static/` and
`chat.trex`. The archived and untracked source variants are not part of this
description.

```mermaid
flowchart LR
    subgraph Extension["Tableau dashboard extension"]
        Dashboard["Tableau dashboard"]
        UI["static/index.html<br/>chat UI"]
        Context["Dashboard name,<br/>worksheets and filters"]
        Dashboard --> UI
        Dashboard --> Context
    end

    subgraph HTTP["agent_api.py · FastAPI"]
        Static["StaticFiles mount"]
        Chat["POST /chat"]
        Agent["LangGraph ReAct agent<br/>InMemorySaver checkpointer"]
        Static --> UI
        Chat --> Agent
    end

    UI -->|"message, thread_id, context"| Chat
    Chat -->|"assistant reply"| UI

    subgraph MCP["server.py · FastMCP over stdio"]
        Tools["18 registered Tableau tools"]
        REST["Tableau Server Client<br/>REST API"]
        VDS["requests<br/>VizQL Data Service"]
        Pulse["requests<br/>Tableau Pulse API"]
        Tools --> REST
        Tools --> VDS
        Tools --> Pulse
    end

    Agent <-->|"MCP ClientSession / stdio subprocess"| Tools
    Agent <-->|"model calls"| OpenAI["OpenAI ChatOpenAI<br/>gpt-4.1"]
    REST <-->|"PAT sign-in/session"| Tableau["Tableau Server / Cloud"]
    VDS <-->|"X-Tableau-Auth"| Tableau
    Pulse <-->|"X-Tableau-Auth"| Tableau

    subgraph CLI["client.py · terminal client"]
        Terminal["User prompt / response"]
        CliAgent["LangGraph ReAct agent"]
        Terminal --> CliAgent
    end
    CliAgent <-->|"MCP ClientSession / stdio subprocess"| Tools
    CliAgent <-->|"model calls"| OpenAI

    Tools -->|"download tools write workbook, PNG, PDF"| Files["Local filesystem<br/>caller-selected output_dir"]
```

## Request and data flow

- `agent_api.py` starts a FastMCP `server.py` subprocess during FastAPI lifespan,
  initializes an MCP client session, loads the registered tools, and creates a
  LangGraph ReAct agent. The agent is then reused for HTTP chat requests.
- The extension initializes through the Tableau Extensions API. Before each
  message it refreshes dashboard context when possible, then sends
  `message`, `thread_id`, and `context` as JSON to `/chat`. The API prepends
  the context to the message and invokes the agent.
- The agent can call the MCP tools over the subprocess's stdio connection. The
  tools authenticate with a Tableau Personal Access Token for each tool call.
  TSC handles the classic Tableau REST operations; VDS and Pulse calls use
  `requests` with the session's `X-Tableau-Auth` token.
- The final agent message is returned as `reply` to the extension. Tool errors
  can propagate through the agent/API error handling.
- `client.py` is an independent terminal interface: it starts the same
  `server.py` subprocess, loads its tools, invokes its own LangGraph agent, and
  prints responses. It does not pass through the HTTP extension service.
- Workbook, PNG, and PDF download tools write to the local filesystem. The
  project does not configure a database or persistent application cache.
