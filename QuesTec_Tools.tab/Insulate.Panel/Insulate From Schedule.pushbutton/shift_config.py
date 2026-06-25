# -*- coding: utf-8 -*-

from pyrevit import forms
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    GlobalParameter,
    SpecTypeId,
    StringParameterValue,
    Transaction,
)

INSULATION_SCHEDULE_PARAM_NAME = "Insulation Schedule Path"


def pick_schedule_file():
    return forms.pick_file(
        file_ext='csv',
        files_filter='CSV Files (*.csv)|*.csv',
        multi_file=False,
    )


def find_global_parameter(doc, parameter_name):
    global_parameters = FilteredElementCollector(doc).OfClass(GlobalParameter).ToElements()
    for gp in global_parameters:
        if gp.Name == parameter_name:
            return gp
    return None


def set_global_parameter(doc, parameter_name, value):
    with Transaction(doc, 'Set Insulation Schedule Path') as tx:
        tx.Start()
        gp = find_global_parameter(doc, parameter_name)
        if gp:
            gp.SetValue(StringParameterValue(value))
        else:
            new_gp = GlobalParameter.Create(doc, parameter_name, SpecTypeId.String.Text)
            new_gp.SetValue(StringParameterValue(value))
        tx.Commit()


def main():
    doc = __revit__.ActiveUIDocument.Document

    csv_path = pick_schedule_file()
    if not csv_path:
        forms.alert('No schedule file selected.', exitscript=True)
        return

    set_global_parameter(doc, INSULATION_SCHEDULE_PARAM_NAME, csv_path)
    forms.alert('Insulation schedule path set.', title='Insulate From Schedule')


if __name__ == '__main__':
    main()
