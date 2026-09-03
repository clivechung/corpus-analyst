# SkillMCP MCP Client Integration Examples

Code snippets for interacting with SkillMCP over Streamable HTTP and SSE transports in Python, TypeScript, and cURL.

---

## 1. Python (`mcp` SDK & `httpx`)

```python
import httpx
import asyncio

async def main():
    base_url = "http://localhost:8080/mcp"
    headers = {"Accept": "application/json, text/event-stream"}

    async with httpx.AsyncClient() as client:
        # Step 1: Initialize
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "python-client", "version": "1.0"}
            }
        }
        res = await client.post(base_url, json=init_payload, headers=headers)
        print("Init response:", res.text)

        # Step 2: List Skills
        list_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "list_skills",
                "arguments": {}
            }
        }
        res_list = await client.post(base_url, json=list_payload, headers=headers)
        print("Skills list:", res_list.text)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 2. cURL (Streamable HTTP)

```bash
# Initialize Session
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "curl-test", "version": "1.0"}
    }
  }'

# Call get_skill tool
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get_skill",
      "arguments": { "name": "trem-python" }
    }
  }'
```

---

## 3. Antigravity Configuration (`mcp_config.json`)

```json
{
  "mcpServers": {
    "skillmcp": {
      "type": "http",
      "url": "http://localhost:8080/mcp"
    }
  }
}
```
