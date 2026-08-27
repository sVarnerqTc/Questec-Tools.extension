namespace QuesTec.Bridge.Contracts;

public sealed class BridgeRequestEnvelope
{
    public string? Id { get; set; }
    public string? Method { get; set; }
    public object? Payload { get; set; }
}

public sealed class BridgeResponseEnvelope
{
    public string? Id { get; set; }
    public bool Success { get; set; }
    public string? Error { get; set; }
    public object? Payload { get; set; }
}

public sealed class RevitContextRequest
{
    public bool IncludeSelection { get; set; } = true;
    public bool IncludeActiveView { get; set; } = true;
    public bool IncludeElementParameters { get; set; } = true;
}

public sealed class RevitContextResponse
{
    public string? DocumentTitle { get; set; }
    public string? DocumentPath { get; set; }
    public string? ActiveViewName { get; set; }
    public string? ActiveViewType { get; set; }
    public int? SelectionCount { get; set; }
    public IReadOnlyList<ElementSnapshot> Elements { get; set; } = Array.Empty<ElementSnapshot>();
}

public sealed class ElementSnapshot
{
    public int ElementId { get; set; }
    public string? UniqueId { get; set; }
    public string? Category { get; set; }
    public string? ClassName { get; set; }
    public string? Name { get; set; }
    public IReadOnlyDictionary<string, string?> Parameters { get; set; } = new Dictionary<string, string?>();
}
