# -*- coding: utf-8 -*-

from pyrevit import forms, script


def main():
    config = script.get_config()
    current_shift = getattr(config, "viewport_shift_inches", -1.5)

    shift_input = forms.ask_for_string(
        default=str(current_shift),
        prompt="Enter viewport horizontal shift in inches (negative = left, positive = right):",
        title="Create Sheets Viewport Shift"
    )

    if shift_input is None:
        script.exit()

    shift_input = shift_input.strip()
    if not shift_input:
        forms.alert("No viewport shift provided.", exitscript=True)

    try:
        shift_value = float(shift_input)
    except Exception:
        forms.alert("Invalid viewport shift value: {}".format(shift_input), exitscript=True)

    config.viewport_shift_inches = shift_value
    script.save_config()

    forms.alert(
        "Viewport horizontal shift saved: {} in\nNegative = left, positive = right".format(shift_value),
        title="Create Sheets Settings"
    )


if __name__ == "__main__":
    main()
