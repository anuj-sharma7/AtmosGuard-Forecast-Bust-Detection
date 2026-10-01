"""Deterministic, reproducible pseudo-randomness.

The MVP must produce *identical* numbers for identical inputs: a judge
clicking Jaipur / Day 5 / Rainfall has to see the same 78% every time, and the
verification metrics must not drift between page loads.  We therefore derive
every random draw from a stable hash of the semantic key rather than from
global RNG state.
"""

from __future__ import annotations

import hashlib

import numpy as np


def stable_seed(*parts: object) -> int:
    """Return a stable 32-bit seed derived from ``parts``.

    ``hash()`` is salted per-process in Python, so we use blake2b instead.
    """
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") % (2**32)


def generator(*parts: object) -> np.random.Generator:
    """A numpy Generator keyed on the semantic identity of a forecast."""
    return np.random.default_rng(stable_seed(*parts))


def unit(*parts: object) -> float:
    """A stable pseudo-random float in [0, 1) for a semantic key.

    Useful for latent per-location/per-date drivers that must stay fixed.
    """
    return float(generator(*parts).random())
