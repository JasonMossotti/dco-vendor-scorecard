"""A minimal stand-in for Streamlit so CI can run the whole app script.

It records every element the app draws and returns sensible widget values
(the default, or an override set by the test). It checks real-world mistakes:
tables must be DataFrames, charts must have data, and the script must reach
the end without raising.
"""

from __future__ import annotations

import re

import pandas as pd

_UNESCAPED_DOLLAR = re.compile(r"(?<!\\)\$")


class StopApp(Exception):
    pass


class RerunApp(Exception):
    pass


class _Block:
    """A container (tab, column, expander, spinner): proxies calls to the app."""

    def __init__(self, app: "FakeStreamlit"):
        self._app = app

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(self._app, name)


class _Sidebar(_Block):
    def __getattr__(self, name):
        self._app.sidebar_used.append(name)
        return getattr(self._app, name)


class FakeStreamlit:
    def __init__(self, overrides: dict | None = None, buttons: set | None = None,
                 session_state: dict | None = None):
        self.session_state: dict = dict(session_state or {})
        self.overrides = overrides or {}       # label -> value returned by that widget
        self.buttons = buttons or set()        # labels of buttons that are "pressed"
        self.drawn: list[tuple[str, object]] = []
        self.sidebar_used: list[str] = []      # names of st.sidebar calls; the app draws nothing there
        self.sidebar = _Sidebar(self)

    # ---------------------------------------------------------------- record
    def _rec(self, kind, payload=None):
        self.drawn.append((kind, payload))

    def texts(self, kind=None) -> list[str]:
        return [str(p) for k, p in self.drawn if kind is None or k == kind]

    # --------------------------------------------------------------- layout
    def set_page_config(self, **kw):
        self._rec("page_config", kw)

    def tabs(self, names):
        self._rec("tabs", names)
        return [_Block(self) for _ in names]

    def columns(self, spec, **kw):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Block(self) for _ in range(n)]

    def expander(self, label, expanded=False):
        self._rec("expander", label)
        return _Block(self)

    def spinner(self, text=""):
        return _Block(self)

    def popover(self, label, **kw):
        self._rec("popover", label)
        return _Block(self)

    # ---------------------------------------------------------------- text
    def __getattr__(self, name):
        if name in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error",
                    "success", "write", "divider", "text"):
            def draw(*a, **k):
                text = str(a[0]) if a else ""
                # Real Streamlit renders text between two unescaped $ signs as LaTeX math.
                assert len(_UNESCAPED_DOLLAR.findall(text)) < 2, f"unescaped $ in st.{name}: {text[:80]!r}"
                self._rec(name, text)
            return draw
        raise AttributeError(f"FakeStreamlit has no '{name}'; add it if the app uses a new Streamlit feature")

    def metric(self, label, value, *a, **k):
        self._rec("metric", (label, value))

    # ------------------------------------------------------- data and charts
    def dataframe(self, data, **kw):
        assert isinstance(data, pd.DataFrame), "st.dataframe expects a DataFrame"
        self._rec("dataframe", data)

    def image(self, image, caption=None, width=None, **kw):
        assert isinstance(image, str) and image.lstrip().startswith("<svg") and 'xmlns="http://www.w3.org/2000/svg"' in image, \
            "the app shows drawings as SVG strings (st.image renders those in an img tag, which needs xmlns)"
        assert width is None or isinstance(width, int), "an integer width works on every Streamlit version the app supports"
        self._rec("image", image)

    def _chart(self, kind, data, **kw):
        assert isinstance(data, pd.DataFrame) and not data.empty, f"{kind} needs a non-empty DataFrame"
        self._rec(kind, data)

    def bar_chart(self, data, **kw):
        if len(data.columns) > 1:
            assert kw.get("stack") is False, "multi-series bar charts must use stack=False to compare side by side"
        self._chart("bar_chart", data, **kw)

    def line_chart(self, data, **kw):
        if isinstance(kw.get("color"), list):
            assert len(kw["color"]) == len(data.columns), "one color per line is required"
        self._chart("line_chart", data, **kw)

    # -------------------------------------------------------------- widgets
    def _value(self, label, default, key=None):
        """Test override > session state (as real Streamlit) > widget default."""
        if label in self.overrides:
            v = self.overrides[label]
            if key:
                self.session_state[key] = v
            return v
        if key and key in self.session_state:
            return self.session_state[key]
        return default

    def radio(self, label, options, index=0, **kw):
        return self._value(label, options[index])

    def segmented_control(self, label, options, default=None, key=None, on_change=None, **kw):
        self._rec("segmented_control", (label, list(options)))
        if key and key in self.session_state and default is not None:
            raise AssertionError(f"'{label}' sets both a default and a session-state value (Streamlit warns on screen)")
        return self._value(label, default, key)

    def selectbox(self, label, options, index=0, format_func=str, key=None, **kw):
        for o in options:
            format_func(o)
        return self._value(label, options[index], key)

    def multiselect(self, label, options, default=None, **kw):
        return self._value(label, list(default or []))

    def slider(self, label, min_value=None, max_value=None, value=None, step=None, key=None, **kw):
        self._rec("slider", label)
        v = self._value(label, value if value is not None else min_value, key)
        assert min_value <= v <= max_value, f"slider '{label}' value {v} outside [{min_value}, {max_value}]"
        return v

    def number_input(self, label, min_value=None, max_value=None, value=None, step=None, key=None, **kw):
        return self._value(label, value if value is not None else min_value, key)

    def text_input(self, label, value="", key=None, **kw):
        return self._value(label, value, key)

    def checkbox(self, label, value=False, **kw):
        return self._value(label, value)

    def button(self, label, on_click=None, **kw):
        pressed = label in self.buttons
        if pressed and on_click is not None:
            on_click()               # Streamlit runs callbacks before the rest of the script
        return pressed

    # ---------------------------------------------------------- control flow
    def stop(self):
        raise StopApp()

    def rerun(self):
        raise RerunApp()
