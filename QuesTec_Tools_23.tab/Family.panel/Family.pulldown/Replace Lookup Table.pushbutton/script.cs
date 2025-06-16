using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using System.Text;

[Transaction(TransactionMode.Manual)]
public class ReplaceLookupTable : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        UIApplication uiapp = commandData.Application;
        UIDocument uidoc = uiapp.ActiveUIDocument;
        Document doc = uidoc.Document;

        try
        {
            // Step 1: Get selected family instance or ask user to select one
            FamilyInstance familyInstance = null;
            
            // Check if there's already a selection
            ICollection<ElementId> selectedIds = uidoc.Selection.GetElementIds();
            if (selectedIds.Count == 1)
            {
                Element selectedElement = doc.GetElement(selectedIds.First());
                if (selectedElement is FamilyInstance)
                {
                    familyInstance = selectedElement as FamilyInstance;
                }
            }

            // If no valid selection, ask user to pick a family instance
            if (familyInstance == null)
            {
                try
                {
                    Reference reference = uidoc.Selection.PickObject(ObjectType.Element, 
                        "Please select a family instance");
                    Element selectedElement = doc.GetElement(reference);
                    if (selectedElement is FamilyInstance)
                    {
                        familyInstance = selectedElement as FamilyInstance;
                    }
                    else
                    {
                        TaskDialog.Show("Error", "Selected element is not a family instance.");
                        return Result.Failed;
                    }
                }
                catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                {
                    // User cancelled the selection
                    return Result.Cancelled;
                }
            }

            // Get the family from the instance
            Family family = familyInstance.Symbol.Family;
            
            // Step 2: Browse for CSV file
            OpenFileDialog openFileDialog = new OpenFileDialog();
            openFileDialog.Filter = "CSV files (*.csv)|*.csv";
            openFileDialog.Title = "Select CSV file for lookup table";
            
            if (openFileDialog.ShowDialog() != DialogResult.OK)
            {
                return Result.Cancelled;
            }
            
            string csvFilePath = openFileDialog.FileName;
            string lookupTableName = Path.GetFileNameWithoutExtension(csvFilePath);
            
            // Step 3: Read CSV file content
            List<string[]> csvData = new List<string[]>();
            using (StreamReader reader = new StreamReader(csvFilePath))
            {
                string line;
                while ((line = reader.ReadLine()) != null)
                {
                    csvData.Add(line.Split(','));
                }
            }
            
            if (csvData.Count == 0)
            {
                TaskDialog.Show("Error", "CSV file is empty.");
                return Result.Failed;
            }
            
            // Step 4: Open family document and replace lookup table
            Document familyDoc = doc.EditFamily(family);
            
            using (Transaction trans = new Transaction(familyDoc, "Replace Lookup Table"))
            {
                trans.Start();
                
                // Find lookup table with matching name
                FilteredElementCollector collector = new FilteredElementCollector(familyDoc)
                    .OfClass(typeof(LookupTableElement));
                    
                LookupTableElement lookupTable = null;
                foreach (LookupTableElement table in collector)
                {
                    if (table.Name == lookupTableName)
                    {
                        lookupTable = table;
                        break;
                    }
                }
                
                if (lookupTable == null)
                {
                    TaskDialog.Show("Error", $"No lookup table named '{lookupTableName}' found in the family.");
                    trans.RollBack();
                    familyDoc.Close(false);
                    return Result.Failed;
                }
                
                // Clear existing data
                lookupTable.ClearValues();
                
                // Determine the number of parameters
                int paramCount = csvData[0].Length - 1; // First column is input
                if (paramCount < 1)
                {
                    TaskDialog.Show("Error", "CSV format incorrect. Need at least one parameter column.");
                    trans.RollBack();
                    familyDoc.Close(false);
                    return Result.Failed;
                }
                
                // Add new data from CSV
                for (int i = 1; i < csvData.Count; i++) // Skip header row
                {
                    if (csvData[i].Length >= paramCount + 1)
                    {
                        double inputValue;
                        if (double.TryParse(csvData[i][0], out inputValue))
                        {
                            double[] outputValues = new double[paramCount];
                            bool validRow = true;
                            
                            for (int j = 0; j < paramCount; j++)
                            {
                                if (!double.TryParse(csvData[i][j + 1], out outputValues[j]))
                                {
                                    validRow = false;
                                    break;
                                }
                            }
                            
                            if (validRow)
                            {
                                lookupTable.SetValues(inputValue, outputValues);
                            }
                        }
                    }
                }
                
                trans.Commit();
            }
            
            // Step 5: Load the modified family back into project
            familyDoc.LoadFamily(doc, new FamilyLoadOptions());
            familyDoc.Close(false);
            
            TaskDialog.Show("Success", $"Lookup table '{lookupTableName}' has been updated successfully.");
            
            return Result.Succeeded;
        }
        catch (Exception ex)
        {
            TaskDialog.Show("Error", ex.Message);
            return Result.Failed;
        }
    }

    // FamilyLoadOptions implementation to handle family load
    private class FamilyLoadOptions : IFamilyLoadOptions
    {
        public bool OnFamilyFound(bool familyInUse, out bool overwriteParameterValues)
        {
            overwriteParameterValues = true;
            return true;
        }

        public bool OnSharedFamilyFound(Family sharedFamily, bool familyInUse, out FamilySource source, out bool overwriteParameterValues)
        {
            source = FamilySource.Family;
            overwriteParameterValues = true;
            return true;
        }
    }
}