# -*- coding: utf-8 -*-
"""
Configuration UI for NWC export settings.
Handles all user prompts and saves configuration to Revit project global variables.
"""

from pyrevit import forms, revit, DB
import System

# Schema GUID - must match the one in script.py
SCHEMA_GUID = System.Guid("12345678-1234-1234-1234-123456789ABC")
SCHEMA_NAME = "NWCExportConfig"

def create_or_get_schema():
    """Create or get the extensible storage schema."""
    schema = DB.Schema.Lookup(SCHEMA_GUID)
    
    if schema is None:
        schema_builder = DB.SchemaBuilder(SCHEMA_GUID)
        schema_builder.SetSchemaName(SCHEMA_NAME)
        schema_builder.SetDocumentation("NWC Export Configuration Storage")
        
        # Add fields
        schema_builder.AddSimpleField("OutputFolder", str)
        schema_builder.AddArrayField("SelectedViews", int)
        schema_builder.AddSimpleField("ExportLinks", bool)
        schema_builder.AddSimpleField("ExportRoomAttr", bool)
        schema_builder.AddSimpleField("ExportRoomGeom", bool)
        schema_builder.AddSimpleField("ConvertProperties", bool)
        schema_builder.AddSimpleField("ExportParts", bool)
        schema_builder.AddSimpleField("DivideFileIntoLevels", bool)
        schema_builder.AddSimpleField("ExportUrls", bool)
        
        schema = schema_builder.Finish()
    
    return schema

def get_3d_views():
    """Get all 3D views in the project."""
    doc = revit.doc
    views_3d = DB.FilteredElementCollector(doc)\
        .OfClass(DB.View3D)\
        .WhereElementIsNotElementType()\
        .ToElements()
    
    return [v for v in views_3d if not v.IsTemplate]

def get_export_options():
    """Get export options from user."""
    options_form = [
        forms.flexform.FlexForm.CheckBox('export_links', 'Export Links', True),
        forms.flexform.FlexForm.CheckBox('export_room_attr', 'Export Room as Attribute', True),
        forms.flexform.FlexForm.CheckBox('export_room_geom', 'Export Room Geometry', True),
        forms.flexform.FlexForm.CheckBox('convert_properties', 'Convert Element Properties', True),
        forms.flexform.FlexForm.CheckBox('export_parts', 'Export Parts', False),
        forms.flexform.FlexForm.CheckBox('divide_file_into_levels', 'Divide File into Levels', False),
        forms.flexform.FlexForm.CheckBox('export_urls', 'Export URLs', True)
    ]
    
    result = forms.flexform.FlexForm('NWC Export Options', options_form).show()
    
    if result:
        return {
            'export_links': result['export_links'],
            'export_room_attr': result['export_room_attr'],
            'export_room_geom': result['export_room_geom'],
            'convert_properties': result['convert_properties'],
            'export_parts': result['export_parts'],
            'divide_file_into_levels': result['divide_file_into_levels'],
            'export_urls': result['export_urls']
        }
    return None

def save_config_to_project(output_folder, selected_views, export_options):
    """Save configuration to Revit project extensible storage."""
    doc = revit.doc
    
    try:
        with revit.Transaction("Save NWC Export Config"):
            schema = create_or_get_schema()
            project_info = doc.ProjectInformation
            
            # Remove existing entity if it exists
            if project_info.GetEntity(schema).IsValid():
                project_info.DeleteEntity(schema)
            
            # Create new entity
            entity = DB.Entity(schema)
            entity.Set("OutputFolder", output_folder)
            entity.Set("SelectedViews", System.Collections.Generic.IList[int](selected_views))
            entity.Set("ExportLinks", export_options.get('export_links', True))
            entity.Set("ExportRoomAttr", export_options.get('export_room_attr', True))
            entity.Set("ExportRoomGeom", export_options.get('export_room_geom', True))
            entity.Set("ConvertProperties", export_options.get('convert_properties', True))
            entity.Set("ExportParts", export_options.get('export_parts', False))
            entity.Set("DivideFileIntoLevels", export_options.get('divide_file_into_levels', False))
            entity.Set("ExportUrls", export_options.get('export_urls', True))
            
            project_info.SetEntity(entity)
            
        return True
    except Exception as e:
        print("Error saving config: {}".format(str(e)))
        return False

def configure_export():
    """Main configuration function with all user prompts."""
    # 1. PATH: Get output folder
    output_folder = forms.pick_folder(title="Select Output Folder for NWC Files")
    if not output_folder:
        forms.alert("No output folder selected.", exitscript=True)
    
    # Get all 3D views
    views_3d = get_3d_views()
    if not views_3d:
        forms.alert("No 3D views found in the project.", exitscript=True)
    
    # Create view selection options
    view_options = {}
    for view in views_3d:
        view_name = view.Name
        if hasattr(view, 'Title') and view.Title:
            view_name = view.Title
        view_options[view_name] = view.Id.IntegerValue
    
    # 2. VIEW SELECTION: Let user select views
    selected_view_names = forms.SelectFromList.show(
        view_options.keys(),
        title="Select 3D Views to Export",
        multiselect=True,
        button_name="Select Views"
    )
    
    if not selected_view_names:
        forms.alert("No views selected.", exitscript=True)
    
    # Convert to view IDs
    selected_view_ids = [view_options[name] for name in selected_view_names]
    
    # 3. EXPORT OPTIONS: Get export options
    export_options = get_export_options()
    if not export_options:
        forms.alert("Export options not configured.", exitscript=True)
    
    # Save configuration to project
    if save_config_to_project(output_folder, selected_view_ids, export_options):
        forms.alert("Configuration saved to project. {} views selected for export to:\n{}".format(
            len(selected_view_ids), output_folder), title="Configuration Saved")
    else:
        forms.alert("Error saving configuration to project.", title="Error")

def show_current_config():
    """Show current configuration stored in project."""
    doc = revit.doc
    
    try:
        schema = DB.Schema.Lookup(SCHEMA_GUID)
        if schema is None:
            forms.alert("No configuration found. Use Shift+Click to configure.", title="Current NWC Export Configuration")
            return
        
        project_info = doc.ProjectInformation
        entity = project_info.GetEntity(schema)
        
        if not entity.IsValid():
            forms.alert("No configuration found. Use Shift+Click to configure.", title="Current NWC Export Configuration")
            return
        
        summary = []
        summary.append("NWC Export Configuration:")
        summary.append("=" * 30)
        
        # Output folder
        output_folder = entity.Get[str]("OutputFolder")
        summary.append("Output Folder: {}".format(output_folder))
        
        # Selected views
        selected_view_ids = list(entity.Get[System.Collections.Generic.IList[int]]("SelectedViews"))
        summary.append("Selected Views: {} views".format(len(selected_view_ids)))
        
        # Show view names
        for view_id in selected_view_ids[:5]:
            try:
                view_element = doc.GetElement(DB.ElementId(view_id))
                if view_element:
                    summary.append("  - {}".format(view_element.Name))
            except:
                summary.append("  - View ID {} (not found)".format(view_id))
        
        if len(selected_view_ids) > 5:
            summary.append("  ... and {} more views".format(len(selected_view_ids) - 5))
        
        # Export options
        summary.append("\nExport Options:")
        summary.append("- Export Links: {}".format(entity.Get[bool]("ExportLinks")))
        summary.append("- Export Room as Attribute: {}".format(entity.Get[bool]("ExportRoomAttr")))
        summary.append("- Export Room Geometry: {}".format(entity.Get[bool]("ExportRoomGeom")))
        summary.append("- Convert Element Properties: {}".format(entity.Get[bool]("ConvertProperties")))
        summary.append("- Export Parts: {}".format(entity.Get[bool]("ExportParts")))
        summary.append("- Divide File into Levels: {}".format(entity.Get[bool]("DivideFileIntoLevels")))
        summary.append("- Export URLs: {}".format(entity.Get[bool]("ExportUrls")))
        
        forms.alert("\n".join(summary), title="Current NWC Export Configuration")
        
    except Exception as e:
        forms.alert("Error reading configuration: {}".format(str(e)), title="Error")
