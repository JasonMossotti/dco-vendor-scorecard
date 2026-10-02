"""A minimal stand-in for Streamlit so CI can run the whole app script.

It records every element the app draws and returns sensible widget values
(the default, or an override set by the test). It checks real-world mistakes:
tables must be DataFrames, charts must have data, and the script must reach
the end without raising.
"""

from __future__ import annotations

import pandas as pd


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


class FakeStreamlit:
    def __init__(self, overrides: dict | None = None, buttons: set | None = None):
        self.session_state: dict = {}
        self.overrides = overrides or {}       # label -> value returned by that widget
        self.buttons = buttons or set()        # labels of buttons that are "pressed"
        self.drawn: list[tuple[str, object]] = []
        self.sidebar = _Block(self)

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

    def columns(self, spec):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Block(self) for _ in range(n)]

    def expander(self, label, expanded=False):
        self._rec("expander", label)
        return _Block(self)

    def spinner(self, text=""):
        return _Block(self)

    # ---------------------------------------------------------------- text
    def __getattr__(self, name):
        if name in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error",
                    "success", "write", "divider", "text"):
            return lambda *a, **k: self._rec(name, a[0] if a else "")
        raise AttributeError(f"FakeStreamlit has no '{name}'; add it if the app uses a new Streamlit feature")

    def metric(self, label, value, *a, **k):
        self._rec("metric", (label, value))

    # ------------------------------------------------------- data and charts
    def dataframe(self, data, **kw):
        assert isinstance(data, pd.DataFrame), "st.dataframe expects a DataFrame"
        self._rec("dataframe", data)

    def _chart(self, kind, data, **kw):
        assert isinstance(data, pd.DataFrame) and not data.empty, f"{kind} needs a non-empty DataFrame"
        self._rec(kind, data)

    def bar_chart(self, data, **kw):
        self._chart("bar_chart", data, **kw)

    def line_chart(self, data, **kw):
        self._chart("line_chart", data, **kw)

    # -------------------------------------------------------------- widgets
    def _value(self, label, default):
        return self.overrides.get(label, default)

    def radio(self, label, options, index=0, **kw):
        return self._value(label, options[index])

    def selectbox(self, label, options, index=0, format_func=str, **kw):
        for o in options:
            format_func(o)
        return self._value(label, options[index])

    def multiselect(self, label, options, default=None, **kw):
        return self._value(label, list(default or []))

    def slider(self, label, min_value=None, max_value=None, value=None, step=None, **kw):
        v = self._value(label, value)
        assert min_value <= v <= max_value, f"slider '{label}' value {v} outside [{min_value}, {max_value}]"
        return v

    def number_input(self, label, min_value=None, max_value=None, value=None, step=None, **kw):
        return self._value(label, value)

    def checkbox(self, label, value=False, **kw):
        return self._value(label, value)

    def button(self, label, **kw):
        return label in self.buttons

    # ---------------------------------------------------------- control flow
    def stop(self):
        raise StopApp()

    def rerun(self):
        raise RerunApp()
