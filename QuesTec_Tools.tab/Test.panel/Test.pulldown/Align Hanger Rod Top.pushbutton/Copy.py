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
    output.print_md("Total accessories found: {}".format(len(all_elements)))
    
    return all_elements

def process_accessories(doc, accessories):
    """Set Rod Extn Above parameter to 24 for all accessories"""
    output = script.get_output()
    output.print_md("# Setting Rod Extension Above to 24")
    output.print_md("---")
    
    if not accessories:
        output.print_md("No accessories found")
        return []

    # Get project parameter definition
    param_found = False
    binding_map = doc.ParameterBindings
    iterator = binding_map.ForwardIterator()
    while iterator.MoveNext():
        if iterator.Key.Name == "Rod Extn Above":
            param_definition = iterator.Key
            param_found = True
            output.print_md("found project parameter")
            break
    
    if not param_found:
        output.print_md("Could not find Rod Extn Above project parameter")
        return []

    # Start transaction
    t = DB.Transaction(doc, "Set Rod Extension")
    t.Start()
    
    try:
        modified_count = 0
        for acc in accessories:
            # Get parameter by definition
            param = acc.get_Parameter(param_definition.Id)
            if param and param.IsReadOnly == False:
                param.Set(24.0)
                modified_count += 1
                output.print_md("* Modified Element ID: {0}".format(acc.Id))
        
        t.Commit()
        output.print_md("\nSuccessfully modified {0} elements".format(modified_count))
        
    except Exception as ex:
        t.RollBack()
        output.print_md("\nError occurred: {0}".format(str(ex)))
    
    return accessories

def print_results(output, accessories):
    """Format and print results to output window"""
    output.print_md("# Pipe Accessories Information")
    output.print_md("---")
    
    if not accessories:
        output.print_md("No accessories found with Rod Extension parameter.")
        return
        
    # Print each accessory's information
    for acc in accessories:
        output.print_md(
            "* **ID**: {0}\n"
            "  * Elevation: {1:.2f}\n"
            "  * Rod Extension: {2}".format(
                acc['id'],
                acc['elevation'] if isinstance(acc['elevation'], float) else 0.0,
                acc['rod_extension']
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
        print_results(output, processed_accessories)
        
    except Exception as ex:
        forms.alert("An error occurred: " + str(ex), exitscript=True)

if __name__ == "__main__":
    main()