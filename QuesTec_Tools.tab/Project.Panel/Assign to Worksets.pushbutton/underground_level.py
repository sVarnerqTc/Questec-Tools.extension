# -*- coding: utf-8 -*-
"""Remember which level defines 'underground' for each project.

Stored per user in a pyRevit data file, keyed by the project's central model
path (or file path / title for non-workshared models).
"""

import json
import os

from Autodesk.Revit.DB import FilteredElementCollector, Level, ModelPathUtils
from pyrevit import forms, script


DATA_FILE_ID = "QTC_UndergroundLevels"


def _data_path():
    return script.get_universal_data_file(DATA_FILE_ID, "json")


def _load():
    path = _data_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    with open(_data_path(), "w") as f:
        json.dump(data, f, indent=2)


def project_key(doc):
    try:
        if doc.IsWorkshared:
            central = doc.GetWorksharingCentralModelPath()
            if central is not None:
                return ModelPathUtils.ConvertModelPathToUserVisiblePath(central).lower()
    except Exception:
        pass
    if doc.PathName:
        return doc.PathName.lower()
    return doc.Title.lower()


def get_saved_level(doc):
    unique_id = _load().get(project_key(doc))
    if not unique_id:
        return None
    try:
        level = doc.GetElement(unique_id)
    except Exception:
        level = None
    return level if isinstance(level, Level) else None


def pick_level(doc, title="Pick Underground Level"):
    levels = sorted(
        FilteredElementCollector(doc).OfClass(Level).ToElements(),
        key=lambda lv: lv.ProjectElevation,
    )
    if not levels:
        forms.alert("No levels found in this project.", title=title)
        return None

    options = {}
    for lv in levels:
        label = u"{0}   ({1:.2f} ft)".format(lv.Name, lv.ProjectElevation)
        options[label] = lv
    labels = sorted(options.keys(), key=lambda k: options[k].ProjectElevation)

    choice = forms.SelectFromList.show(
        labels,
        title="{0} - elements below this level go to Pipe - Underground".format(title),
        button_name="Use This Level",
        multiselect=False,
    )
    if not choice:
        return None
    if isinstance(choice, list):
        choice = choice[0]

    level = options[choice]
    data = _load()
    data[project_key(doc)] = level.UniqueId
    _save(data)
    return level


def get_or_pick_level(doc):
    level = get_saved_level(doc)
    if level is not None:
        return level
    return pick_level(doc)
