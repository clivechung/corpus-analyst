# SkillMCP API & JSON-RPC Specification

Detailed technical specification of SkillMCP HTTP transport endpoints, JSON-RPC schema, MCP tools, and MCP resources.

---

## 🌐 Transport Protocols

### 1. Stateless Streamable HTTP Transport (Default)
- **Path**: `/mcp` (or `/sse` alias)
- **Method**: `POST`
- **Headers**:
  - `Content-Type: application/json`
  - `Accept: application/json, text/event-stream`
- **Stateless Architecture**:
  - Each incoming HTTP request is self-contained and handles its own JSON-RPC lifecycle.
  - Server does not retain persistent in-memory session state between separate requests, allowing arbitrary load balancing across replicas.
  - Streaming responses are streamed over `text/event-stream` and closed immediately upon JSON-RPC response completion.

### 2. Native SSE Transport (`SKILLMCP_TRANSPORT=sse`)
- **Handshake Path**: `GET /sse`
- **Message Path**: `POST /messages/?session_id=<UUID>`
- **Behavior**: `GET /sse` establishes an open SSE event stream and returns an `endpoint` event with session routing. Requires sticky sessions or single-replica deployment.

### 3. Health & Readiness Probe
- **Path**: `GET /healthz`
- **Status Code**: `200 OK`
- **Response Format**: `{"status": "healthy", "service": "skillmcp", "version": "<version>"}`

---

## 🛠️ MCP Tools Specification

### `list_skills`
- **Description**: Returns metadata summaries for all skills available on the server.
- **Parameters**: None
- **Return Type**: `Array<SkillMetadata>`
- **Sample Return Object**:
  ```json
  [
    {
      "name": "trem-python",
      "description": "Reviews, audits, refactors, and generates Python code following TREM principles...",
      "category": "software",
      "references": ["references/stack-patterns.md"],
      "examples": ["examples/typer-fastmcp-example.md"]
    }
  ]
  ```

---

### `get_skill`
- **Description**: Retrieves full markdown contents (frontmatter + body) of a specific skill.
- **Parameters**:
  - `name` (string, required): Lowercase skill identifier (e.g. `"trem-python"`).
- **Return Type**: `string` (Markdown text).

---

### `search_skills`
- **Description**: Performs keyword search across skill names, descriptions, and markdown content.
- **Parameters**:
  - `query` (string, required): Search query keyword (e.g. `"FastAPI"`).
- **Return Type**: `Array<SkillMetadata>`

---

### `read_skill_reference`
- **Description**: Reads a specific reference document bundled inside a skill directory.
- **Parameters**:
  - `name` (string, required): Skill name.
  - `ref_path` (string, required): Relative path to reference file (e.g. `"references/stack-patterns.md"`).
- **Return Type**: `string` (Markdown text).

---

### `read_skill_example`
- **Description**: Reads an example document bundled inside a skill directory.
- **Parameters**:
  - `name` (string, required): Skill name.
  - `example_path` (string, required): Relative path to example file (e.g. `"examples/typer-fastmcp-example.md"`).
- **Return Type**: `string` (Markdown text).

---

## 📦 MCP Resources Specification

### `skill://{name}`
- **Description**: Exposes skill content as a standard MCP Resource.
- **URI Template**: `skill://{name}`
- **Parameters**:
  - `name`: Target skill name.
- **MIME Type**: `text/markdown`
