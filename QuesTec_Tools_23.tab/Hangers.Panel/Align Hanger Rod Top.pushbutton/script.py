from pyrevit import revit, DB, script, forms
import math  # Add this import at the top
# Add UV definition at top
UV = DB.UV  # Define UV class from Revit DB

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

def prompt_for_reference():
    """Prompt user to select a level or reference plane"""
    options = {
        'Levels': DB.FilteredElementCollector(revit.doc)
                .OfClass(DB.Level)
                .ToElements(),
        'Reference Planes': DB.FilteredElementCollector(revit.doc)
                .OfClass(DB.ReferencePlane)
                .ToElements()
    }
    
    category = forms.CommandSwitchWindow.show(
        options.keys(),
        message='Select element type:'
    )
    
    if not category:
        return None
    
    # Format display names based on element type
    elements = options[category]
    if category == 'Reference Planes':
        display_list = {elem: elem.Name for elem in elements}
    else:  # Levels
        display_list = {elem: elem.Name for elem in elements}
        
    selected = forms.SelectFromList.show(
        sorted(display_list.values()),  # Show sorted names
        multiselect=False,
        title='Select ' + category,
        width=500
    )
    
    # Convert selected name back to element
    if selected:
        return next(elem for elem, name in display_list.items() if name == selected)
    return None

def collect_pipe_accessories(doc, view_id, reference_element):
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

def calculate_elevation_differences(doc, reference_element, filtered_elements):
    """Calculate elevation differences accounting for sloped reference planes"""
    output = script.get_output()
    # output.print_md("# Calculating Elevation Differences")
    # output.print_md("---")
    
    if not filtered_elements:
        output.print_md("No elements to compare")
        return []
    
    # Get project base point elevation
    project_location = doc.ActiveProjectLocation
    project_position = project_location.GetProjectPosition(DB.XYZ.Zero)
    survey_to_internal_elevation = project_position.Elevation
    base_point = (DB.FilteredElementCollector(doc)
             .OfCategory(DB.BuiltInCategory.OST_ProjectBasePoint)
             .FirstElement())
    if base_point:
        survey_to_base_point = base_point.get_Parameter(
            DB.BuiltInParameter.BASEPOINT_ELEVATION_PARAM).AsDouble()
        # output.print_md("Survey to Base Point Elevation: {:.2f}".format(survey_to_base_point))
    else:
        survey_to_base_point = 0.0
        output.print_md("Warning: Could not find Project Base Point")
    base_point_elevation = survey_to_base_point - survey_to_internal_elevation
    # output.print_md("* project Base Point: {:.2f}".format(base_point_elevation))

    # Get reference elevation or plane points
    if isinstance(reference_element, DB.Level):
        ref_elevation = reference_element.Elevation + base_point_elevation
        is_sloped = False
    else:  # Reference Plane
        # Get both ends of reference plane
        bubble_point = reference_element.BubbleEnd
        free_point = reference_element.FreeEnd
        is_sloped = True
        # Calculate slope vector
        slope_vector = free_point - bubble_point

        # # Print endpoint elevations
        # output.print_md("Reference Plane Endpoints:")
        # output.print_md("* Bubble End: ({:.2f}, {:.2f}, {:.2f})".format(
        #     bubble_point.X, bubble_point.Y, bubble_point.Z))
        # output.print_md("* Free End: ({:.2f}, {:.2f}, {:.2f})".format(
        #     free_point.X, free_point.Y, free_point.Z))
        
        # Calculate and print slope
        # slope_vector = free_point - bubble_point
        # run = ((slope_vector.X ** 2 + slope_vector.Y ** 2) ** 0.5)  # Horizontal distance
        # if run != 0:
        #     slope = slope_vector.Z / run
        #     slope_percent = slope * 100
            # output.print_md("* Slope: {:.2f}% ({:.2f} degrees)".format(
            #     slope_percent, 
            #     math.degrees(math.atan(slope))
            # ))
        # output.print_md("---")
        
        
        
    
    
    differences = []
    for element in filtered_elements:
        location = element.Location
        if location:
            element_point = location.Point
            
            if is_sloped:
                # Get the XY distance from bubble point to element point
                dx = element_point.X - bubble_point.X
                dy = element_point.Y - bubble_point.Y
                
                # Calculate percentage along slope in XY plane
                slope_run_x = free_point.X - bubble_point.X
                slope_run_y = free_point.Y - bubble_point.Y
                total_run = (slope_run_x ** 2 + slope_run_y ** 2) ** 0.5
                
                # Project element point onto slope line (in XY plane)
                if total_run != 0:
                    # Calculate dot product to find position along slope
                    element_run = (dx * slope_run_x + dy * slope_run_y) / total_run
                    # Percentage along slope (0 to 1)
                    t = element_run / total_run
                    # Interpolate Z value
                    ref_elevation = bubble_point.Z + (t * slope_vector.Z)
                else:
                    ref_elevation = bubble_point.Z

                # # Debug output
                # output.print_md("* Point: ({:.2f}, {:.2f}, {:.2f})".format(
                #     element_point.X, element_point.Y, element_point.Z))
                # output.print_md("* Reference Z at XY: {:.2f}".format(ref_elevation))

            
            elevation_diff = (ref_elevation - element_point.Z)
            
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

def prompt_for_offset():
    """Prompt user for additional offset value"""
    offset_value = forms.ask_for_string(
        prompt="Enter additional offset value in INCHES (positive or negative number):",
        title="Rod Extension Offset"
    )
    
    try:
        return float(offset_value) if offset_value else 0
    except ValueError:
        forms.alert("Invalid number format. Using 0 as offset.", exitscript=False)
        return 0

def set_rod_extensions(doc, differences, filtered_elements):
    """Set Rod Extension values based on elevation differences and offsets"""
    output = script.get_output()
    user_offset = prompt_for_offset()/12  # Convert to feet
    excluded_elements = []
    
    t = DB.Transaction(doc, "Set Rod Extensions")
    t.Start()
    
    try:
        for diff, element in zip(differences, filtered_elements):
            if diff['difference'] < 0:
                excluded_elements.append(element.Id)
                continue
                    
            offset_param = element.LookupParameter("Offset")
            horiz_offset_param = element.LookupParameter("Horizontal Rod Offset")
            rod_extn_param = element.LookupParameter("Rod Extn Above")
            
            if not rod_extn_param:
                output.print_md("* Missing Rod Extension parameter for Element ID: {}".format(element.Id))
                continue
                
            offset = offset_param.AsDouble() if (offset_param and offset_param.HasValue) else 0
            horiz_offset = horiz_offset_param.AsDouble() if (horiz_offset_param and horiz_offset_param.HasValue) else 0
            new_extension = diff['difference'] - offset - horiz_offset + (user_offset)
            # First check for negative difference
            if new_extension < 0:
                excluded_elements.append(element.Id)
                continue
            rod_extn_param.Set(new_extension)
            
        t.Commit()
        
        # Print excluded elements
        if excluded_elements:
            output.print_md("\nExcluded hangers above the reference plane:")
            for elem_id in excluded_elements:
                output.print_md("* Element ID: {}".format(elem_id))
                
        # output.print_md("\nSuccessfully updated rod extensions with offset: {:.2f}".format(user_offset))
        
    except Exception as ex:
        t.RollBack()
        output.print_md("\nError setting rod extensions: {}".format(str(ex)))

def print_results(output, accessories):
    """Format and print results to output window"""
    output.print_md("# Pipe Accessories Information")
    output.print_md("---")
    
    if not accessories:
        output.print_md("No accessories found with Rod Extension parameter.")
        return
        
    # Print each accessory's information
    for acc in accessories:
        # Get location
        location = acc.Location
        elevation = location.Point.Z if location else 0.0
        
        # Get rod extension parameter
        rod_param = acc.LookupParameter("Rod Extn Above")
        rod_value = rod_param.AsDouble() if (rod_param and rod_param.HasValue) else "No Value"
        
        output.print_md(
            "* **ID**: {0}\n"
            "  * Elevation: {1:.2f}\n"
            "  * Rod Extension: {2}".format(
                acc.Id,
                elevation,
                rod_value
            )
        )
    
    output.print_md("\n**Total Found: " + str(len(accessories)) + "**")

def main():
    """Main execution function"""
    output = setup_output()
    
    try:
        doc, active_view = get_active_document_and_view()
        reference = prompt_for_reference()
        accessories = collect_pipe_accessories(doc, active_view.Id, reference)
        processed_accessories = process_accessories(doc, accessories)
        
        # Calculate elevation differences
        differences = calculate_elevation_differences(doc, reference, processed_accessories)
        
        # print_results(output, processed_accessories)
        
    except Exception as ex:
        forms.alert("An error occurred: " + str(ex), exitscript=True)

if __name__ == "__main__":
    main()