# Import necessary modules
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory, 
                              FamilyInstance, XYZ, Transaction, Structure, 
                              FamilySymbol, View)
from Autodesk.Revit.UI import TaskDialog
from pyrevit import script

def setup_output():
    """Initialize and configure output window"""
    output = script.get_output()
    output.set_height(800)
    return output

# Get the active document and view
doc = __revit__.ActiveUIDocument.Document
view = __revit__.ActiveUIDocument.ActiveView
output = setup_output()

# Function to collect visible pipe accessories by family name
def collect_accessories_by_name(doc, view, name):
    # Use collector with document and view - handles visibility automatically
    collector = FilteredElementCollector(doc) \
        .OfCategory(BuiltInCategory.OST_PipeAccessory) \
        .WhereElementIsNotElementType() \
    
    # Filter by family name and visibility
    return [acc for acc in collector.ToElements()
            if name.lower() in acc.Symbol.Family.Name.lower() 
            and acc.IsVisibleInView(view)]

# Collect sleeves, drains, and hangers
sleeves = collect_accessories_by_name(doc, view, "sleeve")
drains = collect_accessories_by_name(doc, view, "drain")
hangers = collect_accessories_by_name(doc, view, "hanger")

# Function to place SSW layout points
def place_layout_points(doc, elements, comment, prefix=None):
    missing_tags = []
    t = Transaction(doc, "Place SSW Layout Points")
    t.Start()
    for i, elem in enumerate(elements, start=1):
        original_location = elem.Location.Point
        # Create new point at zero elevation
        location = XYZ(original_location.X, original_location.Y, 0)
        level = view.GenLevel
        # Create the SSW layout point family instance
        point = doc.Create.NewFamilyInstance(location, family_symbol, level, Structure.StructuralType.NonStructural)
        
        # Set the "Comments" parameter
        if comment == "Hangers":
            package_name = elem.LookupParameter("STRATUS Package Name").AsString()
            if package_name:
                point.LookupParameter("Comments").Set(package_name + " Hangers")
            else:
                point.LookupParameter("Comments").Set("Hangers")
        else:
            point.LookupParameter("Comments").Set(comment)
            
        # Set the "Mark" parameter
        if prefix:
            point.LookupParameter("Mark").Set("{0}{1}".format(prefix, i))
        elif comment == "Hangers":
            stratus_item_tag = elem.LookupParameter("STRATUS Item Tag").AsString()
            if stratus_item_tag:
                point.LookupParameter("Mark").Set(stratus_item_tag)
            else:
                missing_tags.append(elem.Id)
    t.Commit()
    return missing_tags

# Load the SSW layout point family symbol
family_symbol = None
collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
for symbol in collector:
    if symbol.Family.Name == "SSW Layout Point":
        family_symbol = symbol
        break

if not family_symbol:
    TaskDialog.Show("Error", "SSW Layout Point family not found.")
else:
    if not family_symbol.IsActive:
        t = Transaction(doc, "Activate Family Symbol")
        t.Start()
        family_symbol.Activate()
        t.Commit()

    # Place layout points for sleeves, drains, and hangers
    place_layout_points(doc, sleeves, "Sleeves", "S")
    place_layout_points(doc, drains, "Drains", "D")
    missing_hanger_ids = place_layout_points(doc, hangers, "Hangers")
    
    if missing_hanger_ids:
        output.print_md("### Hangers missing Stratus Item Tag:")
        for hanger_id in missing_hanger_ids:
            output.print_md("- Element ID: {}".format(hanger_id))

    TaskDialog.Show("Complete", "SSW Layout Points placed successfully.")