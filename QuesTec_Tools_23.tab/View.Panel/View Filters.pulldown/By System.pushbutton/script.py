"""
Create view filters for all piping and duct system types
without color overrides - for visibility control only.
If elements are selected, only show filters for those system types.
Shift-click to remove all system type view filters
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from System.Collections.Generic import List

# Get current document and active view
doc = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView
uidoc = __revit__.ActiveUIDocument

def get_selected_system_types():
    """Get system type names from selected elements"""
    selected_system_abbreviations = set()
    
    # Get selected element IDs
    selected_ids = uidoc.Selection.GetElementIds()
    
    if not selected_ids or len(selected_ids) == 0:
        print("No elements selected")
        return None  # No selection
    
    #print("Found " + str(len(selected_ids)) + " selected elements")
    
    for element_id in selected_ids:
        try:
            element = doc.GetElement(element_id)
            #print("Processing element: " + str(element.Category.Name) + " - ID: " + str(element.Id.IntegerValue))
            
            # Try to get system abbreviation (which we can see in the output)
            system_abbreviation = None
            
            # Method 1: Try System Abbreviation parameter
            try:
                abbrev_param = element.get_Parameter(BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM)
                if abbrev_param and abbrev_param.HasValue:
                    system_abbreviation = abbrev_param.AsString()
                    #print("  Found system abbreviation: " + system_abbreviation)
            except Exception as e:
                print("  Method 1 error: " + str(e))
            
            # Method 2: Try to find system abbreviation in parameters by name
            if not system_abbreviation:
                try:
                    for param in element.Parameters:
                        param_name = param.Definition.Name
                        if param_name == "System Abbreviation" and param.HasValue:
                            if param.StorageType == StorageType.String:
                                system_abbreviation = param.AsString()
                                #print("  Found system abbreviation (method 2): " + system_abbreviation)
                                break
                except Exception as e:
                    print("  Method 2 error: " + str(e))
            
            if system_abbreviation and system_abbreviation.strip():
                selected_system_abbreviations.add(system_abbreviation)
            else:
                print("  No system abbreviation found for this element")
                    
        except Exception as e:
            print("  Error processing element: " + str(e))
            continue
    
    if selected_system_abbreviations:
        #print("Selected system abbreviations: " + ", ".join(selected_system_abbreviations))
        return selected_system_abbreviations
    else:
        #print("No system abbreviations found in selected elements")
        return None

def get_system_types():
    """Get all piping and duct system types with their properties"""
    collector = FilteredElementCollector(doc)
    system_types = collector.OfClass(MEPSystemType).ToElements()
    
    piping_systems = []
    duct_systems = []
    
    for system_type in system_types:
        try:
            # Get system abbreviation with error handling
            try:
                abbreviation = system_type.Abbreviation
            except:
                abbreviation = ""
            
            # Get the actual system type name that will be used in filters
            name = "Unknown"
            try:
                # For piping and duct system types, get the type name parameter
                type_name_param = system_type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                if type_name_param and type_name_param.HasValue:
                    name = type_name_param.AsString()
                else:
                    # Try symbol name parameter
                    name_param = system_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                    if name_param and name_param.HasValue:
                        name = name_param.AsString()
                    else:
                        # Fall back to element name
                        name = system_type.Name
                        
            except Exception as e:
                name = "Unknown"
            
            # Check the type to determine if it's piping or duct
            type_name = system_type.GetType().Name
            
            if type_name == "PipingSystemType":
                piping_systems.append({
                    'name': name,
                    'abbreviation': abbreviation,
                    'element_id': system_type.Id
                })
            elif type_name == "MechanicalSystemType":
                duct_systems.append({
                    'name': name,
                    'abbreviation': abbreviation,
                    'element_id': system_type.Id
                })
        except Exception as e:
            print("Error processing system type: " + str(e))
            continue
    
    return piping_systems, duct_systems

def create_view_filter(filter_name, category_ids, system_type_name, is_piping=True):
    """Create a view filter with the specified parameters (no color override)"""
    
    # Create filter categories
    categories = List[ElementId]()
    for category_id in category_ids:
        categories.Add(category_id)
    
    # Create parameter filter rule using string comparison with system type name
    system_type_param_id = ElementId(BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
    if not is_piping:
        system_type_param_id = ElementId(BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM)
    
    provider = ParameterValueProvider(system_type_param_id)
    evaluator = FilterStringEquals()
    rule_value = system_type_name
    rule = FilterStringRule(provider, evaluator, rule_value)
    
    param_filter = ElementParameterFilter(rule)
    
    # Create the view filter
    view_filter = ParameterFilterElement.Create(doc, filter_name, categories, param_filter)
    
    return view_filter

def main():
    """Main function to create filters and apply to active view"""
    
    # Get selected system abbreviations before starting transaction
    selected_system_abbreviations = get_selected_system_types()
    
    # Start transaction
    transaction = Transaction(doc, "Create System Type View Filters")
    transaction.Start()
    
    try:
        # Get all system types
        piping_systems, duct_systems = get_system_types()
        
        # Get category IDs for piping systems
        pipe_category_ids = [
            Category.GetCategory(doc, BuiltInCategory.OST_PipeCurves).Id,
            Category.GetCategory(doc, BuiltInCategory.OST_PipeFitting).Id,
            Category.GetCategory(doc, BuiltInCategory.OST_PipeAccessory).Id,
            Category.GetCategory(doc, BuiltInCategory.OST_PlumbingFixtures).Id
        ]
        
        # Get category IDs for duct systems
        duct_category_ids = [
            Category.GetCategory(doc, BuiltInCategory.OST_DuctCurves).Id,
            Category.GetCategory(doc, BuiltInCategory.OST_DuctFitting).Id,
            Category.GetCategory(doc, BuiltInCategory.OST_DuctAccessory).Id,
            Category.GetCategory(doc, BuiltInCategory.OST_DuctTerminal).Id,
            Category.GetCategory(doc, BuiltInCategory.OST_FlexDuctCurves).Id
        ]
        
        created_filters = []
        
        # Get existing filters in the document
        existing_filters = {}
        collector = FilteredElementCollector(doc)
        all_filters = collector.OfClass(ParameterFilterElement).ToElements()
        for filter_element in all_filters:
            existing_filters[filter_element.Name] = filter_element

        # Create or find filters for piping systems
        for system in piping_systems:
            # Skip systems without abbreviations
            if not system['abbreviation'] or system['abbreviation'].strip() == "":
                continue
                
            # Use system type name in filter name
            filter_name = "Pipe System - " + system['abbreviation'] + " - " + system['name']
            try:
                if filter_name in existing_filters:
                    # Use existing filter
                    view_filter = existing_filters[filter_name]
                else:
                    # Create new filter
                    view_filter = create_view_filter(
                        filter_name, 
                        pipe_category_ids, 
                        system['name'],
                        is_piping=True
                    )
                
                created_filters.append((view_filter, system['name'], system['abbreviation']))
            except Exception as e:
                print("Error processing piping filter " + filter_name + ": " + str(e))
        
        # Create or find filters for duct systems
        for system in duct_systems:
            # Skip systems without abbreviations
            if not system['abbreviation'] or system['abbreviation'].strip() == "":
                continue
                
            # Use system type name in filter name
            filter_name = "Duct System - " + system['abbreviation'] + " - " + system['name']
            try:
                if filter_name in existing_filters:
                    # Use existing filter
                    view_filter = existing_filters[filter_name]
                else:
                    # Create new filter
                    view_filter = create_view_filter(
                        filter_name, 
                        duct_category_ids, 
                        system['name'],
                        is_piping=False
                    )
                
                created_filters.append((view_filter, system['name'], system['abbreviation']))
            except Exception as e:
                print("Error processing duct filter " + filter_name + ": " + str(e))
        
        # Apply all filters to the active view (without override settings)
        for view_filter, system_name, system_abbreviation in created_filters:
            try:
                # Check if filter is already applied to avoid errors
                try:
                    active_view.AddFilter(view_filter.Id)
                except Exception as add_error:
                    if "already applied" not in str(add_error):
                        print("Error adding filter " + view_filter.Name + " to view: " + str(add_error))
                
                # Set filter visibility based on selection
                if selected_system_abbreviations is not None:
                    if system_abbreviation in selected_system_abbreviations:
                        active_view.SetFilterVisibility(view_filter.Id, True)
                        #print("Made filter visible: " + view_filter.Name)
                    else:
                        active_view.SetFilterVisibility(view_filter.Id, False)
                        #print("Made filter hidden: " + view_filter.Name)
                else:
                    # No selection, make all filters visible
                    active_view.SetFilterVisibility(view_filter.Id, True)
                    
            except Exception as e:
                print("Error processing filter " + view_filter.Name + ": " + str(e))
        
        # Commit transaction
        transaction.Commit()
        
        # Print summary
        if selected_system_abbreviations is not None:
            print("\nSUMMARY: Applied " + str(len(created_filters)) + " filters, showing only filters for selected system abbreviations:")
            for sys_abbrev in selected_system_abbreviations:
                print("  - " + sys_abbrev)
        else:
            print("\nSUMMARY: Applied " + str(len(created_filters)) + " filters, all visible (no selection)")
        
    except Exception as e:
        transaction.RollBack()
        print("Error in main execution: " + str(e))
        raise

# Run the script
if __name__ == "__main__":
    main()
