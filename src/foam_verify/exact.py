"""Exact reference values for the verification studies.

Fully developed laminar flow in a rectangular duct: the Poisson problem for the axial velocity
has a Fourier series solution, and integrating it gives the friction factor in closed form up to
one rapidly converging series (Shah and London 1978, "Laminar Flow Forced Convection in Ducts",
Academic Press, chapter on rectangular ducts). The value is computed here rather than copied, so
the reference carries as many digits as the study needs.
"""

from __future__ import annotations

import math


def rectangular_duct_fre(aspect: float, *, darcy: bool = True, tol: float = 1e-15) -> float:
    """Friction factor times Reynolds number (hydraulic diameter) for a rectangular duct.

    ``aspect`` is short side / long side, in (0, 1]. Returns the Darcy value by default
    (Fanning = Darcy / 4). The square duct (aspect 1) gives Darcy f Re = 56.908.
    """
    if not 0.0 < aspect <= 1.0:
        raise ValueError(f"aspect must be in (0, 1], got {aspect}")
    total = 0.0
    n = 1
    while True:
        term = math.tanh(n * math.pi / (2.0 * aspect)) / n**5
        total += term
        if term < tol * total:
            break
        n += 2
    bracket = 1.0 - 192.0 * aspect / math.pi**5 * total
    fanning = 24.0 / ((1.0 + aspect) ** 2 * bracket)
    return 4.0 * fanning if darcy else fanning
