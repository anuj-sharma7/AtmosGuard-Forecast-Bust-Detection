"""Ingestion of official data into AtmosGuard.

`sources.py` is the catalogue of where everything comes from. The modules
beside it fetch from those sources.

A caveat that belongs at the top: the network clients here were written in an
environment whose egress policy blocks every government data host, so they have
**not** been exercised against the live endpoints. Their parsing, URL building
and error handling are unit-tested against recorded fixtures; the HTTP call
itself is not. Treat the first real run as the test, and check the response
shape before trusting a bulk download.
"""
