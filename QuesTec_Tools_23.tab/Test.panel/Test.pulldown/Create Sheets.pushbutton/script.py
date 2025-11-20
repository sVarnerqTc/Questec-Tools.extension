# -*- coding: utf-8 -*-
from pyrevit import forms, revit, DB
import clr

try:
    # Get current document and active view
    doc = revit.doc
    active_view = doc.ActiveView

    # Check if current view is a 2D plan view
    if not isinstance(active_view, DB.ViewPlan):
        forms.alert("Current view must be a 2D plan view.", exitscript=True)

    # Prompt user for base sheet name
    base_sheet_name = forms.ask_for_string(
        default="Sheet Base Name",
        prompt="Enter base sheet name:",
        title="Base Sheet Name"
    )

    if not base_sheet_name:
        forms.alert("No base sheet name provided.", exitscript=True)

    # Get all scope boxes in the project
    scope_boxes = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)\
        .WhereElementIsNotElementType()\
        .ToElements()

    if not scope_boxes:
        forms.alert("No scope boxes found in the project.", exitscript=True)

    # Create selection options for scope boxes
    scope_box_options = {sb.Name: sb for sb in scope_boxes if sb.Name}

    if not scope_box_options:
        forms.alert("No named scope boxes found in the project.", exitscript=True)

    # Let user select scope boxes
    selected_scope_boxes = forms.SelectFromList.show(
        scope_box_options.keys(),
        title="Select Scope Boxes",
        multiselect=True,
        button_name="Select"
    )

    if not selected_scope_boxes:
        forms.alert("No scope boxes selected.", exitscript=True)

    # Get all title block types for sheet template selection
    title_blocks = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)\
        .WhereElementIsElementType()\
        .ToElements()

    if not title_blocks:
        forms.alert("No title block templates found.", exitscript=True)

    # Create selection options for title blocks
    title_block_options = {tb.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString(): tb for tb in title_blocks}

    # Let user select title block template
    selected_title_block_name = forms.SelectFromList.show(
        title_block_options.keys(),
        title="Select Sheet Template",
        button_name="Select"
    )

    if not selected_title_block_name:
        forms.alert("No sheet template selected.", exitscript=True)

    selected_title_block = title_block_options[selected_title_block_name]

    # Start transaction
    t = DB.Transaction(doc, "Create Sheets from Scope Boxes")
    t.Start()
    
    try:
        created_sheets = []
        
        for scope_box_name in selected_scope_boxes:
            try:
                scope_box = scope_box_options[scope_box_name]
                
                # Create dependent view
                dependent_view_id = active_view.Duplicate(DB.ViewDuplicateOption.AsDependent)
                dependent_view = doc.GetElement(dependent_view_id)
                
                # Rename dependent view
                new_view_name = "{} - {}".format(active_view.Name, scope_box_name)
                dependent_view.Name = new_view_name
                
                # Set crop box to scope box
                dependent_view.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP).Set(scope_box.Id)
                
                # Create sheet number and name
                sheet_number = "{}.{}".format(base_sheet_name, scope_box_name)
                sheet_name = new_view_name
                
                # Create new sheet
                new_sheet = DB.ViewSheet.Create(doc, selected_title_block.Id)
                new_sheet.SheetNumber = sheet_number
                new_sheet.Name = sheet_name
                
                # Place view on sheet
                try:
                    # Get the center of the sheet for view placement
                    outline = new_sheet.Outline
                    center_point = DB.XYZ(
                        (outline.Max.U + outline.Min.U) / 2,
                        (outline.Max.V + outline.Min.V) / 2,
                        0
                    )
                    
                    # Create viewport
                    viewport = DB.Viewport.Create(doc, new_sheet.Id, dependent_view_id, center_point)
                    
                    created_sheets.append((sheet_number, sheet_name))
                    
                except Exception as e:
                    print("Error placing view {} on sheet {}: {}".format(new_view_name, sheet_number, str(e)))
                    
            except Exception as e:
                print("Error processing scope box {}: {}".format(scope_box_name, str(e)))
                continue
        
        t.Commit()
        
        # Report results
        if created_sheets:
            message = "Successfully created {} sheets:\n\n".format(len(created_sheets))
            for sheet_num, sheet_name in created_sheets:
                message += "- {}: {}\n".format(sheet_num, sheet_name)
            forms.alert(message, title="Success")
        else:
            forms.alert("No sheets were created.", title="Warning")
            
    except Exception as e:
        t.RollBack()
        forms.alert("Error during sheet creation: {}".format(str(e)), title="Error")
        
except Exception as e:
    forms.alert("Script error: {}".format(str(e)), title="Error")
