# Architecture V2 Flow

This repository now treats the v2 runtime as the source of truth for document mutations.

## `/invocations`

API Gateway forwards chat-style requests to AgentCore Runtime `POST /invocations`.
The runtime calls `ParentOrchestrator`, which delegates to sub-agents and writes document changes through optimistic locking.

## `/documents/{docId}/chat` compatibility alias

`POST /documents/{docId}/chat` remains available for backward compatibility.
It maps to the same runtime payload shape as `/invocations`:

```json
{ "doc_id": "...", "prompt": "...", "history": [] }
```

The Lambda does not mutate the authoritative document state directly for chat requests.

## AppSync channels

Document updates are published through separate AppSync Event channels:

- `docs/{docId}/chat` for streamed chat chunks and final chat messages
- `docs/{docId}/status` for processing / idle / degraded / error state
- `docs/{docId}/patch` for authoritative document patches

The frontend applies patch events through `applyPatches()`. Chat events update chat UI only.

## DynamoDB optimistic locking

`DocumentStore.update()` / conditional writes use the stored version as the expected version.
If the stored version moves before the update lands, the write fails safely with a version conflict.

## REST fallback

REST reloads still use `setDocument()` to replace the full local document view.
That path is reserved for reload and fallback behavior, not for agent-authored mutations.
