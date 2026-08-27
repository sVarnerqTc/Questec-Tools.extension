# IPC Contract

This bridge uses a small JSON request/response contract between the Claude-side MCP host and the Revit-side add-in.

## Transport

Start with a Windows named pipe.

- local only
- no network exposure
- easy to version by request ID

## Message shape

### Request

```json
{
  "id": "c9d2f7be-74f6-4df0-b4e1-0d9f4c1c8b5e",
  "method": "revit/context",
  "payload": {
    "includeSelection": true,
    "includeActiveView": true,
    "includeElementParameters": true
  }
}
```

### Response

```json
{
  "id": "c9d2f7be-74f6-4df0-b4e1-0d9f4c1c8b5e",
  "success": true,
  "payload": {
    "documentTitle": "Project A",
    "activeViewName": "Level 1",
    "selectionCount": 3,
    "elements": []
  }
}
```

## Initial methods

- `revit/context`: return document, view, and selection context.
- `revit/selection`: return only the selected elements.
- `revit/execute`: reserved for later controlled write actions.

## Revit rules

- Any model write must be marshaled through `ExternalEvent`.
- The MCP host must never call the Revit API directly.
- Write actions should support a preview/confirm step before commit.
