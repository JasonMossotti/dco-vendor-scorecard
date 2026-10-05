"""Live collector: read real facility equipment, read-only, into the dataset contract.

The collector writes the same files the synthetic generator writes (see
docs/DATA_MODEL.md), so the engines, scorecards, reports, and app run on live
data unchanged. Every adapter is read-only by construction, and a test fails
if write-capable calls appear anywhere in this package.

Optional dependencies: ``pip install -r requirements-live.txt``. Nothing in the
core package or the browser app imports this package.
"""
