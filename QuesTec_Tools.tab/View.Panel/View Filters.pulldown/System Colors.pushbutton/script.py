
"""
Create view filters for all piping and duct system types
with solid color overrides based on system line colors.
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

def get_system_types():
    """Get all piping and duct system types with their properties"""
    collector = FilteredElementCollector(doc)
    system_types = collector.OfClass(MEPSystemType).ToElements()
    
    piping_systems = []
    duct_systems = []
    
    for system_type in system_types:
        try:
            # Get system abbreviation and line color with error handling
            try:
                abbreviation = system_type.Abbreviation
            except:
                abbreviation = ""
            
            try:
                line_color = system_type.LineColor
            except:
                line_color = Color.Black
            
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
                        
                # Debug output
                # print("System Type ID: " + str(system_type.Id.IntegerValue) + ", Type Name: '" + str(name) + "', Abbreviation: '" + str(abbreviation) + "'")
                        
            except Exception as e:
                # print("Error getting name for system type " + str(system_type.Id.IntegerValue) + ": " + str(e))
                name = "Unknown"
            
            # Check the type to determine if it's piping or duct
            type_name = system_type.GetType().Name
            
            if type_name == "PipingSystemType":
                piping_systems.append({
                    'name': name,
                    'abbreviation': abbreviation,
                    'color': line_color,
                    'element_id': system_type.Id
                })
            elif type_name == "MechanicalSystemType":
                duct_systems.append({
                    'name': name,
                    'abbreviation': abbreviation,
                    'color': line_color,
                    'element_id': system_type.Id
                })
        except Exception as e:
            print("Error processing system type: " + str(e))
            continue
    
    return piping_systems, duct_systems

def create_view_filter(filter_name, category_id, system_type_name, color):
    """Create a view filter with the specified parameters"""
    
    # Create filter categories
    categories = List[ElementId]()
    categories.Add(category_id)
    
    # Create parameter filter rule using string comparison with system type name
    system_type_param_id = ElementId(BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
    if category_id == Category.GetCategory(doc, BuiltInCategory.OST_DuctCurves).Id:
        system_type_param_id = ElementId(BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM)
    
    provider = ParameterValueProvider(system_type_param_id)
    evaluator = FilterStringEquals()
    rule_value = system_type_name
    rule = FilterStringRule(provider, evaluator, rule_value)
    
    # print("Creating filter rule: System Type equals '" + str(rule_value) + "'")  # Debug output
    
    param_filter = ElementParameterFilter(rule)
    
    # Create the view filter
    view_filter = ParameterFilterElement.Create(doc, filter_name, categories, param_filter)
    
    # Create override graphics settings with solid color
    override_settings = OverrideGraphicSettings()
    
    # Create fill pattern (solid)
    try:
        solid_pattern_id = FillPatternElement.GetFillPatternElementByName(doc, FillPatternTarget.Drafting, "<Solid fill>").Id
    except:
        # Try alternative solid pattern name
        try:
            solid_pattern_id = FillPatternElement.GetFillPatternElementByName(doc, FillPatternTarget.Drafting, "Solid fill").Id
        except:
            # If no solid pattern found, use no pattern
            solid_pattern_id = ElementId.InvalidElementId
    
    # Set surface foreground pattern override
    override_settings.SetSurfaceForegroundPatternId(solid_pattern_id)
    override_settings.SetSurfaceForegroundPatternColor(color)
    
    return view_filter, override_settings

def main():
    """Main function to create filters and apply to active view"""
    
    # Start transaction
    transaction = Transaction(doc, "Create System Type View Filters")
    transaction.Start()
    
    try:
        # Get all system types
        piping_systems, duct_systems = get_system_types()
        
        # Get category IDs
        pipe_category_id = Category.GetCategory(doc, BuiltInCategory.OST_PipeCurves).Id
        duct_category_id = Category.GetCategory(doc, BuiltInCategory.OST_DuctCurves).Id
        
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
                # print("Skipping piping system with no abbreviation - Name: '" + system['name'] + "'")
                continue
                
            # Use system type name in filter name
            filter_name = "Pipe - " + system['abbreviation'] + " - " + system['name']
            # print("Processing piping system - Name: '" + system['name'] + "', Abbreviation: '" + system['abbreviation'] + "', Filter Name: '" + filter_name + "'")
            try:
                if filter_name in existing_filters:
                    # Use existing filter
                    view_filter = existing_filters[filter_name]
                    override_settings = OverrideGraphicSettings()
                    
                    # Create fill pattern (solid)
                    try:
                        solid_pattern_id = FillPatternElement.GetFillPatternElementByName(doc, FillPatternTarget.Drafting, "<Solid fill>").Id
                    except:
                        try:
                            solid_pattern_id = FillPatternElement.GetFillPatternElementByName(doc, FillPatternTarget.Drafting, "Solid fill").Id
                        except:
                            solid_pattern_id = ElementId.InvalidElementId
                    
                    override_settings.SetSurfaceForegroundPatternId(solid_pattern_id)
                    override_settings.SetSurfaceForegroundPatternColor(system['color'])
                    
                    # print("Found existing piping filter: " + filter_name)
                else:
                    # Create new filter
                    view_filter, override_settings = create_view_filter(
                        filter_name, 
                        pipe_category_id, 
                        system['name'], 
                        system['color']
                    )
                    # print("Created new piping filter: " + filter_name)
                
                created_filters.append((view_filter, override_settings))
            except Exception as e:
                print("Error processing piping filter " + filter_name + ": " + str(e))
        
        # Create or find filters for duct systems
        for system in duct_systems:
            # Skip systems without abbreviations
            if not system['abbreviation'] or system['abbreviation'].strip() == "":
                # print("Skipping duct system with no abbreviation - Name: '" + system['name'] + "'")
                continue
                
            # Use system type name in filter name
            filter_name = "Duct - " + system['abbreviation'] + " - " + system['name']
            # print("Processing duct system - Name: '" + system['name'] + "', Abbreviation: '" + system['abbreviation'] + "', Filter Name: '" + filter_name + "'")
            try:
                if filter_name in existing_filters:
                    # Use existing filter
                    view_filter = existing_filters[filter_name]
                    override_settings = OverrideGraphicSettings()
                    
                    # Create fill pattern (solid)
                    try:
                        solid_pattern_id = FillPatternElement.GetFillPatternElementByName(doc, FillPatternTarget.Drafting, "<Solid fill>").Id
                    except:
                        try:
                            solid_pattern_id = FillPatternElement.GetFillPatternElementByName(doc, FillPatternTarget.Drafting, "Solid fill").Id
                        except:
                            solid_pattern_id = ElementId.InvalidElementId
                    
                    override_settings.SetSurfaceForegroundPatternId(solid_pattern_id)
                    override_settings.SetSurfaceForegroundPatternColor(system['color'])
                    
                    # print("Found existing duct filter: " + filter_name)
                else:
                    # Create new filter
                    view_filter, override_settings = create_view_filter(
                        filter_name, 
                        duct_category_id, 
                        system['name'], 
                        system['color']
                    )
                    # print("Created new duct filter: " + filter_name)
                
                created_filters.append((view_filter, override_settings))
            except Exception as e:
                print("Error processing duct filter " + filter_name + ": " + str(e))
        
        # Apply all filters to the active view
        for view_filter, override_settings in created_filters:
            try:
                active_view.AddFilter(view_filter.Id)
                active_view.SetFilterOverrides(view_filter.Id, override_settings)
                #print("Applied filter to view: " + view_filter.Name)
            except Exception as e:
                print("Error applying filter " + view_filter.Name + " to view: " + str(e))
        
        # Commit transaction
        transaction.Commit()
        
        #print("Successfully created and applied " + str(len(created_filters)) + " view filters")
        
    except Exception as e:
        transaction.RollBack()
        print("Error in main execution: " + str(e))
        raise

# Run the script
if __name__ == "__main__":
    main()