# -*- coding: utf-8 -*-

from pyrevit import forms, script


def main():
    options = [
        "Show Mechanical Equipment",
        "Hide Mechanical Equipment",
    ]

    current_value = getattr(script.get_config(), "include_mechanical_equipment", True)
    current_label = "Show Mechanical Equipment" if current_value else "Hide Mechanical Equipment"

    choice = forms.CommandSwitchWindow.show(
        options,
        message="When isolating by system, what should happen to mechanical equipment?\nCurrent: {0}".format(current_label)
    )

    if not choice:
        script.exit()

    config = script.get_config()
    config.include_mechanical_equipment = (choice == "Show Mechanical Equipment")
    script.save_config()

    forms.alert(
        "Saved setting: {0}".format(choice),
        title="By System Shift Config"
    )


if __name__ == "__main__":
    main()
