"""Predictive maintenance: detectors that read condition data and propose work before a failure.

``methods`` and ``detectors`` use the Python standard library only and take plain rows in the
columns a real feed produces (documented in docs/predict/README.md), so a site can run them on
its own exports with ``scripts/predict.py``. ``review`` is this repository's wiring: it runs the
detectors on the synthetic condition history and the sample month, and scores the backtest.
"""
