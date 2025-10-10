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

def get_support_disciplines():
    """Get all unique Support Discipline values from pipe accessories in current view"""
    support_disciplines = set()
    
    # Get all pipe accessories in current view
    collector = FilteredElementCollector(doc, active_view.Id)
    pipe_accessories = collector.OfCategory(BuiltInCategory.OST_PipeAccessory).WhereElementIsNotElementType().ToElements()
    
    for accessory in pipe_accessories:
        try:
            # Try to get Support Discipline parameter
            support_discipline = None
            
            # Method 1: Try by parameter name
            try:
                for param in accessory.Parameters:
                    param_name = param.Definition.Name
                    if param_name == "Support Discipline" and param.HasValue:
                        if param.StorageType == StorageType.String:
                            support_discipline = param.AsString()
                            break
            except Exception as e:
                pass
            
            if support_discipline and support_discipline.strip():
                support_disciplines.add(support_discipline)
                
        except Exception as e:
            continue
    
    return list(support_disciplines)

def create_support_filter(filter_name, support_discipline_value):
    """Create a view filter for pipe accessories based on Support Discipline parameter"""
    
    # Create filter categories - only pipe accessories
    categories = List[ElementId]()
    categories.Add(Category.GetCategory(doc, BuiltInCategory.OST_PipeAccessory).Id)
    
    # Create parameter filter rule using string comparison with support discipline value
    # We need to find the parameter definition for Support Discipline
    # Since it's likely a shared parameter, we'll use a more flexible approach
    
    # Get a sample pipe accessory to find the parameter definition
    collector = FilteredElementCollector(doc)
    sample_accessory = collector.OfCategory(BuiltInCategory.OST_PipeAccessory).WhereElementIsNotElementType().FirstElement()
    
    support_param_def = None
    if sample_accessory:
        for param in sample_accessory.Parameters:
            if param.Definition.Name == "Support Discipline":
                support_param_def = param.Definition
                break
    
    if support_param_def:
        provider = ParameterValueProvider(support_param_def.Id)
        evaluator = FilterStringEquals()
        rule_value = support_discipline_value
        rule = FilterStringRule(provider, evaluator, rule_value)
        
        param_filter = ElementParameterFilter(rule)
        
        # Create the view filter
        view_filter = ParameterFilterElement.Create(doc, filter_name, categories, param_filter)
        
        return view_filter
    
    return None

def create_blank_system_filter(filter_name, category_ids, is_piping=True):
    """Create a view filter for elements with blank/empty system type"""
    
    # Create filter categories
    categories = List[ElementId]()
    for category_id in category_ids:
        categories.Add(category_id)
    
    # Create parameter filter rule for blank/empty values
    system_type_param_id = ElementId(BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
    if not is_piping:
        system_type_param_id = ElementId(BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM)
    
    provider = ParameterValueProvider(system_type_param_id)
    evaluator = FilterStringEquals()
    rule_value = ""  # Empty string for blank values
    rule = FilterStringRule(provider, evaluator, rule_value)
    
    param_filter = ElementParameterFilter(rule)
    
    # Create the view filter
    view_filter = ParameterFilterElement.Create(doc, filter_name, categories, param_filter)
    
    return view_filter

def create_blank_support_filter(filter_name):
    """Create a view filter for pipe accessories with blank Support Discipline parameter"""
    
    # Create filter categories - only pipe accessories
    categories = List[ElementId]()
    categories.Add(Category.GetCategory(doc, BuiltInCategory.OST_PipeAccessory).Id)
    
    # Get a sample pipe accessory to find the parameter definition
    collector = FilteredElementCollector(doc)
    sample_accessory = collector.OfCategory(BuiltInCategory.OST_PipeAccessory).WhereElementIsNotElementType().FirstElement()
    
    support_param_def = None
    if sample_accessory:
        for param in sample_accessory.Parameters:
            if param.Definition.Name == "Support Discipline":
                support_param_def = param.Definition
                break
    
    if support_param_def:
        provider = ParameterValueProvider(support_param_def.Id)
        evaluator = FilterStringEquals()
        rule_value = ""  # Empty string for blank values
        rule = FilterStringRule(provider, evaluator, rule_value)
        
        param_filter = ElementParameterFilter(rule)
        
        # Create the view filter
        view_filter = ParameterFilterElement.Create(doc, filter_name, categories, param_filter)
        
        return view_filter
    
    return None

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
        
        # Get support disciplines
        support_disciplines = get_support_disciplines()
        
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
        
        # Create filters for support disciplines
        for support_discipline in support_disciplines:
            filter_name = "Support - " + support_discipline
            try:
                if filter_name in existing_filters:
                    # Use existing filter
                    view_filter = existing_filters[filter_name]
                else:
                    # Create new filter
                    view_filter = create_support_filter(filter_name, support_discipline)
                
                if view_filter:
                    created_filters.append((view_filter, support_discipline, support_discipline))
            except Exception as e:
                print("Error processing support filter " + filter_name + ": " + str(e))
        
        # Create filters for blank/empty values
        # Blank piping system filter
        blank_pipe_filter_name = "Pipe System - (Blank)"
        try:
            if blank_pipe_filter_name in existing_filters:
                view_filter = existing_filters[blank_pipe_filter_name]
            else:
                view_filter = create_blank_system_filter(blank_pipe_filter_name, pipe_category_ids, is_piping=True)
            
            if view_filter:
                created_filters.append((view_filter, "(Blank)", "(Blank)"))
        except Exception as e:
            print("Error processing blank pipe filter: " + str(e))
        
        # Blank duct system filter
        blank_duct_filter_name = "Duct System - (Blank)"
        try:
            if blank_duct_filter_name in existing_filters:
                view_filter = existing_filters[blank_duct_filter_name]
            else:
                view_filter = create_blank_system_filter(blank_duct_filter_name, duct_category_ids, is_piping=False)
            
            if view_filter:
                created_filters.append((view_filter, "(Blank)", "(Blank)"))
        except Exception as e:
            print("Error processing blank duct filter: " + str(e))
        
        # Blank support discipline filter
        blank_support_filter_name = "Support - (Blank)"
        try:
            if blank_support_filter_name in existing_filters:
                view_filter = existing_filters[blank_support_filter_name]
            else:
                view_filter = create_blank_support_filter(blank_support_filter_name)
            
            if view_filter:
                created_filters.append((view_filter, "(Blank)", "(Blank)"))
        except Exception as e:
            print("Error processing blank support filter: " + str(e))
        
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
                if view_filter.Name.startswith("Support - "):
                    # For support filters, match visibility to system abbreviation selection
                    if selected_system_abbreviations is not None:
                        # Support discipline should match system abbreviation, or show blank if no match
                        if system_abbreviation in selected_system_abbreviations or system_abbreviation == "(Blank)":
                            active_view.SetFilterVisibility(view_filter.Id, True)
                        else:
                            active_view.SetFilterVisibility(view_filter.Id, False)
                    else:
                        # No selection, make all support filters visible
                        active_view.SetFilterVisibility(view_filter.Id, True)
                else:
                    # Set filter visibility based on selection for system filters
                    if selected_system_abbreviations is not None:
                        # Show blank filters when there's a selection (to see unassigned elements)
                        if system_abbreviation in selected_system_abbreviations or system_abbreviation == "(Blank)":
                            active_view.SetFilterVisibility(view_filter.Id, True)
                        else:
                            active_view.SetFilterVisibility(view_filter.Id, False)
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
