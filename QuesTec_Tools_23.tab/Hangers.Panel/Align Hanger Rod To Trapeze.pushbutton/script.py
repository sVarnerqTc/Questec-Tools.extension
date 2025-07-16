from pyrevit import revit, DB, script, forms

def setup_output():
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

def get_trapeze_reference():
    """Get reference elevation from trapeze hangers"""
    doc = revit.doc
    active_view = doc.ActiveView
    
    # Collect pipe accessories in active view
    accessories = (DB.FilteredElementCollector(doc, active_view.Id)
                  .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
                  .WhereElementIsNotElementType()
                  .ToElements())
    
    # Find all trapezes and their elevations
    trapezes = []
    elevations = set()
    
    for acc in accessories:
        type_elem = doc.GetElement(acc.GetTypeId())
        if type_elem and "trapeze" in type_elem.FamilyName.lower():
            location = acc.Location
            if location:
                trapezes.append(acc)
                elevations.add(round(location.Point.Z, 4))  # Round to 4 decimal places
    
    if not trapezes:
        forms.alert("No trapeze hangers found in view", exitscript=True)
        return None, None
        
    if len(elevations) > 1:
        # Build elevation list string using Python 2.7 compatible formatting
        elevation_list = "\n".join(["Elevation: {0:.4f}".format(e) for e in elevations])
        message = "Warning: Multiple trapeze elevations found:\n" + elevation_list
        forms.alert(message, exitscript=True)
        return None, None
        
    # All elevations match, return first trapeze and elevation
    return trapezes[0], list(elevations)[0]

def get_reference_elevation():
    """Get reference elevation from trapeze"""
    trapeze, elevation = get_trapeze_reference()
    if not trapeze:
        forms.alert("No trapeze hanger found in view", exitscript=True)
        return None
    return elevation

def collect_pipe_accessories(doc, view_id):
    """Collect all pipe accessories from the active view"""
    output = script.get_output()  # Debug output
    
    collector = (DB.FilteredElementCollector(doc, view_id)
                .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
                .WhereElementIsNotElementType())
    
    # Get all elements
    all_elements = collector.ToElements()
    # output.print_md("Total accessories found: {}".format(len(all_elements)))
    
    return all_elements

def process_accessories(doc, accessories):
    """Find accessories with Rod Extn Above parameter"""
    output = script.get_output()
    # output.print_md("# Finding accessories with Rod Extension Above parameter")
    # output.print_md("---")
    
    if not accessories:
        # output.print_md("No accessories found")
        return []

    filtered_accessories = []
    for acc in accessories:
        param = acc.LookupParameter("Rod Extn Above")
        if param:
            filtered_accessories.append(acc)
            # output.print_md("* Found Element ID: {0}".format(acc.Id))
    
    # output.print_md("\nTotal accessories with parameter: {0}".format(len(filtered_accessories)))
    return filtered_accessories

def calculate_elevation_differences(doc, ref_elevation, filtered_elements):
    """Calculate elevation differences accounting for sloped reference planes"""
    output = script.get_output()
    # output.print_md("# Calculating Elevation Differences")
    # output.print_md("---")
    
    if not filtered_elements:
        output.print_md("No elements to compare")
        return []
    
        
        
    differences = []
    for element in filtered_elements:
        location = element.Location
        if location:
            element_point = location.Point
            
            elevation_diff = (ref_elevation - element_point.Z)  # Convert to inches
            
            differences.append({
                'element_id': element.Id,
                'element_xyz': (element_point.X, element_point.Y, element_point.Z),
                'reference_z': ref_elevation,
                'difference': elevation_diff
            })
            
            # output.print_md(
            #     "* Element ID: {0}\n"
            #     "  * Position: ({1:.2f}, {2:.2f}, {3:.2f})\n"
            #     "  * Reference Z at point: {4:.2f}\n"
            #     "  * Difference: {5:.2f}".format(
            #         element.Id,
            #         element_point.X,
            #         element_point.Y,
            #         element_point.Z,
            #         ref_elevation,
            #         elevation_diff
            #     )
            # )
    
    set_rod_extensions(doc, differences, filtered_elements)
    return differences

def set_rod_extensions(doc, differences, filtered_elements):
    """Set Rod Extension values based on elevation differences and offsets"""
    output = script.get_output()
    excluded_elements = []
    
    t = DB.Transaction(doc, "Set Rod Extensions")
    t.Start()
    
    try:
        for diff, element in zip(differences, filtered_elements):
            # Check if difference is negative
            if diff['difference'] < 0:
                excluded_elements.append(element.Id)
                continue
                
            offset_param = element.LookupParameter("Offset")
            horiz_offset_param = element.LookupParameter("Horizontal Rod Offset")
            rod_extn_param = element.LookupParameter("Rod Extn Above")
            
            if not all([offset_param, horiz_offset_param, rod_extn_param]):
                output.print_md("* Missing required parameters for Element ID: {}".format(element.Id))
                continue
                
            offset = offset_param.AsDouble() if offset_param.HasValue else 0
            horiz_offset = horiz_offset_param.AsDouble() if horiz_offset_param.HasValue else 0
            new_extension = diff['difference'] - offset - horiz_offset
            rod_extn_param.Set(new_extension)
            
        t.Commit()
        
        # Print excluded elements
        if excluded_elements:
            output.print_md("\nExcluded elements (negative elevation difference):")
            for elem_id in excluded_elements:
                output.print_md("* Element ID: {}".format(elem_id))
                
        # output.print_md("\nSuccessfully updated rod extensions")
        
    except Exception as ex:
        t.RollBack()
        output.print_md("\nError setting rod extensions: {}".format(str(ex)))

def main():
    """Main execution function"""
    output = setup_output()
    
    try:
        doc, active_view = get_active_document_and_view()
        reference = get_reference_elevation()
        accessories = collect_pipe_accessories(doc, active_view.Id)
        processed_accessories = process_accessories(doc, accessories)
        
        # Calculate elevation differences
        differences = calculate_elevation_differences(doc, reference, processed_accessories)
        
        # print_results(output, processed_accessories)
        
    except Exception as ex:
        forms.alert("An error occurred: " + str(ex), exitscript=True)

if __name__ == "__main__":
    main()
# This script aligns hanger rods to a trapeze reference elevation in Revit.
# It collects pipe accessories, calculates elevation differences,
# and updates rod extension parameters accordingly.