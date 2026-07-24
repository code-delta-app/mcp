# Glama verification image — starts the CodeDelta MCP server (stdio JSON-RPC).
# The server lists its tools without the engine binary; tool CALLS need the
# CodeDelta engine from https://codedelta.app/download.html mounted alongside.
FROM python:3.12-slim
WORKDIR /app
COPY codedelta_mcp.py .
CMD ["python3", "codedelta_mcp.py"]
