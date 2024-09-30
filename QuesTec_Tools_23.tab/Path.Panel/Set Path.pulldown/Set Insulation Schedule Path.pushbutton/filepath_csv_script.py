import pyrevit
from pyrevit import forms
from Autodesk.Revit.DB import Transaction, GlobalParameter, ElementId, ForgeTypeId, SpecTypeId, FilteredElementCollector, BuiltInCategory, StringParameterValue

# Function to pick a CSV file using pyRevit forms
def pick_file():
    file_path = forms.pick_file(file_ext='csv', files_filter='CSV Files (*.csv)|*.csv', multi_file=False)
    #print file_path
    return file_path

# Function to find an existing global parameter by name
def find_global_parameter(doc, parameter_name):
    # Collect all global parameters in the document
    global_parameters = FilteredElementCollector(doc).OfClass(GlobalParameter).ToElements()

    # Search for the parameter by label name
    for param in global_parameters:
        if param.Name == parameter_name:  # Check the name using GetName()
            return param
    return None

# Function to add or update a global parameter
def set_global_parameter(doc, parameter_name, file_path):
    # Start a transaction to modify the Revit model
    with Transaction(doc, "Set Global Parameter") as t:
        t.Start()
        StringParameterValue

        # Find or create the global parameter
        global_param = find_global_parameter(doc, parameter_name)

        if global_param:
            # Update the existing global parameter value
            global_param.SetValue(StringParameterValue(file_path))
        else:
            # Create a new global parameter using ForgeTypeId for text parameters
            new_global_param = GlobalParameter.Create(doc, parameter_name, SpecTypeId.String.Text)
            new_global_param.SetValue(StringParameterValue(file_path))

        t.Commit()

# Main function
def main():
    doc = __revit__.ActiveUIDocument.Document

    # Pick a CSV file
    file_path = pick_file()

    if file_path:
        # Set the file path in a global parameter
        parameter_name = "InsulationSchedulePath"
        set_global_parameter(doc, parameter_name, file_path)

main()