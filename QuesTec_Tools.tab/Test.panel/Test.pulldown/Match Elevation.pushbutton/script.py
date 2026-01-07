from pyrevit import revit, DB, UI, forms
from pyrevit import script



def get_element_elevation_data(element):
    """Get elevation and level data from an element based on its category."""
    category = element.Category
    
    if category and category.Id.IntegerValue == int(DB.BuiltInCategory.OST_PipeCurves):
        # Pipe element - use 'Middle Elevation' and 'Reference Level'
        elevation_param = element.LookupParameter("Middle Elevation")
        level_param = element.LookupParameter("Reference Level")
        return elevation_param, level_param, "Pipe"
    else:
        # Pipe accessory or fitting - use 'Elevation from Level' and 'Level'
        elevation_param = element.LookupParameter("Elevation from Level")
        level_param = element.LookupParameter("Level")
        return elevation_param, level_param, "Accessory/Fitting"

def main():
    doc = revit.doc
    uidoc = revit.uidoc
    
    # Get first selection
    try:
        selection1 = uidoc.Selection.PickObject(
            UI.Selection.ObjectType.Element,
            "Select the first element (source elevation)"
        )
        element1 = doc.GetElement(selection1.ElementId)
    except:
        script.exit()
    
    # Get second selection
    try:
        selection2 = uidoc.Selection.PickObject(
            UI.Selection.ObjectType.Element,
            "Select the second element (target to match elevation)"
        )
        element2 = doc.GetElement(selection2.ElementId)
    except:
        script.exit()
    
    # Get elevation data from both elements
    elev_param1, level_param1, type1 = get_element_elevation_data(element1)
    elev_param2, level_param2, type2 = get_element_elevation_data(element2)
    
    # Validate parameters exist based on element type
    if type1 == "Pipe":
        if not elev_param1 or not level_param1:
            forms.alert("First element (Pipe) is missing 'Middle Elevation' or 'Reference Level' parameters.")
            return
    else:
        if not elev_param1 or not level_param1:
            forms.alert("First element (Accessory/Fitting) is missing 'Elevation from Level' or 'Level' parameters.")
            return
    
    if type2 == "Pipe":
        if not elev_param2 or not level_param2:
            forms.alert("Second element (Pipe) is missing 'Middle Elevation' or 'Reference Level' parameters.")
            return
    else:
        if not elev_param2 or not level_param2:
            forms.alert("Second element (Accessory/Fitting) is missing 'Elevation from Level' or 'Level' parameters.")
            return
    
    # Get values from first element
    source_elevation = elev_param1.AsDouble()
    source_level_id = level_param1.AsElementId()
    
    # Start transaction
    with revit.Transaction("Match Elevation"):
        # Match the level first if different
        if level_param2.AsElementId() != source_level_id:
            level_param2.Set(source_level_id)
        
        # Match the elevation
        elev_param2.Set(source_elevation)
    
    # Show completion message
    source_level = doc.GetElement(source_level_id)
    elevation_ft = source_elevation
    #forms.alert(
    #    "Elevation matched successfully!\n"
    #    "Source: {}\n"
    #    "Target: {}\n"
    #    "Level: {}\n"
    #    "Elevation: {:.3f} ft".format(type1, type2, source_level.Name, elevation_ft)
    #)

if __name__ == "__main__":
    main()
