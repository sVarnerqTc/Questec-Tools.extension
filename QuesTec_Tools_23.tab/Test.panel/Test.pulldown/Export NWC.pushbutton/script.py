# -*- coding: utf-8 -*-
from pyrevit import forms, revit, DB
import clr
import os
import System

# Schema GUID for configuration storage
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
    """Configuration function with all user prompts."""
    # Get output folder
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
    
    # Let user select views
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
    
    # Get export options
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

def load_config_from_project():
    """Load configuration from Revit project global variables."""
    doc = revit.doc
    
    try:
        schema = DB.Schema.Lookup(SCHEMA_GUID)
        if schema is None:
            return None
        
        project_info = doc.ProjectInformation
        entity = project_info.GetEntity(schema)
        
        if entity.IsValid():
            return {
                'output_folder': entity.Get[str]("OutputFolder"),
                'selected_views': list(entity.Get[System.Collections.Generic.IList[int]]("SelectedViews")),
                'export_options': {
                    'export_links': entity.Get[bool]("ExportLinks"),
                    'export_room_attr': entity.Get[bool]("ExportRoomAttr"),
                    'export_room_geom': entity.Get[bool]("ExportRoomGeom"),
                    'convert_properties': entity.Get[bool]("ConvertProperties"),
                    'export_parts': entity.Get[bool]("ExportParts"),
                    'divide_file_into_levels': entity.Get[bool]("DivideFileIntoLevels"),
                    'export_urls': entity.Get[bool]("ExportUrls")
                }
            }
    except Exception as e:
        print("Error loading config: {}".format(str(e)))
    
    return None

def export_nwc():
    """Export NWC files based on project global variables."""
    doc = revit.doc
    
    # Load configuration from project
    config = load_config_from_project()
    if not config:
        forms.alert("No configuration found. Please use Shift+Click to configure export settings first.", 
                   exitscript=True)
    
    output_folder = config.get('output_folder')
    selected_view_ids = config.get('selected_views', [])
    export_options_config = config.get('export_options', {})
    
    if not output_folder or not selected_view_ids:
        forms.alert("Invalid configuration. Please use Shift+Click to reconfigure.", exitscript=True)
    
    if not os.path.exists(output_folder):
        forms.alert("Output folder does not exist: {}".format(output_folder), exitscript=True)
    
    # Get project name for file naming
    project_name = os.path.splitext(os.path.basename(doc.PathName))[0] if doc.PathName else "Untitled"
    
    # Execute export without transaction (export doesn't modify model)
    exported_files = []
    failed_exports = []
    
    for view_id in selected_view_ids:
        try:
            view_element = doc.GetElement(DB.ElementId(view_id))
            if not view_element:
                failed_exports.append("View ID {} not found".format(view_id))
                continue
            
            view_name = view_element.Name
            if hasattr(view_element, 'Title') and view_element.Title:
                view_name = view_element.Title
            
            # Clean view name for filename
            safe_view_name = "".join(c for c in view_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            
            # Create output filename
            output_filename = "{} - {}.nwc".format(project_name, safe_view_name)
            
            # Set up NWC export options
            options = DB.NavisworksExportOptions()
            options.ExportScope = DB.NavisworksExportScope.View
            options.ViewId = view_element.Id
            options.ExportLinks = export_options_config.get('export_links', True)
            options.ExportRoomAsAttribute = export_options_config.get('export_room_attr', True)
            options.ExportRoomGeometry = export_options_config.get('export_room_geom', True)
            options.ConvertElementProperties = export_options_config.get('convert_properties', True)
            options.ExportParts = export_options_config.get('export_parts', False)
            options.DivideFileIntoLevels = export_options_config.get('divide_file_into_levels', False)
            options.ExportUrls = export_options_config.get('export_urls', True)
            
            # Export NWC
            doc.Export(output_folder, output_filename, options)
            exported_files.append(output_filename)
            
        except Exception as e:
            failed_exports.append("View '{}': {}".format(view_name, str(e)))
            continue
    
    # Report results
    message = ""
    if exported_files:
        message += "Successfully exported {} NWC files:\n\n".format(len(exported_files))
        for filename in exported_files:
            message += "- {}\n".format(filename)
        message += "\nLocation: {}\n\n".format(output_folder)
    
    if failed_exports:
        message += "Failed exports ({}):\n".format(len(failed_exports))
        for failure in failed_exports:
            message += "- {}\n".format(failure)
    
    if not exported_files and not failed_exports:
        message = "No files were processed."
    
    forms.alert(message, title="NWC Export Results")

# Main script logic
if __name__ == '__main__':
    modifier_keys = System.Windows.Forms.Control.ModifierKeys
    
    if modifier_keys == System.Windows.Forms.Keys.Shift:
        # Shift+Click: Configure export settings
        configure_export()
    elif modifier_keys == System.Windows.Forms.Keys.Control:
        # Ctrl+Click: View current configuration
        show_current_config()
    else:
        # Normal click: Execute export using project global variables
        export_nwc()
