"""Event type shared by the pure engines and the Quartz executor."""


class Event:
    """kind: move click right_click drag_start drag_move drag_end scroll space tile head gaze.
    value: kind specific (positions are normalised screen coords (nx, ny)).
    pulse: True when the gadget pulse dot should flash."""
    __slots__ = ("kind", "value", "pulse")

    def __init__(self, kind, value=None, pulse=False):
        self.kind, self.value, self.pulse = kind, value, pulse

    def __repr__(self):
        return f"Event({self.kind!r}, {self.value!r}{', pulse' if self.pulse else ''})"
