"""Opens a specific URL in the default web browser.
-------------------------------------
Provides quick access to the QC checklist website.
"""

import webbrowser
from pyrevit import script, forms

# The URL to navigate to (replace this with your actual link)
target_url = "https://questecbim.atlassian.net/wiki/x/AQCFAg"

def open_link():
    try:
        # Open URL in default browser
        webbrowser.open_new(target_url)
        
        # Show success message
        # forms.alert("QC Checklist opened in your browser.", title="Success")
    except Exception as e:
        # Handle any errors
        error_msg = "Failed to open link: {}".format(str(e))
        forms.alert(error_msg, title="Error")
        script.get_logger().error(error_msg)

if __name__ == '__main__':
    open_link()