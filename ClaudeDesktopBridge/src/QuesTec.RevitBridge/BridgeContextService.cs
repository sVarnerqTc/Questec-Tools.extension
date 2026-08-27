using QuesTec.Bridge.Contracts;

namespace QuesTec.RevitBridge;

public interface IBridgeContextService
{
    RevitContextResponse GetCurrentContext(RevitContextRequest request);
}

public sealed class BridgeContextService : IBridgeContextService
{
    public RevitContextResponse GetCurrentContext(RevitContextRequest request)
    {
        // Revit API calls will be filled in once the add-in shell is wired to ExternalEvent.
        return new RevitContextResponse
        {
            DocumentTitle = "",
            DocumentPath = "",
            ActiveViewName = "",
            ActiveViewType = "",
            SelectionCount = 0,
            Elements = Array.Empty<ElementSnapshot>()
        };
    }
}
