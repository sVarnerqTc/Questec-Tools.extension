from pyrevit import revit, DB, script, forms
from typing import List, Dict
from collections import defaultdict

def setup_output() -> script.output:
    """Initialize and configure output window"""
    output = script.get_output()
    output.set_height(800)
    return output

def get_active_document_and_view():
    """Validate and return active document and view"""
    doc = revit.doc
    if not doc:
        raise ValueError("No active document found.")
    
    active_view = doc.ActiveView
    if not active_view:
        raise ValueError("No active view found.")
    
    return doc, active_view

def collect_pipe_accessories(doc: DB.Document, view_id: DB.ElementId) -> List[DB.Element]:
    """Collect all pipe accessories from the active view"""
    return (DB.FilteredElementCollector(doc, view_id)
            .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
            .WhereElementIsNotElementType()
            .ToElements())

def process_accessories(doc: DB.Document, accessories: List[DB.Element]) -> List[Dict]:
    """Process pipe accessories and extract relevant information"""
    processed_items = []
    
    for acc in accessories:
        param = acc.LookupParameter("QTC Pipe Size")
        if not param:
            continue
            
        type_elem = doc.GetElement(acc.GetTypeId())
        type_name = type_elem.FamilyName if type_elem else "Unknown Type"
        
        processed_items.append({
            'id': acc.Id,
            'name': acc.Name,
            'type': type_name,
            'size': param.AsString() if param.HasValue else "No Value"
        })
    
    return processed_items

def print_results(output, accessories: List[Dict]):
    """Format and print results to output window"""
    output.print_md("# Pipe Accessories with QTC Pipe Size Parameter")
    output.print_md("---")
    
    if not accessories:
        output.print_md("No accessories found with 'QTC Pipe Size' parameter.")
        return
        
    # Group accessories by type for better organization
    by_type = defaultdict(list)
    for acc in accessories:
        by_type[acc['type']].append(acc)
    
    for type_name, items in by_type.items():
        output.print_md(f"\n## {type_name}")
        for acc in items:
            output.print_md(
                f"* **ID**: {acc['id']}\n"
                f"  * Name: {acc['name']}\n"
                f"  * Size: {acc['size']}"
            )
    
    output.print_md(f"\n**Total Found: {len(accessories)}**")

def main():
    """Main execution function"""
    output = setup_output()
    
    try:
        doc, active_view = get_active_document_and_view()
        accessories = collect_pipe_accessories(doc, active_view.Id)
        processed_accessories = process_accessories(doc, accessories)
        print_results(output, processed_accessories)
        
    except Exception as ex:
        forms.alert(f"An error occurred: {ex}", exitscript=True)

if __name__ == "__main__":
    main()