from pyrevit import revit, DB, script, forms


def _is_nonzero(value, tol=1e-9):
    return abs(value) > tol


def _is_select_upper_attachment_six(element):
    """Return True when Select Upper Attachment resolves to value 6."""
    param = element.LookupParameter("Select Upper Attachment")
    if not param or not param.HasValue:
        return False

    st = param.StorageType

    if st == DB.StorageType.Integer:
        return param.AsInteger() == 6

    if st == DB.StorageType.Double:
        return abs(param.AsDouble() - 6.0) < 1e-9

    if st == DB.StorageType.ElementId:
        elem_id = param.AsElementId()
        return elem_id and elem_id.IntegerValue == 6

    for raw_value in [param.AsValueString(), param.AsString()]:
        if raw_value:
            text = raw_value.strip()
            try:
                return abs(float(text) - 6.0) < 1e-9
            except Exception:
                if text == "6":
                    return True

    return False


def prompt_reset_added_rod_extension(doc, elements):
    """Optionally reset Added Rod Extension to 0 when non-zero values are found."""
    elements_with_nonzero = []
    for element in elements:
        param = element.LookupParameter("Added Rod Extension")
        if param and param.HasValue and not param.IsReadOnly and param.StorageType == DB.StorageType.Double:
            if _is_nonzero(param.AsDouble()):
                elements_with_nonzero.append((element, param))

    if not elements_with_nonzero:
        return

    should_reset = forms.alert(
        "Found {0} hanger(s) with non-zero 'Added Rod Extension'.\n\nDo you want to set 'Added Rod Extension' to 0 before continuing?".format(len(elements_with_nonzero)),
        yes=True,
        no=True,
        exitscript=False
    )

    if not should_reset:
        return

    t = DB.Transaction(doc, "Reset Added Rod Extension")
    t.Start()
    try:
        for _, param in elements_with_nonzero:
            param.Set(0.0)
        t.Commit()
    except Exception:
        t.RollBack()
        raise

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
    """Get reference elevation from selected trapezes, or all in view if none selected."""
    doc = revit.doc
    active_view = doc.ActiveView
    
    # Collect pipe accessories in active view
    accessories = (DB.FilteredElementCollector(doc, active_view.Id)
                  .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
                  .WhereElementIsNotElementType()
                  .ToElements())
    
    # Find all trapezes and their elevations
    all_trapezes = []
    elevations = set()
    
    for acc in accessories:
        type_elem = doc.GetElement(acc.GetTypeId())
        family_name = type_elem.FamilyName.lower() if (type_elem and type_elem.FamilyName) else ""
        if "trapeze" in family_name or "unistrut_spanner" in family_name:
            location = acc.Location
            if location:
                all_trapezes.append(acc)

    if not all_trapezes:
        forms.alert("No trapeze hangers found in view", exitscript=True)
        return None, None

    selected_ids = set(revit.uidoc.Selection.GetElementIds())
    selected_trapezes = [trap for trap in all_trapezes if trap.Id in selected_ids]

    trapezes = selected_trapezes if selected_trapezes else all_trapezes

    for trap in trapezes:
        location = trap.Location
        if location:
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
    """Collect selected hangers, or optionally all hangers in active view."""
    collector = (DB.FilteredElementCollector(doc, view_id)
                .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
                .WhereElementIsNotElementType())

    all_elements = list(collector.ToElements())
    visible_hangers = [acc for acc in all_elements if acc.LookupParameter("Rod Extn Above")]

    if not visible_hangers:
        forms.alert("No hangers with 'Rod Extn Above' were found in the active view.", exitscript=True)
        return []

    selected_ids = set(revit.uidoc.Selection.GetElementIds())
    selected_hangers = [hanger for hanger in visible_hangers if hanger.Id in selected_ids]

    if selected_hangers:
        target_hangers = selected_hangers
    else:
        process_all = forms.alert(
            "No hangers are selected.\n\nDo you want to process all {0} hangers in the active view?".format(len(visible_hangers)),
            yes=True,
            no=True,
            exitscript=False
        )

        if process_all:
            target_hangers = visible_hangers
        else:
            forms.alert("No hangers selected. Script cancelled.", exitscript=True)
            return []

    filtered_hangers = [h for h in target_hangers if _is_select_upper_attachment_six(h)]
    if not filtered_hangers:
        forms.alert(
            "No selected/in-view hangers had 'Select Upper Attachment' set to 6.",
            exitscript=True
        )
        return []

    return filtered_hangers

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
            deduct_param = element.LookupParameter("LengthtobeDeducted")
            rod_extn_param = element.LookupParameter("Rod Extn Above")
            
            if not rod_extn_param:
                output.print_md("* Missing Rod Extn Above parameter for Element ID: {}".format(element.Id))
                continue
            
            # Use Offset and Horizontal Rod Offset if available, otherwise use LengthtobeDeducted
            if offset_param or horiz_offset_param:
                offset = offset_param.AsDouble() if (offset_param and offset_param.HasValue) else 0
                horiz_offset = horiz_offset_param.AsDouble() if (horiz_offset_param and horiz_offset_param.HasValue) else 0
                new_extension = diff['difference'] - offset - horiz_offset
            else:
                deduct_value = deduct_param.AsDouble() if (deduct_param and deduct_param.HasValue) else 0
                new_extension = diff['difference'] - deduct_value
                
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
        prompt_reset_added_rod_extension(doc, accessories)
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