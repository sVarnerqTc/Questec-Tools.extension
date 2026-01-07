from pyrevit import revit, DB, script, forms
import math

def get_pipe_info(pipe):
    """Get system type and size for a pipe"""
    output = script.get_output()
    
    
    # Try different ways to get system type
    system_type = (
        pipe.LookupParameter("System Type") or
        pipe.LookupParameter("System Classification") or
        pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM) or
        pipe.get_Parameter(DB.BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)
    )
    
    if system_type:
        system_value = system_type.AsString() or system_type.AsValueString()
    else:
        # List all parameters to help identify correct name
        output.print_md("Available parameters:")
        for param in pipe.Parameters:
            try:
                value = param.AsString() or param.AsValueString() or "No Value"
                output.print_md("* {}: {}".format(param.Definition.Name, value))
            except:
                output.print_md("* {}: Error reading value".format(param.Definition.Name))
        system_value = "Unknown"
    
    size = pipe.LookupParameter("Size").AsString()
    return system_value, size

def get_float_from_parameter(param):
    """Convert parameter value to float, handling units and fractions"""
    if not param or not param.HasValue:
        return 0.0
        
    try:
        # Try direct conversion first
        return param.AsDouble()
    except:
        try:
            # Try parsing string value
            value_str = param.AsValueString()
            if not value_str:
                return 0.0
            
            # Clean up the string
            value_str = value_str.strip()
            
            # Handle fraction format like "0" / 12""
            if '/' in value_str:
                parts = value_str.replace('"', '').split('/')
                numerator = float(parts[0].strip())
                denominator = float(parts[1].strip())
                if denominator == 0:
                    return 0.0
                return numerator / denominator
            
            # Handle simple unit format
            value = float(value_str.replace('"', ''))
            if '"' in value_str:
                value /= 12.0  # Convert inches to feet
            return value
            
        except:
            return 0.0

def update_hanger_parameters(doc, hanger, pipe):
    """Update hanger parameters based on pipe properties"""
    output = script.get_output()
    t = None
    
    try:
        t = DB.Transaction(doc, "Update Hanger Parameters")
        t.Start()
        
        # Get pipe parameters
        system_type = (pipe.LookupParameter("System Type") or
                      pipe.LookupParameter("System Classification") or
                      pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM))
        insul_thick = pipe.LookupParameter("Insulation Thickness")
        lower_end = pipe.LookupParameter("Lower End Bottom")
        slope = pipe.LookupParameter("Slope")
        
        # Get pipe curve and project point
        pipe_curve = pipe.Location.Curve
        hanger_point = hanger.Location.Point
        projection = pipe_curve.Project(hanger_point)
        
        if projection:
            projected_point = projection.XYZPoint
            pipe_start = pipe_curve.GetEndPoint(0)
            distance_from_start = pipe_start.DistanceTo(projected_point)
            
            # Handle slope calculation
            slope_value = 0.0
            if slope and slope.HasValue:
                slope_str = slope.AsValueString()
                if slope_str:
                    slope_value = float(slope_str.strip('%')) / 100.0
            
            elevation_change = distance_from_start * slope_value
            bop = get_float_from_parameter(lower_end) + elevation_change
            
            # Set hanger parameters
            nom_radius = hanger.LookupParameter("Nom Radius")
            qtc_size = hanger.LookupParameter("QTC Pipe Size")
            if nom_radius and qtc_size:
                pipe_size = get_float_from_parameter(nom_radius) * 2
                qtc_size.Set(pipe_size)

            support_disc = hanger.LookupParameter("Support Discipline")
            if support_disc and system_type and system_type.HasValue:
                support_disc.Set(system_type.AsString())

            hanger_bop = hanger.LookupParameter("BOP")
            if hanger_bop:
                hanger_bop.Set(bop)

            hanger_boi = hanger.LookupParameter("BOI")
            if hanger_boi and insul_thick:
                insul_value = get_float_from_parameter(insul_thick)
                boi = bop - insul_value
                hanger_boi.Set(boi)

            qtc_insul = hanger.LookupParameter("QTC Insulation Thickness")
            if qtc_insul and insul_thick:
                insul_value = get_float_from_parameter(insul_thick)
                qtc_insul.Set(insul_value)

            pipe_id_param = hanger.LookupParameter("QTC Pipe ID")
            if pipe_id_param:
                pipe_id_str = str(pipe.Id.IntegerValue)
                pipe_id_param.Set(pipe_id_str)
            
        t.Commit()
        return True
            
    except Exception as ex:
        if t and t.HasStarted():
            t.RollBack()
        output.print_md("Error updating hanger {}: {}".format(hanger.Id, str(ex)))
        return False

def get_hangers_and_pipes():
    """Find hangers and their intersecting pipes"""
    doc = revit.doc
    active_view = doc.ActiveView
    output = script.get_output()
    
    # Collect pipe accessories with BOP parameter
    hangers = []
    accessories = (DB.FilteredElementCollector(doc, active_view.Id)
                  .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
                  .WhereElementIsNotElementType()
                  .ToElements())
    
    for acc in accessories:
        if acc.LookupParameter("BOP"):
            hangers.append(acc)
    
    if not hangers:
        output.print_md("No hangers found with BOP parameter")
        return
    
    # Collect all pipes
    pipes = (DB.FilteredElementCollector(doc, active_view.Id)
            .OfCategory(DB.BuiltInCategory.OST_PipeCurves)
            .WhereElementIsNotElementType()
            .ToElements())
    
    output.print_md("# Hanger Analysis Results")
    output.print_md("---")
    
    # Track results by category
    error_hangers = []
    no_pipe_hangers = []
    valid_hangers = []
    warning_hangers = []  # New list for multiple matching pipes
    
    # Check each hanger for intersecting pipes
    for hanger in hangers:
        location = hanger.Location.Point
        nom_radius_param = hanger.LookupParameter("Nom Radius")
        if not nom_radius_param:
            continue
            
        search_radius = nom_radius_param.AsDouble() + (1.0/12.0)
        intersecting_pipes = []
        
        # Find intersecting pipes
        for pipe in pipes:
            curve = pipe.Location.Curve
            if curve:
                closest_point = curve.Project(location).XYZPoint
                distance = location.DistanceTo(closest_point)
                
                if distance <= search_radius:
                    intersecting_pipes.append(pipe)
        
        # Analyze intersecting pipes
        if not intersecting_pipes:
            no_pipe_hangers.append(hanger.Id)
        elif len(intersecting_pipes) == 1:
            valid_hangers.append((hanger.Id, intersecting_pipes[0].Id))
        else:
            # Check if all pipes have matching parameters
            system_types = set()
            sizes = set()
            for pipe in intersecting_pipes:
                system_type, size = get_pipe_info(pipe)
                system_types.add(system_type)
                sizes.add(size)
            
            if len(system_types) == 1 and len(sizes) == 1:
                # All pipes match - use first pipe but add warning
                pipe = intersecting_pipes[0]
                if update_hanger_parameters(doc, hanger, pipe):
                    valid_hangers.append((hanger.Id, pipe.Id))
                    if len(intersecting_pipes) > 1:
                        warning_hangers.append((hanger.Id, system_types.pop(), sizes.pop()))
                else:
                    error_hangers.append(hanger.Id)
            else:
                error_hangers.append(hanger.Id)
    
    # Print results
    if valid_hangers:
        output.print_md("\n## Valid Hangers:")
        for hanger_id, pipe_id in valid_hangers:
            output.print_md("* Hanger {0} -> Pipe {1}".format(hanger_id, pipe_id))
    
    if warning_hangers:
        output.print_md("\n## Warning - Multiple Matching Pipes:")
        for hanger_id, system_type, size in warning_hangers:
            output.print_md("* Hanger {0} -> System: {1}, Size: {2}".format(
                hanger_id, system_type, size))
    
    if error_hangers:
        output.print_md("\n## Error - Multiple Different Pipes:")
        for hanger_id in error_hangers:
            output.print_md("* Hanger {}".format(hanger_id))
    
    if no_pipe_hangers:
        output.print_md("\n## Error - No Pipes Found:")
        for hanger_id in no_pipe_hangers:
            output.print_md("* Hanger {}".format(hanger_id))
    
    # Collect all system types from intersecting pipes
    all_system_types = set()
    for hanger, pipe_id in valid_hangers:
        pipe = doc.GetElement(pipe_id)
        system_type = get_pipe_info(pipe)[0]
        all_system_types.add(system_type)
        
    # Add systems from warning hangers
    for hanger_id, system_type, size in warning_hangers:
        all_system_types.add(system_type)
    
    # Print system types summary
    if all_system_types:
        output.print_md("\n## All System Types Found:")
        for system in sorted(all_system_types):
            output.print_md("* {}".format(system))

if __name__ == "__main__":
    get_hangers_and_pipes()