# Claude Desktop Bridge

This folder holds the C# bridge between Revit and Claude Desktop.

## Shape

- `QuesTec.Bridge.Contracts`: shared JSON/message models.
- `QuesTec.RevitBridge`: Revit add-in that owns all Revit API calls.
- `QuesTec.ClaudeBridge.Mcp`: local MCP host that Claude Desktop connects to.

## First milestone

Read-only bridge:

- export current document and selection context
- return active view metadata
- read element snapshots
- pass context through a local IPC channel

## Next milestone

Controlled write actions:

- set parameter values
- select/isolate elements in Revit
- preview changes before commit

## Notes

- Revit API calls must run on Revit's UI thread.
- Use `ExternalEvent` / `IExternalEventHandler` for write actions.
- Keep the MCP server separate from the add-in process.
