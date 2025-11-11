from pyrevit import revit, DB, script, forms
from Autodesk.Revit.UI.Selection import ObjectType
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

def prompt_for_geometry_selection():
    """Prompt user to select geometry (face, edge, or point) in the model"""
    output = script.get_output()
    
    # First, let user choose what type of geometry to select
    selection_options = ['Face', 'Edge', 'Point on Element', 'Reference (Level/Plane)']
    
    selected_type = forms.CommandSwitchWindow.show(
        selection_options,
        message='What type of geometry do you want to select?'
    )
    
    if not selected_type:
        return None, None
    
    doc = revit.doc
    uidoc = revit.uidoc
    
    try:
        if selected_type == 'Reference (Level/Plane)':
            # Use existing reference selection function
            return prompt_for_reference(), 'reference'
            
        elif selected_type == 'Face':
            output.print_md("Please select a face in the model...")
            face_ref = uidoc.Selection.PickObject(
                ObjectType.Face,
                "Select a face"
            )
            element = doc.GetElement(face_ref.ElementId)
            face = element.GetGeometryObjectFromReference(face_ref)
            
            # Get a point on the face using the picked point
            try:
                # Use the GlobalPoint from the reference which represents the picked point
                if hasattr(face_ref, 'GlobalPoint'):
                    face_point = face_ref.GlobalPoint
                    #output.print_md("Using picked point on face: X={:.2f}, Y={:.2f}, Z={:.2f}".format(
                    #    face_point.X, face_point.Y, face_point.Z))
                else:
                    # Fallback: try to evaluate face at center
                    if hasattr(face, 'Evaluate'):
                        # Get face bounds and evaluate at center
                        bbox = face.GetBoundingBox()
                        if bbox and hasattr(bbox, 'Min') and hasattr(bbox, 'Max'):
                            center_uv = DB.UV((bbox.Min.U + bbox.Max.U) / 2, (bbox.Min.V + bbox.Max.V) / 2)
                            face_point = face.Evaluate(center_uv)
                        else:
                            face_point = face.Evaluate(DB.UV(0.5, 0.5))
                    else:
                        # Final fallback: use element location
                        face_point = element.Location.Point if element.Location else DB.XYZ.Zero
                        
            except Exception as face_ex:
                output.print_md("Warning evaluating face: {}".format(str(face_ex)))
                # Use element location as fallback
                if element.Location and hasattr(element.Location, 'Point'):
                    face_point = element.Location.Point
                elif element.Location and hasattr(element.Location, 'Curve'):
                    face_point = element.Location.Curve.GetEndPoint(0)
                else:
                    face_point = DB.XYZ.Zero
                
            return {'type': 'face', 'element': element, 'face': face, 'point': face_point, 'reference': face_ref}, 'geometry'
            
        elif selected_type == 'Edge':
            output.print_md("Please select an edge in the model...")
            edge_ref = uidoc.Selection.PickObject(
                ObjectType.Edge,
                "Select an edge"
            )
            element = doc.GetElement(edge_ref.ElementId)
            edge = element.GetGeometryObjectFromReference(edge_ref)
            
            # Get point on the edge using the picked point
            try:
                # Use the GlobalPoint from the reference which represents the picked point
                if hasattr(edge_ref, 'GlobalPoint'):
                    edge_point = edge_ref.GlobalPoint
                    #output.print_md("Using picked point on edge: X={:.2f}, Y={:.2f}, Z={:.2f}".format(
                    #    edge_point.X, edge_point.Y, edge_point.Z))
                else:
                    # Fallback: try to get edge midpoint
                    if hasattr(edge, 'Evaluate'):
                        edge_point = edge.Evaluate(0.5, True)  # Evaluate at parameter 0.5 (midpoint)
                    elif hasattr(edge, 'GetEndPoint'):
                        # Calculate midpoint from endpoints
                        start_point = edge.GetEndPoint(0)
                        end_point = edge.GetEndPoint(1)
                        edge_point = DB.XYZ(
                            (start_point.X + end_point.X) / 2,
                            (start_point.Y + end_point.Y) / 2,
                            (start_point.Z + end_point.Z) / 2
                        )
                    elif hasattr(edge, 'AsCurve'):
                        # Try to get curve and evaluate at midpoint
                        curve = edge.AsCurve()
                        edge_point = curve.Evaluate(0.5, True)
                    else:
                        # Final fallback: use element location
                        edge_point = element.Location.Point if element.Location else DB.XYZ.Zero
                        
            except Exception as edge_ex:
                output.print_md("Warning evaluating edge: {}".format(str(edge_ex)))
                # Use element location as fallback
                if element.Location and hasattr(element.Location, 'Point'):
                    edge_point = element.Location.Point
                elif element.Location and hasattr(element.Location, 'Curve'):
                    edge_point = element.Location.Curve.Evaluate(0.5, True)
                else:
                    edge_point = DB.XYZ.Zero
                
            return {'type': 'edge', 'element': element, 'edge': edge, 'point': edge_point, 'reference': edge_ref}, 'geometry'
            
        elif selected_type == 'Point on Element':
            output.print_md("Please select a point on an element...")
            point_ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                "Select an element to get its location point"
            )
            element = doc.GetElement(point_ref.ElementId)
            
            # Get element location point
            if element.Location:
                if hasattr(element.Location, 'Point'):
                    element_point = element.Location.Point
                elif hasattr(element.Location, 'Curve'):
                    # For linear elements, get midpoint of curve
                    curve = element.Location.Curve
                    element_point = curve.Evaluate(0.5, True)
                else:
                    element_point = DB.XYZ.Zero
            else:
                element_point = DB.XYZ.Zero
                
            return {'type': 'point', 'element': element, 'point': element_point, 'reference': point_ref}, 'geometry'
            
    except Exception as ex:
        output.print_md("Selection cancelled or failed: {}".format(str(ex)))
        return None, None
    
    return None, None

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

def collect_pipe_accessories(doc, view_id, reference_data, reference_type):
    """Collect all pipe accessories from the active view"""
    output = script.get_output()  # Debug output
    
    collector = (DB.FilteredElementCollector(doc, view_id)
                .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
                .WhereElementIsNotElementType())
    
    # Get all elements
    all_elements = collector.ToElements()
    # output.print_md("Total accessories found: {}".format(len(all_elements)))
    
    if reference_type == 'geometry':
        output.print_md("Using geometry reference: {} on Element ID {}".format(
            reference_data['type'], reference_data['element'].Id))
    
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

def calculate_elevation_differences(doc, reference_data, reference_type, filtered_elements):
    """Calculate elevation differences accounting for different reference types"""
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

    # Handle different reference types
    if reference_type == 'reference':
        # Original level/reference plane logic
        reference_element = reference_data
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
    elif reference_type == 'geometry':
        # New geometry-based reference
        is_sloped = False
        ref_elevation = reference_data['point'].Z + base_point_elevation
        #output.print_md("Using geometry reference point at elevation: {:.2f}".format(ref_elevation))
    
    differences = []
    for element in filtered_elements:
        location = element.Location
        if location:
            element_point = location.Point
            
            if reference_type == 'reference' and is_sloped:
                # Original sloped reference plane logic
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
                    current_ref_elevation = bubble_point.Z + (t * slope_vector.Z)
                else:
                    current_ref_elevation = bubble_point.Z
            else:
                # For geometry references or non-sloped references, use the same elevation
                current_ref_elevation = ref_elevation
            
            elevation_diff = (current_ref_elevation - element_point.Z)
            
            differences.append({
                'element_id': element.Id,
                'element_xyz': (element_point.X, element_point.Y, element_point.Z),
                'reference_z': current_ref_elevation,
                'difference': elevation_diff
            })
    
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
                    
            offset_param = element.LookupParameter("Offset")
            horiz_offset_param = element.LookupParameter("Horizontal Rod Offset")
            rod_extn_param = element.LookupParameter("Rod Extn Above")
            deduct_param = element.LookupParameter("LengthtobeDeducted")

            
            if not rod_extn_param:
                output.print_md("* Missing Rod Extension parameter for Element ID: {}".format(element.Id))
                continue
                
            offset = deduct_param.AsDouble() if (deduct_param and deduct_param.HasValue) else 0 #Using LengthtobeDeducted instead of offset and horiz rod offset
            #horiz_offset = horiz_offset_param.AsDouble() if (horiz_offset_param and horiz_offset_param.HasValue) else 0
            new_extension = diff['difference'] - offset + (user_offset)
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
        
        # Get reference selection (geometry or traditional reference)
        reference_data, reference_type = prompt_for_geometry_selection()
        
        if not reference_data:
            output.print_md("No reference selected. Script cancelled.")
            return
            
        accessories = collect_pipe_accessories(doc, active_view.Id, reference_data, reference_type)
        processed_accessories = process_accessories(doc, accessories)
        
        # Calculate elevation differences
        differences = calculate_elevation_differences(doc, reference_data, reference_type, processed_accessories)
        
        # print_results(output, processed_accessories)
        
    except Exception as ex:
        forms.alert("An error occurred: " + str(ex), exitscript=True)

if __name__ == "__main__":
    main()