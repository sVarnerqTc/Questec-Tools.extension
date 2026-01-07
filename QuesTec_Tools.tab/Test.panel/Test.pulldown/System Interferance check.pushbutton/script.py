"""Detects clashes between different piping system types."""
__title__ = "Piping System\nClash Detection"
__author__ = "Copilot"

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Plumbing import *
from pyrevit import revit, script, forms
from System.Collections.Generic import List
import traceback

doc = revit.doc
active_view = doc.ActiveView
output = script.get_output()

def get_system_elements():
    """Collect all MEP elements in active view and group by system type."""
    # Get categories we want to check
    categories = [
        BuiltInCategory.OST_PipeCurves,
        BuiltInCategory.OST_PipeFitting,
        BuiltInCategory.OST_PipeAccessory
    ]
    
    # Collect all elements from those categories
    elements = []
    for category in categories:
        collector = FilteredElementCollector(doc, active_view.Id) \
            .OfCategory(category) \
            .WhereElementIsNotElementType() \
            .ToElements()
        elements.extend(collector)
    
    output.print_md("Found {} total elements to check".format(len(elements)))
    
    # Group by system type
    system_elements = {}
    unknown_count = 0
    
    for elem in elements:
        try:
            # Default system name
            system_name = "Unknown System"
            
            # Method 1: Try to get piping system for pipes
            if isinstance(elem, Plumbing.Pipe):
                pipe_system = elem.MEPSystem
                if pipe_system:
                    system_name = pipe_system.Name
            
            # Method 2: Using parameter for all elements
            if system_name == "Unknown System":
                # Try different parameter options
                for param_id in [
                    BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
                    BuiltInParameter.RBS_SYSTEM_NAME_PARAM,
                    BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM
                ]:
                    try:
                        param = elem.get_Parameter(param_id)
                        if param and param.HasValue:
                            if param.StorageType == StorageType.ElementId:
                                type_id = param.AsElementId()
                                if type_id != ElementId.InvalidElementId:
                                    system_type = doc.GetElement(type_id)
                                    if system_type:
                                        system_name = system_type.Name
                                        break
                            elif param.StorageType == StorageType.String:
                                system_name = param.AsString()
                                if system_name:
                                    break
                    except:
                        continue
                        
            # Method 3: For pipe fittings - get connector info
            if system_name == "Unknown System" and hasattr(elem, "ConnectorManager"):
                try:
                    conn_mgr = elem.ConnectorManager
                    if conn_mgr:
                        for conn in conn_mgr.Connectors:
                            if conn.MEPSystem:
                                system_name = conn.MEPSystem.Name
                                break
                except:
                    pass
            
            # Add element to its system group
            if system_name == "Unknown System":
                unknown_count += 1
                
            if system_name not in system_elements:
                system_elements[system_name] = []
                
            system_elements[system_name].append(elem)
            
        except Exception as ex:
            output.print_md("Error processing element {}: {}".format(
                elem.Id.IntegerValue, 
                traceback.format_exc()))
    
    if unknown_count > 0:
        output.print_md("Note: {} elements couldn't be assigned to a specific system".format(unknown_count))
        
    return system_elements

def check_intersection(elem1, elem2):
    """Check if two elements intersect geometrically."""
    # First check bounding boxes for quick rejection
    bb1 = elem1.get_BoundingBox(active_view)
    bb2 = elem2.get_BoundingBox(active_view)
    
    if not bb1 or not bb2:
        return False
        
    # Quick bounding box check
    if not (bb1.Min.X <= bb2.Max.X and bb1.Max.X >= bb2.Min.X and
            bb1.Min.Y <= bb2.Max.Y and bb1.Max.Y >= bb2.Min.Y and
            bb1.Min.Z <= bb2.Max.Z and bb1.Max.Z >= bb2.Min.Z):
        return False
    
    # Detailed geometry check for actual intersections
    try:
        # Get element geometries
        opt = Options()
        opt.DetailLevel = ViewDetailLevel.Fine
        opt.ComputeReferences = True
        
        geom1 = elem1.get_Geometry(opt)
        geom2 = elem2.get_Geometry(opt)
        
        if not geom1 or not geom2:
            return False
            
        # Extract solids from geometry
        solids1 = extract_solids(geom1)
        solids2 = extract_solids(geom2)
        
        # Check all solid combinations for intersections
        for s1 in solids1:
            for s2 in solids2:
                try:
                    result = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if result and result.Volume > 0.0001:  # Small tolerance
                        return True
                except:
                    continue
        
        return False
    except Exception as e:
        output.print_md("Error checking intersection: {}".format(e))
        return False

def extract_solids(geom):
    """Extract solid geometry objects from geometry collection."""
    solids = []
    for geo in geom:
        if isinstance(geo, Solid) and geo.Volume > 0:
            solids.append(geo)
        elif isinstance(geo, GeometryInstance):
            inst_geom = geo.GetInstanceGeometry()
            for inst_solid in inst_geom:
                if isinstance(inst_solid, Solid) and inst_solid.Volume > 0:
                    solids.append(inst_solid)
    return solids

def find_clashes():
    """Find clashes between elements of different system types."""
    output.print_md("### Starting Clash Detection...")
    
    with forms.ProgressBar(title='Collecting systems') as pb:
        system_elements = get_system_elements()
        pb.update_progress(1, 1)
    
    # Show what we found
    output.print_md("Found {} system types:".format(len(system_elements)))
    for system_name, elements in system_elements.items():
        output.print_md("- {}: {} elements".format(system_name, len(elements)))
    
    clashing_elements = set()
    systems = list(system_elements.keys())
    clash_count = 0
    
    # Skip if only one system type
    if len(systems) < 2:
        output.print_md("Not enough system types to compare.")
        return clashing_elements
    
    # Calculate total comparisons for progress tracking
    total_comparisons = 0
    for i in range(len(systems)):
        for j in range(i + 1, len(systems)):
            total_comparisons += len(system_elements[systems[i]]) * len(system_elements[systems[j]])
    
    # Compare systems
    with forms.ProgressBar(title='Checking clashes', cancellable=True) as pb:
        current_comparison = 0
        
        for i in range(len(systems)):
            for j in range(i + 1, len(systems)):
                system1 = systems[i]
                system2 = systems[j]
                
                output.print_md("Comparing '{}' with '{}'...".format(system1, system2))
                
                # Compare elements between the two systems
                for elem1 in system_elements[system1]:
                    for elem2 in system_elements[system2]:
                        current_comparison += 1
                        
                        # Update progress every 10 comparisons
                        if current_comparison % 10 == 0:
                            if pb.cancelled:
                                output.print_md("Operation cancelled by user.")
                                return clashing_elements
                            pb.update_progress(current_comparison, total_comparisons)
                        
                        if check_intersection(elem1, elem2):
                            clash_count += 1
                            clashing_elements.add(elem1.Id)
                            clashing_elements.add(elem2.Id)
                            output.print_md("Clash found: Element {} and {}".format(elem1.Id.IntegerValue, elem2.Id.IntegerValue))
    
    # Report results
    output.print_md("### Clash Detection Complete")
    output.print_md("- Total elements checked: {}".format(total_comparisons))
    output.print_md("- Clash instances found: {}".format(clash_count))
    output.print_md("- Unique clashing elements: {}".format(len(clashing_elements)))
    
    return clashing_elements

def main():
    try:
        # Find all clashes
        clashing_ids = find_clashes()
        
        # Isolate clashing elements if any were found
        if clashing_ids:
            with revit.Transaction("Isolate Clashing Elements"):
                active_view.IsolateElementsTemporary(List[ElementId](clashing_ids))
            
            forms.alert("Found {} clashing elements between different piping systems.\n"
                      "These elements have been temporarily isolated in the current view.".format(len(clashing_ids)),
                      title="Clash Detection Complete")
        else:
            forms.alert("No clashes found between different piping systems.",
                      title="Clash Detection Complete")
                
    except Exception as e:
        forms.alert("Error during clash detection: {}".format(str(e)), title="Error")

if __name__ == "__main__":
    main()