# -*- coding: utf-8 -*-

import json
import os
import tempfile
from datetime import datetime

import clr

clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import Clipboard

from pyrevit import DB, forms, revit, script


doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()


def safe_text(value):
    try:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    except Exception:
        return None


def safe_element_name(element):
    if element is None:
        return None

    for attr_name in ("Name",):
        try:
            value = getattr(element, attr_name, None)
            text = safe_text(value)
            if text:
                return text
        except Exception:
            continue

    try:
        type_name = element.GetType().Name
        return safe_text(type_name)
    except Exception:
        return None


def get_parameter_value(parameter):
    if not parameter or not parameter.HasValue:
        return None

    try:
        storage_type = parameter.StorageType
        if storage_type == DB.StorageType.String:
            return safe_text(parameter.AsString() or parameter.AsValueString())
        if storage_type == DB.StorageType.Integer:
            value = parameter.AsInteger()
            return value
        if storage_type == DB.StorageType.Double:
            value_string = safe_text(parameter.AsValueString())
            return value_string if value_string is not None else parameter.AsDouble()
        if storage_type == DB.StorageType.ElementId:
            element_id = parameter.AsElementId()
            if element_id and element_id != DB.ElementId.InvalidElementId:
                return element_id.IntegerValue
    except Exception:
        return None

    return safe_text(parameter.AsValueString() or parameter.AsString())


def collect_parameters(element, parameter_names):
    values = {}
    for parameter_name in parameter_names:
        try:
            parameter = element.LookupParameter(parameter_name)
        except Exception:
            parameter = None

        value = get_parameter_value(parameter)
        if value not in (None, ""):
            values[parameter_name] = value

    return values


def collect_element_snapshot(element):
    record = {
        "element_id": element.Id.IntegerValue,
        "unique_id": safe_text(getattr(element, "UniqueId", None)),
        "class_name": safe_text(element.GetType().Name),
        "category": safe_text(element.Category.Name if element.Category else None),
        "name": safe_element_name(element),
    }

    try:
        type_id = element.GetTypeId()
        if type_id and type_id != DB.ElementId.InvalidElementId:
            type_element = doc.GetElement(type_id)
            if type_element:
                record["type_id"] = type_id.IntegerValue
                record["type_name"] = safe_element_name(type_element)
    except Exception:
        pass

    try:
        family_name = None
        if isinstance(element, DB.FamilyInstance):
            family = element.Symbol.Family if element.Symbol else None
            if family:
                family_name = safe_text(family.Name)
        if family_name:
            record["family_name"] = family_name
    except Exception:
        pass

    try:
        workset_id = element.WorksetId
        if workset_id and workset_id != DB.ElementId.InvalidElementId:
            record["workset_id"] = workset_id.IntegerValue
    except Exception:
        pass

    interesting_parameters = [
        "Mark",
        "Comments",
        "Type Comments",
        "System Type",
        "System Abbreviation",
        "BOP",
        "Diameter",
        "Diameter1",
        "Width",
        "Height",
        "Length",
        "Size",
        "Nominal Diameter",
        "Level",
    ]
    record["parameters"] = collect_parameters(element, interesting_parameters)

    try:
        bbox = element.get_BoundingBox(doc.ActiveView)
        if bbox:
            record["bounding_box"] = {
                "min": [bbox.Min.X, bbox.Min.Y, bbox.Min.Z],
                "max": [bbox.Max.X, bbox.Max.Y, bbox.Max.Z],
            }
    except Exception:
        pass

    return record


def collect_selection_context():
    selection_ids = list(uidoc.Selection.GetElementIds())
    selected_elements = []

    for element_id in selection_ids:
        try:
            element = doc.GetElement(element_id)
            if element:
                selected_elements.append(element)
        except Exception:
            continue

    if selected_elements:
        return {
            "mode": "selection",
            "count": len(selected_elements),
            "elements": [collect_element_snapshot(element) for element in selected_elements],
        }

    active_view = doc.ActiveView
    return {
        "mode": "active_view",
        "count": 0,
        "view": {
            "element_id": active_view.Id.IntegerValue,
            "name": safe_text(active_view.Name),
            "view_type": safe_text(active_view.ViewType.ToString()),
            "scale": getattr(active_view, "Scale", None),
        },
    }


def build_context_payload():
    project_info = getattr(doc, "ProjectInformation", None)

    payload = {
        "source": "pyrevit",
        "tool": "Claude Desktop Handoff",
        "created_utc": datetime.utcnow().isoformat() + "Z",
        "revit": {
            "document_title": safe_text(doc.Title),
            "document_path": safe_text(doc.PathName),
            "is_workshared": bool(doc.IsWorkshared),
            "version": safe_text(doc.Application.VersionNumber),
            "sub_version": safe_text(doc.Application.SubVersionNumber),
        },
        "project_information": {
            "name": safe_text(project_info.Name) if project_info else None,
            "number": safe_text(project_info.Number) if project_info else None,
            "client_name": safe_text(project_info.ClientName) if project_info else None,
        },
        "active_view": {
            "element_id": doc.ActiveView.Id.IntegerValue,
            "name": safe_text(doc.ActiveView.Name),
            "view_type": safe_text(doc.ActiveView.ViewType.ToString()),
            "discipline": safe_text(doc.ActiveView.Discipline.ToString()) if hasattr(doc.ActiveView, "Discipline") else None,
        },
        "selection": collect_selection_context(),
    }

    return payload


def write_handoff_file(payload):
    output_dir = os.path.join(tempfile.gettempdir(), "QuesTec_Revit_Claude")
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    output_path = os.path.join(output_dir, "latest_revit_context.json")
    with open(output_path, "w") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True)

    return output_path


def copy_to_clipboard(text):
    try:
        Clipboard.SetText(text)
        return True
    except Exception as exc:
        logger.warning("Clipboard copy failed: {}".format(exc))
        return False


def main():
    payload = build_context_payload()
    handoff_path = write_handoff_file(payload)

    clipboard_text = json.dumps(payload, indent=2, sort_keys=True)
    clipboard_ok = copy_to_clipboard(clipboard_text)

    if payload["selection"]["mode"] == "selection":
        scope_message = "{} selected element(s)".format(payload["selection"]["count"])
    else:
        scope_message = "active view only"

    message = [
        "Revit context exported for Claude Desktop.",
        "Scope: {}".format(scope_message),
        "File: {}".format(handoff_path),
    ]
    if clipboard_ok:
        message.append("The JSON was also copied to the clipboard.")
    else:
        message.append("Clipboard copy failed; use the JSON file instead.")

    forms.alert("\n".join(message), title="Claude Desktop Handoff")


if __name__ == "__main__":
    main()