# -*- coding: utf-8 -*-
from pyrevit import forms, revit, DB, script
import clr
import json
import System

# Categories hidden in the new views so they don't stretch the viewport
# (they ignore the annotation crop). Matches the existing piping plans.
HIDDEN_CATEGORIES = [
    DB.BuiltInCategory.OST_VolumeOfInterest,  # Scope Boxes
    DB.BuiltInCategory.OST_Sections,
]
TITLE_GAP_INCHES = 0.25  # view title sits this far below the lowest grid bubble


def hide_categories(view):
    for bic in HIDDEN_CATEGORIES:
        try:
            cat_id = DB.ElementId(bic)
            if view.CanCategoryBeHidden(cat_id):
                view.SetCategoryHidden(cat_id, True)
        except Exception:
            pass  # e.g. visibility controlled by a view template


def fit_view_title(viewport, view):
    """Trim the view title line to the plan (crop) width and place the title
    TITLE_GAP_INCHES below the lowest grid bubble (or below the plan if there
    are no grids)."""
    to_sheet = viewport.GetProjectionToSheetTransform()
    to_proj = view.GetModelToProjectionTransforms()[0].GetModelToProjectionTransform()

    def on_sheet(point):
        return to_sheet.OfPoint(to_proj.OfPoint(point))

    crop = view.CropBox
    corners = [
        on_sheet(crop.Transform.OfPoint(DB.XYZ(x, y, crop.Min.Z)))
        for x in (crop.Min.X, crop.Max.X)
        for y in (crop.Min.Y, crop.Max.Y)
    ]
    min_x = min(p.X for p in corners)
    max_x = max(p.X for p in corners)
    bottom = min(p.Y for p in corners)

    for grid in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Grid):
        bbox = grid.get_BoundingBox(view)
        if bbox:
            bottom = min(bottom, on_sheet(bbox.Min).Y, on_sheet(bbox.Max).Y)

    box_min = viewport.GetBoxOutline().MinimumPoint
    viewport.LabelLineLength = max_x - min_x
    viewport.LabelOffset = DB.XYZ(min_x - box_min.X, (bottom - TITLE_GAP_INCHES / 12.0) - box_min.Y, 0)


def can_make_dependents(view):
    try:
        return (isinstance(view, DB.ViewPlan) and not view.IsTemplate
                and view.GetPrimaryViewId() == DB.ElementId.InvalidElementId  # not itself a dependent
                and view.CanViewBeDuplicated(DB.ViewDuplicateOption.AsDependent))
    except Exception:
        return False


def view_label(view):
    return "{} - {}".format(view.ViewType, view.Name)


def pick_plan_views():
    """Let the user check one or more 2D plan views that dependent views can be made from."""
    views = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan) if can_make_dependents(v)]
    if not views:
        forms.alert("No 2D plan views were found that dependent views can be made from.", exitscript=True)
    options = dict((view_label(v), v) for v in views)
    chosen = forms.SelectFromList.show(
        sorted(options.keys()),
        title="Select the 2D Plan Views to Place on Sheets",
        button_name="Use Selected Views",
        multiselect=True,
    )
    if not chosen:
        script.exit()
    if not isinstance(chosen, list):
        chosen = [chosen]
    return [options[c] for c in chosen]


def choose_source_views(current):
    """Use the current view, or pick one or more views. Goes straight to the
    pick list if the current view isn't a usable 2D plan."""
    if not can_make_dependents(current):
        forms.alert(
            "The active view ({}) isn't a 2D plan view that dependent views can be made from.\n\n"
            "Select one or more 2D plan views to use.".format(current.Name),
            title="Create Sheets",
        )
        return pick_plan_views()

    choice = forms.CommandSwitchWindow.show(
        ["Use Current View", "Select Views"],
        message="Place '{}' on sheets, or select one or more views?".format(current.Name),
    )
    if not choice:
        script.exit()
    if choice == "Select Views":
        return pick_plan_views()
    return [current]


def ask_base_numbers(views, defaults):
    """Fill-in-the-blank form: a base number box on the left, its view on the right.
    Returns {view id int: base number} for filled rows, or None if cancelled."""
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    from System.Windows import (Window, Thickness, SizeToContent, WindowStartupLocation,
                                GridLength, GridUnitType, VerticalAlignment, HorizontalAlignment,
                                ResizeMode)
    from System.Windows.Controls import (Grid, ColumnDefinition, RowDefinition, TextBox, TextBlock,
                                         Button, StackPanel, ScrollViewer, Orientation, ScrollBarVisibility)

    window = Window()
    window.Title = "Base Numbers"
    window.SizeToContent = SizeToContent.WidthAndHeight
    window.WindowStartupLocation = WindowStartupLocation.CenterScreen
    window.ResizeMode = ResizeMode.NoResize
    window.MaxHeight = 700

    root = StackPanel()
    root.Margin = Thickness(14)

    intro = TextBlock()
    intro.Text = ("Enter a base number for each view. For example, P-101\n"
                  "Each sheet will be numbered <base number>.<scope box name>\n"
                  "Leave a row blank to skip that view.")
    intro.Margin = Thickness(0, 0, 0, 10)
    root.Children.Add(intro)

    grid = Grid()
    col0 = ColumnDefinition(); col0.Width = GridLength(150)
    col1 = ColumnDefinition(); col1.Width = GridLength(1, GridUnitType.Auto)
    grid.ColumnDefinitions.Add(col0)
    grid.ColumnDefinitions.Add(col1)

    header_box = TextBlock(); header_box.Text = "Base Number"; header_box.FontWeight = System.Windows.FontWeights.Bold
    header_view = TextBlock(); header_view.Text = "View"; header_view.FontWeight = System.Windows.FontWeights.Bold
    header_view.Margin = Thickness(10, 0, 0, 0)
    grid.RowDefinitions.Add(RowDefinition())
    Grid.SetRow(header_box, 0); Grid.SetColumn(header_box, 0)
    Grid.SetRow(header_view, 0); Grid.SetColumn(header_view, 1)
    grid.Children.Add(header_box)
    grid.Children.Add(header_view)

    boxes = []
    for i, view in enumerate(views):
        grid.RowDefinitions.Add(RowDefinition())
        box = TextBox()
        box.Text = defaults.get(str(view.Id.IntegerValue), "")
        box.Margin = Thickness(0, 4, 0, 4)
        box.VerticalAlignment = VerticalAlignment.Center
        label = TextBlock()
        label.Text = view_label(view)
        label.Margin = Thickness(10, 4, 0, 4)
        label.VerticalAlignment = VerticalAlignment.Center
        Grid.SetRow(box, i + 1); Grid.SetColumn(box, 0)
        Grid.SetRow(label, i + 1); Grid.SetColumn(label, 1)
        grid.Children.Add(box)
        grid.Children.Add(label)
        boxes.append((view, box))

    scroller = ScrollViewer()
    scroller.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    scroller.MaxHeight = 520
    scroller.Content = grid
    root.Children.Add(scroller)

    buttons = StackPanel()
    buttons.Orientation = Orientation.Horizontal
    buttons.HorizontalAlignment = HorizontalAlignment.Right
    buttons.Margin = Thickness(0, 12, 0, 0)
    ok = Button(); ok.Content = "Create Sheets"; ok.Width = 110; ok.IsDefault = True
    cancel = Button(); cancel.Content = "Cancel"; cancel.Width = 80; cancel.IsCancel = True
    cancel.Margin = Thickness(8, 0, 0, 0)
    buttons.Children.Add(ok)
    buttons.Children.Add(cancel)
    root.Children.Add(buttons)

    result = {"ok": False}

    def on_ok(sender, args):
        result["ok"] = True
        window.Close()

    ok.Click += on_ok
    window.Content = root
    if boxes:
        boxes[0][1].Focus()
    window.ShowDialog()

    if not result["ok"]:
        return None
    return dict((v.Id.IntegerValue, b.Text.strip()) for v, b in boxes if b.Text and b.Text.strip())


def get_base_numbers(views, config):
    """Show the form until the base numbers are valid. Remembers the last
    base number used for each view."""
    try:
        defaults = json.loads(getattr(config, "base_numbers_json", "{}") or "{}")
    except Exception:
        defaults = {}

    while True:
        numbers = ask_base_numbers(views, defaults)
        if numbers is None:
            script.exit()
        # keep what was typed if the form has to be shown again
        defaults.update(dict((str(k), v) for k, v in numbers.items()))
        if not numbers:
            forms.alert("Enter a base number for at least one view.", title="Base Numbers")
            continue
        repeated = sorted(set(n for n in numbers.values() if list(numbers.values()).count(n) > 1))
        if repeated:
            forms.alert("Each view needs its own base number. Used more than once:\n\n{}".format(
                "\n".join(repeated)), title="Base Numbers")
            continue
        break

    try:
        config.base_numbers_json = json.dumps(defaults)
        script.save_config()
    except Exception:
        pass
    return numbers


try:
    doc = revit.doc
    config = script.get_config()

    # The 2D plan views the sheets are made from
    source_views = sorted(choose_source_views(doc.ActiveView), key=lambda v: v.Name)

    # One base number per view (scope box names are appended per sheet)
    base_numbers = get_base_numbers(source_views, config)
    jobs = [(v, base_numbers[v.Id.IntegerValue]) for v in source_views if v.Id.IntegerValue in base_numbers]

    # Horizontal viewport shift in inches. Negative = left, positive = right.
    viewport_shift_inches = getattr(config, "viewport_shift_inches", -1.625)

    # Get all scope boxes in the project
    scope_boxes = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)\
        .WhereElementIsNotElementType()\
        .ToElements()

    if not scope_boxes:
        forms.alert("No scope boxes found in the project.", exitscript=True)

    scope_box_options = {sb.Name: sb for sb in scope_boxes if sb.Name}
    sorted_scope_box_names = sorted(scope_box_options.keys())

    if not scope_box_options:
        forms.alert("No named scope boxes found in the project.", exitscript=True)

    # Scope boxes apply to every selected view
    selected_scope_boxes = forms.SelectFromList.show(
        sorted_scope_box_names,
        title="Select Scope Boxes (applied to every view)",
        multiselect=True,
        button_name="Select"
    )

    if not selected_scope_boxes:
        forms.alert("No scope boxes selected.", exitscript=True)

    # Title block
    title_blocks = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)\
        .WhereElementIsElementType()\
        .ToElements()

    if not title_blocks:
        forms.alert("No title block templates found.", exitscript=True)

    title_block_options = {tb.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString(): tb for tb in title_blocks}

    selected_title_block_name = forms.SelectFromList.show(
        title_block_options.keys(),
        title="Select Sheet Template",
        button_name="Select"
    )

    if not selected_title_block_name:
        forms.alert("No sheet template selected.", exitscript=True)

    selected_title_block = title_block_options[selected_title_block_name]

    created_sheets = []
    failed = []

    for source_view, base_number in jobs:
        for scope_box_name in selected_scope_boxes:
            t_view = None
            t_sheet = None
            sheet_number = "{}.{}".format(base_number, scope_box_name)

            try:
                scope_box = scope_box_options[scope_box_name]

                # Transaction 1: create and finalize the dependent view before placement.
                t_view = DB.Transaction(doc, "Create dependent view: {}".format(sheet_number))
                t_view.Start()

                dependent_view_id = source_view.Duplicate(DB.ViewDuplicateOption.AsDependent)
                dependent_view = doc.GetElement(dependent_view_id)

                new_view_name = "{} - {}".format(source_view.Name, scope_box_name)
                dependent_view.Name = new_view_name

                scope_param = dependent_view.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
                if not scope_param or scope_param.IsReadOnly:
                    raise Exception("Scope box parameter is unavailable or read-only for view {}".format(new_view_name))

                scope_param.Set(scope_box.Id)
                hide_categories(dependent_view)
                doc.Regenerate()

                t_view.Commit()
                t_view = None

                # Transaction 2: create the sheet and place the already-updated view.
                t_sheet = DB.Transaction(doc, "Create sheet and place view: {}".format(sheet_number))
                t_sheet.Start()

                sheet_name = new_view_name

                new_sheet = DB.ViewSheet.Create(doc, selected_title_block.Id)
                new_sheet.SheetNumber = sheet_number
                new_sheet.Name = sheet_name

                outline = new_sheet.Outline
                center_u = (outline.Max.U + outline.Min.U) / 2
                center_v = (outline.Max.V + outline.Min.V) / 2
                horizontal_shift = viewport_shift_inches / 12.0
                placement_point = DB.XYZ(center_u + horizontal_shift, center_v, 0)

                viewport = DB.Viewport.Create(doc, new_sheet.Id, dependent_view_id, placement_point)
                viewport.SetBoxCenter(placement_point)
                doc.Regenerate()

                try:
                    fit_view_title(viewport, dependent_view)
                except Exception as title_error:
                    print("View title not adjusted on {}: {}".format(sheet_number, title_error))

                t_sheet.Commit()
                t_sheet = None

                created_sheets.append((sheet_number, sheet_name))

            except Exception as e:
                if t_sheet:
                    try:
                        t_sheet.RollBack()
                    except Exception:
                        pass

                if t_view:
                    try:
                        t_view.RollBack()
                    except Exception:
                        pass

                failed.append((sheet_number, str(e)))
                print("Error creating {}: {}".format(sheet_number, str(e)))
                continue

    # Report results
    if created_sheets:
        message = "Created {} sheets from {} view(s):\n\n".format(len(created_sheets), len(jobs))
        for sheet_num, sheet_name in sorted(created_sheets, key=lambda item: item[0]):
            message += "- {}: {}\n".format(sheet_num, sheet_name)
        if failed:
            message += "\nNot created ({}):\n".format(len(failed))
            for sheet_num, reason in failed:
                message += "- {}: {}\n".format(sheet_num, reason)
        forms.alert(message, title="Success" if not failed else "Create Sheets")
    else:
        message = "No sheets were created."
        if failed:
            message += "\n\n" + "\n".join("- {}: {}".format(n, r) for n, r in failed)
        forms.alert(message, title="Warning")

except Exception as e:
    forms.alert("Script error: {}".format(str(e)), title="Error")
