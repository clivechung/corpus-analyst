---
name: skillmcp
description: >-
  Connect to, query, and manage AI agent skills using the stateless SkillMCP (Skill Management System) server over Streamable HTTP.
  Use this skill whenever discovering, searching, inspecting, or fetching AI agent skills, reference documents, or examples from a containerized or remote SkillMCP server instance.
category: software
---

# SkillMCP MCP Server Integration

A guide and operational workflow for discovering, searching, inspecting, and retrieving AI agent skills via the **SkillMCP (Skill Management System)** Model Context Protocol (MCP) server.

SkillMCP delivers a centralized, horizontally scalable skill repository designed for autonomous agent fleets. It uses **Stateless Streamable HTTP** by default, allowing request/response decoupling across multiple backend replicas without requiring sticky sessions.

---

## 🚀 Quick Start

### 1. Transport & Connection Matrix

| Transport Mode | Endpoint URL | HTTP Method | Header Requirements | Statefulness |
| :--- | :--- | :--- | :--- | :--- |
| **Streamable HTTP** | `http://<host>:8080/mcp` | `POST` | `Accept: application/json, text/event-stream`<br>`Content-Type: application/json` | **Stateless** (horizontally scalable, HPA ready) |
| **Health Check** | `http://<host>:8080/healthz` | `GET` | None | **Stateless** |

### 2. Antigravity MCP Client Configuration (`mcp_config.json`)

To register a remote SkillMCP instance in Antigravity or standard MCP client configurations:

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

---

## 🛠️ Workflows

### Workflow 1: Connecting & Validating Server Health

1. **Verify Backend Health & Readiness**:
   Send a `GET` request to `http://<host>:8080/healthz`.
   - **Expected Status**: `200 OK`
   - **Expected Body**: `{"status": "healthy", "service": "skillmcp", "version": "<version>"}`
2. **Perform Stateless JSON-RPC Handshake**:
   Send an `initialize` JSON-RPC request to `/mcp` with header `Accept: application/json, text/event-stream`:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 1,
     "method": "initialize",
     "params": {
       "protocolVersion": "2024-11-05",
       "capabilities": {},
       "clientInfo": { "name": "agent-client", "version": "1.0.0" }
     }
   }
   ```
3. **Verify Server Capabilities**:
   Ensure the response confirms protocol version `2024-11-05` and advertises `tools`, `prompts`, and `resources`.

---

### Workflow 2: Discovering & Searching Skills

1. **List All Available Skills**:
   Call `list_skills` to retrieve summary metadata for all skills available on the server (names, descriptions, categories, references, and examples):
   ```json
   {
     "jsonrpc": "2.0",
     "id": 2,
     "method": "tools/call",
     "params": {
       "name": "list_skills",
       "arguments": {}
     }
   }
   ```
2. **Search Skills by Topic or Keyword**:
   Call `search_skills` when seeking skills relevant to a specific task, technology, or domain:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 3,
     "method": "tools/call",
     "params": {
       "name": "search_skills",
       "arguments": { "query": "python trem" }
     }
   }
   ```

---

### Workflow 3: Retrieving Skill Instructions & Associated Assets

1. **Retrieve Full Skill Instructions (`SKILL.md`)**:
   Call `get_skill` with the skill name to fetch complete markdown instructions and frontmatter:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 4,
     "method": "tools/call",
     "params": {
       "name": "get_skill",
       "arguments": { "name": "trem-python" }
     }
   }
   ```
2. **Fetch Referenced Documentation (`references/`)**:
   When a skill references supplemental deep-dive documents listed in its metadata, fetch them using `read_skill_reference`:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 5,
     "method": "tools/call",
     "params": {
       "name": "read_skill_reference",
       "arguments": {
         "name": "trem-python",
         "ref_path": "references/stack-patterns.md"
       }
     }
   }
   ```
3. **Fetch Practical Examples (`examples/`)**:
   When concrete implementation samples are required, fetch them using `read_skill_example`:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 6,
     "method": "tools/call",
     "params": {
       "name": "read_skill_example",
       "arguments": {
         "name": "trem-python",
         "example_path": "examples/typer-fastmcp-example.md"
       }
     }
   }
   ```
4. **Access via MCP Resource URI**:
   Directly inspect skill markdown via standard MCP resource URI `skill://{name}`:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 7,
     "method": "resources/read",
     "params": {
       "uri": "skill://trem-python"
     }
   }
   ```

---

### Workflow 4: Managing Stateless Replicas & Load Balancing

1. **Horizontal Scaling**:
   Because Streamable HTTP is stateless (`stateless_http=True`), requests can be distributed across any number of container replicas behind Nginx (`least_conn` or `round_robin`) without sticky session cookies (`ip_hash`).
2. **Health Monitoring & Zero-Downtime Updates**:
   Target `/healthz` for load balancer probes, Kubernetes liveness/readiness probes, or rolling deployments.

---

## 📋 MCP Tools & Resources Reference

| Name | Type | Description | Parameters | Return Type |
| :--- | :--- | :--- | :--- | :--- |
| `list_skills` | Tool | Lists all available skills with metadata, categories, references, and examples. | None | `Array<SkillMetadata>` |
| `get_skill` | Tool | Retrieves full markdown instructions (`SKILL.md`) for a skill. | `name` (string, required) | `string` (Markdown) |
| `search_skills` | Tool | Searches available skills matching a keyword or topic query. | `query` (string, required) | `Array<SkillMetadata>` |
| `read_skill_reference` | Tool | Reads a bundled reference document from a skill's `references/` directory. | `name` (string, required),<br>`ref_path` (string, required) | `string` (Markdown) |
| `read_skill_example` | Tool | Reads a bundled example document from a skill's `examples/` directory. | `name` (string, required),<br>`example_path` (string, required) | `string` (Markdown) |
| `skill://{name}` | Resource | Exposes skill markdown content as a standard MCP Resource. | `name` (URI parameter) | `text/markdown` |

---

## 📚 Advanced Features & References

- [SkillMCP API & JSON-RPC Specification](references/api-spec.md) — Comprehensive JSON-RPC schemas, transport headers, and stateless request lifecycle.
- [MCP Client Implementation Examples](examples/mcp-client-usage.md) — Python (`httpx`/`mcp`), TypeScript, and cURL implementation patterns for stateless MCP calls.
