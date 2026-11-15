"""Event type shared by the pure engines and the Quartz executor."""


class Event:
    """kind: move drag_start drag_move drag_end scroll gesture head gaze write.
    value: kind specific (positions are normalised screen coords (nx, ny)); "gesture" carries
    {"id": gesture_id, "pos": (nx, ny) | None}, "scroll" signed px (hand up = positive).
    "write" carries {"op": "text", "text": "a"} or {"op": "enter"} (a letter recognised on the air-writing canvas).
    See bindings.gesture_of for how an event maps to a gesture id.
    pulse: True when the gadget pulse dot should flash."""
    __slots__ = ("kind", "value", "pulse")

    def __init__(self, kind, value=None, pulse=False):
        self.kind, self.value, self.pulse = kind, value, pulse

    def __repr__(self):
        return f"Event({self.kind!r}, {self.value!r}{', pulse' if self.pulse else ''})"
