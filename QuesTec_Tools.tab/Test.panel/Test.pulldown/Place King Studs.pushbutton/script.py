import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import revit, DB, UI, forms
import System

doc = revit.doc
uidoc = revit.uidoc

def get_linked_models_in_view():
    """Get all linked Revit models visible in the active view"""
    active_view = doc.ActiveView
    collector = FilteredElementCollector(doc, active_view.Id)
    revit_links = collector.OfClass(RevitLinkInstance).ToElements()
    
    linked_models = []
    for link in revit_links:
        link_doc = link.GetLinkDocument()
        if link_doc:
            linked_models.append({
                'name': link_doc.Title,
                'instance': link,
                'document': link_doc
            })
    
    return linked_models

def get_doors_from_linked_model(link_doc, link_instance):
    """Get all doors from the linked model"""
    collector = FilteredElementCollector(link_doc)
    doors = collector.OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType().ToElements()
    return doors

def get_door_width_parameters(door_type):
    """Get 'Rough Width' parameter only, return 3.0 if not found"""
    # Try to get Rough Width parameter only
    rough_width_param = door_type.LookupParameter("Rough Width")
    if rough_width_param and rough_width_param.HasValue:
        try:
            rough_width = rough_width_param.AsDouble()
            if rough_width > 0:
                return rough_width, True  # Return value and found flag
        except:
            pass
    
    # Default if Rough Width not found
    return 3.0, False  # Return default and not found flag

def find_king_stud_families():
    """Find all families with 'King Stud' in the name"""
    collector = FilteredElementCollector(doc)
    families = collector.OfClass(Family).ToElements()
    
    king_stud_families = []
    for family in families:
        if 'king stud' in family.Name.lower():
            # Get family symbols (types) for this family
            symbols = list(family.GetFamilySymbolIds())
            if symbols:
                symbol = doc.GetElement(symbols[0])
                king_stud_families.append({
                    'name': family.Name,
                    'symbol': symbol
                })
    
    return king_stud_families

def get_door_location_and_orientation(door, link_instance):
    """Get door location and orientation in project coordinates"""
    door_location = door.Location
    if hasattr(door_location, 'Point'):
        # Transform point from link coordinates to project coordinates
        transform = link_instance.GetTransform()
        project_point = transform.OfPoint(door_location.Point)
        
        # Get door orientation from LocationCurve if available
        door_rotation = 0
        orientation_info = "Unknown"
        
        if hasattr(door_location, 'Curve'):
            # Door has a curve (line) - get its direction
            curve = door_location.Curve
            transformed_curve = curve.CreateTransformed(transform)
            direction = transformed_curve.Direction.Normalize()
            
            # Calculate angle from X-axis (East direction)
            door_rotation = System.Math.Atan2(direction.Y, direction.X)
            
            # Determine if door is primarily north/south or east/west
            angle_degrees = door_rotation * 180 / System.Math.PI
            angle_degrees = angle_degrees % 180  # Normalize to 0-180
            
            if angle_degrees < 45 or angle_degrees > 135:
                orientation_info = "East/West"
            else:
                orientation_info = "North/South"
                
        elif hasattr(door_location, 'Rotation'):
            door_rotation = door_location.Rotation
            angle_degrees = door_rotation * 180 / System.Math.PI
            angle_degrees = angle_degrees % 180
            
            if angle_degrees < 45 or angle_degrees > 135:
                orientation_info = "East/West"
            else:
                orientation_info = "North/South"
        
        return project_point, door_rotation, orientation_info
    return None, None, None

def get_level_at_elevation(elevation):
    """Get the level closest to the given elevation"""
    collector = FilteredElementCollector(doc)
    levels = collector.OfClass(Level).ToElements()
    
    if not levels:
        return None
    
    # Find the level closest to the elevation
    closest_level = None
    min_distance = float('inf')
    
    for level in levels:
        level_elevation = level.Elevation
        distance = abs(level_elevation - elevation)
        if distance < min_distance:
            min_distance = distance
            closest_level = level
    
    return closest_level

def get_king_stud_width(king_stud_symbol):
    """Get the width parameter from the king stud family"""
    for param in king_stud_symbol.Parameters:
        param_name = param.Definition.Name
        if param_name == "Width" and param.HasValue:
            try:
                return param.AsDouble()
            except:
                continue
    return 0.125  # Default 1.5 inches if no width parameter found

def place_king_studs(door, door_width, king_stud_symbol, link_instance, use_default=False):
    """Calculate king stud positions for the door"""
    door_point, door_rotation, orientation = get_door_location_and_orientation(door, link_instance)
    
    if door_point is None:
        return None
    
    # Get the appropriate level for the door elevation
    door_level = get_level_at_elevation(door_point.Z)
    if door_level is None:
        print("No level found for door elevation")
        return None
    
    # Get king stud width and calculate offset distance
    king_stud_width = get_king_stud_width(king_stud_symbol)
    offset_distance = (door_width / 2.0) + (king_stud_width / 2.0)  # Half rough width + half stud width
    
    # Calculate rotation angle for the family instances
    family_rotation = 0
    if orientation == "North/South":
        family_rotation = System.Math.PI / 2  # 90 degrees rotation
    
    # Calculate positions for king studs based on door orientation
    if orientation == "East/West":
        # Door is oriented east/west, place studs east and west (along door width)
        stud1_point = XYZ(door_point.X + offset_distance, door_point.Y, door_level.Elevation)
        stud2_point = XYZ(door_point.X - offset_distance, door_point.Y, door_level.Elevation)
    elif orientation == "North/South":
        # Door is oriented north/south, place studs north and south (along door width)
        stud1_point = XYZ(door_point.X, door_point.Y + offset_distance, door_level.Elevation)
        stud2_point = XYZ(door_point.X, door_point.Y - offset_distance, door_level.Elevation)
    else:
        # Fallback to rotation-based calculation
        cos_rot = System.Math.Cos(door_rotation)  # Parallel to door direction
        sin_rot = System.Math.Sin(door_rotation)
        stud1_point = XYZ(door_point.X + cos_rot * offset_distance, 
                          door_point.Y + sin_rot * offset_distance, 
                          door_level.Elevation)
        stud2_point = XYZ(door_point.X - cos_rot * offset_distance, 
                          door_point.Y - sin_rot * offset_distance, 
                          door_level.Elevation)
    
    # Debug output for positioning
    print("  Door Center: X={:.3f}, Y={:.3f} | Orientation: {} | Door Width: {:.3f} ft | King Stud Width: {:.3f} ft | Offset: {:.3f} ft".format(
        door_point.X, door_point.Y, orientation, door_width, king_stud_width, offset_distance))
    print("  Stud 1: X={:.3f}, Y={:.3f} | Stud 2: X={:.3f}, Y={:.3f}".format(
        stud1_point.X, stud1_point.Y, stud2_point.X, stud2_point.Y))
    
    # Calculate and display center-to-center distance for verification
    if orientation == "East/West":
        center_to_center = abs(stud1_point.X - stud2_point.X)
    elif orientation == "North/South":
        center_to_center = abs(stud1_point.Y - stud2_point.Y)
    else:
        center_to_center = ((stud1_point.X - stud2_point.X)**2 + (stud1_point.Y - stud2_point.Y)**2)**0.5
    
    print("  Center-to-Center Distance: {:.3f} ft (Expected: {:.3f} ft)".format(center_to_center, door_width + king_stud_width))
    
    return [(stud1_point, door_level, family_rotation, use_default), (stud2_point, door_level, family_rotation, use_default)]

def main():
    # Get linked models in active view
    linked_models = get_linked_models_in_view()
    
    if not linked_models:
        forms.alert("No linked Revit models found in the active view.", exitscript=True)
    
    # Show selection dialog for linked models
    if len(linked_models) > 1:
        model_names = [model['name'] for model in linked_models]
        selected_model_name = forms.SelectFromList.show(
            model_names,
            title="Select Linked Model",
            message="Choose a linked Revit model:"
        )
        
        if not selected_model_name:
            return  # User cancelled
        
        selected_model = next(model for model in linked_models if model['name'] == selected_model_name)
    else:
        selected_model = linked_models[0]
    
    # Get doors from selected linked model
    doors = get_doors_from_linked_model(selected_model['document'], selected_model['instance'])
    
    if not doors:
        forms.alert("No doors found in the selected linked model.", exitscript=True)
    
    # Find king stud families
    king_stud_families = find_king_stud_families()
    
    if not king_stud_families:
        forms.alert("No families with 'King Stud' in the name found in the current project.", exitscript=True)
    
    # Select king stud family if multiple options
    if len(king_stud_families) > 1:
        family_names = [family['name'] for family in king_stud_families]
        selected_family_name = forms.SelectFromList.show(
            family_names,
            title="Select King Stud Family",
            message="Choose a king stud family to place:"
        )
        
        if not selected_family_name:
            return  # User cancelled
        
        selected_family = next(family for family in king_stud_families if family['name'] == selected_family_name)
    else:
        selected_family = king_stud_families[0]
    
    king_stud_symbol = selected_family['symbol']
    
    # Collect all king stud positions before placing
    king_stud_positions = []
    door_types_processed = {}  # Change to dict to store width info
    
    for door in doors:
        # Get door type from linked document using proper method
        door_type_id = door.GetTypeId()
        door_type = selected_model['document'].GetElement(door_type_id)
        
        if door_type and door_type.Id not in door_types_processed:
            # Get the width parameter for this door type
            door_width, found_rough_width = get_door_width_parameters(door_type)
            door_types_processed[door_type.Id] = (door_width, found_rough_width)
            
            # Get door type name using proper ElementType properties
            door_type_name = "Unknown Door Type"
            try:
                if hasattr(door_type, 'Name'):
                    door_type_name = door_type.Name
                if hasattr(door_type, 'FamilyName'):
                    family_name = door_type.FamilyName
                    door_type_name = "{} - {}".format(family_name, door_type_name)
            except Exception as e:
                door_type_name = "Error getting name: " + str(e)
            
            # Output information
            if found_rough_width:
                print("Door Type: {} - Found Rough Width: {:.3f} ft".format(door_type_name, door_width))
            else:
                print("Door Type: {} - Rough Width NOT FOUND - Using DEFAULT: {:.3f} ft (WILL BE RED)".format(door_type_name, door_width))
        
        elif door_type and door_type.Id in door_types_processed:
            # Use previously processed door type info
            door_width, found_rough_width = door_types_processed[door_type.Id]
        else:
            # Fallback if door type not found
            door_width = 3.0
            found_rough_width = False
        
        # Get king stud positions for this door
        stud_positions = place_king_studs(door, door_width, king_stud_symbol, selected_model['instance'], not found_rough_width)
        if stud_positions:
            king_stud_positions.extend(stud_positions)
    
    if not king_stud_positions:
        forms.alert("No king stud positions could be calculated.", exitscript=True)
    
    # Place all king studs in a single transaction
    t = Transaction(doc, "Place King Studs")
    t.Start()
    
    try:
        # Activate the symbol if not active
        if not king_stud_symbol.IsActive:
            king_stud_symbol.Activate()
            doc.Regenerate()
        
        studs_placed = 0
        default_studs = []
        
        for stud_point, stud_level, rotation, is_default in king_stud_positions:
            # Create the family instance
            instance = doc.Create.NewFamilyInstance(stud_point, king_stud_symbol, stud_level, Structure.StructuralType.Column)
            
            # Rotate the instance if needed
            if rotation != 0:
                axis = Line.CreateBound(stud_point, XYZ(stud_point.X, stud_point.Y, stud_point.Z + 1))
                ElementTransformUtils.RotateElement(doc, instance.Id, axis, rotation)
            
            # Track default studs for coloring
            if is_default:
                default_studs.append(instance.Id)
            
            studs_placed += 1
        
        # Color default studs red
        if default_studs:
            override_settings = OverrideGraphicSettings()
            red_color = Color(255, 0, 0)  # Red color
            override_settings.SetProjectionLineColor(red_color)
            override_settings.SetSurfaceForegroundPatternColor(red_color)
            override_settings.SetCutLineColor(red_color)
            override_settings.SetSurfaceBackgroundPatternColor(red_color)
            
            for stud_id in default_studs:
                doc.ActiveView.SetElementOverrides(stud_id, override_settings)
        
        t.Commit()
        
        default_count = len(default_studs)
        message = "Successfully placed {} king studs for {} doors.".format(studs_placed, len(doors))
        if default_count > 0:
            message += "\n{} studs colored RED (used default 3' width - no Rough Width found).".format(default_count)
        
        forms.alert(message)
        
    except Exception as e:
        t.RollBack()
        forms.alert("Error placing king studs: {}".format(str(e)))

if __name__ == "__main__":
    main()
