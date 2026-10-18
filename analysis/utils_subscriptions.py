"""
Capsule Club Analytics — curva de retención de suscripción, compartida.

Vive aparte de `utils_timeseries.py` a propósito: aquello es lógica genérica de
serie temporal y esto es una medida de negocio concreta, la curva de retención
por edad de la suscripción (meses desde el alta), ponderada por el tamaño de
cada cohorte.

La usa `04_cohorts_rfm` para las curvas por canal, por descuento y por regalo,
y para proyectar el LTV por canal.

La retención se mide sobre `is_active_eom`, que ignora las pausas, porque si se
midiera sobre los activos netos las pausas de agosto entrarían como "churn a los
N meses" en cohortes que se dieron de alta en meses distintos y contaminarían la
curva. La pausa es un efecto de calendario, no de edad.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "RetentionCurve",
    "build_retention_curve",
    "MIN_COHORT_SIZE",
    "TAIL_AGES",
]

MIN_COHORT_SIZE = 10   # cohortes más pequeñas dan ratios de retención inestables
TAIL_AGES = 6          # edades del final de la curva que fijan el hazard de estado estable



# =============================================================================
# 1. CURVA DE RETENCIÓN
# =============================================================================

@dataclass
class RetentionCurve:
    """
    Curva de retención por edad, con su cola extrapolada.

    `values` está reindexada a todas las edades de 0 a `max_observed_age`, así
    que `at()` nunca falla por un hueco. Más allá de esa edad se extrapola con
    `tail_hazard`, el hazard medio de las últimas edades observadas.
    """

    values: pd.Series
    hazard: pd.Series
    n_cohorts_by_age: pd.Series
    max_observed_age: int
    tail_hazard: float
    weighted_by_recency: bool

    def at(self, age: int) -> float:
        """Retención a una edad, extrapolando más allá de lo observado."""
        if age <= 0:
            return 1.0
        if age <= self.max_observed_age:
            return max(float(self.values.loc[age]), 1e-6)
        extra = age - self.max_observed_age
        return max(float(self.values.loc[self.max_observed_age]) * (1 - self.tail_hazard) ** extra,
                   1e-6)

    def survival_ratio(self, from_age: int, to_age: int) -> float:
        """Probabilidad de llegar a `to_age` dado que se está vivo a `from_age`."""
        return self.at(to_age) / self.at(from_age)

    def to_records(self) -> list[dict[str, Any]]:
        return [
            {"age": int(age), "retention": float(value),
             "n_cohorts": int(self.n_cohorts_by_age.get(age, 0))}
            for age, value in self.values.items()
        ]


def build_retention_curve(
    facts: pd.DataFrame,
    cutoff: pd.Timestamp | None = None,
    min_cohort: int = MIN_COHORT_SIZE,
    recency_halflife: float | None = None,
    tail_ages: int = TAIL_AGES,
) -> RetentionCurve:
    """
    Curva de retención agregada, ponderada por tamaño de cohorte.

    En cada edad se divide la suma de activos entre la suma de altas de las
    cohortes que han llegado a observar esa edad. Ponderar por tamaño evita que
    una cohorte de 12 altas pese lo mismo que una de 250.

    `recency_halflife` (en meses) añade un peso exponencial que da más
    importancia a las cohortes recientes. Existe porque la curva agregada tiene
    un sesgo de supervivencia conocido: **sólo las cohortes antiguas han llegado
    a las edades altas**, y en este negocio son precisamente las que mejor
    retienen (las de 2026 se quedan en 65% a los 6 meses frente al 69-73% de las
    anteriores). Sin ponderar, la cola de la curva es optimista y lo que se
    proyecte con ella (el LTV) hereda un sesgo positivo. Con `None` se desactiva.
    """
    frame = facts if cutoff is None else facts[facts["month_start"] <= cutoff]

    pivot = frame.pivot_table(index="cohort_month", columns="months_since_start",
                              values="is_active_eom", aggfunc="sum")
    size = pivot[0]
    kept = size >= min_cohort
    pivot, size = pivot[kept], size[kept]
    if pivot.empty:
        raise ValueError(
            f"No queda ninguna cohorte con al menos {min_cohort} altas hasta {cutoff}."
        )

    weights = pd.Series(1.0, index=pivot.index)
    if recency_halflife:
        # Peso exponencial por antigüedad de la cohorte respecto a la más reciente.
        newest = pivot.index.max()
        months_old = np.array([(newest.year - c.year) * 12 + newest.month - c.month
                               for c in pivot.index], dtype=float)
        weights = pd.Series(0.5 ** (months_old / float(recency_halflife)), index=pivot.index)

    observed = pivot.notna()
    numerator = pivot.mul(weights, axis=0).sum(axis=0, skipna=True)
    denominator = observed.mul(size * weights, axis=0).sum(axis=0)
    curve = (numerator / denominator).sort_index().dropna()

    max_age = int(curve.index.max())
    curve = curve.reindex(range(0, max_age + 1)).interpolate().ffill()
    hazard = (1 - curve / curve.shift(1)).dropna()
    tail = float(hazard.tail(tail_ages).mean()) if len(hazard) else 0.0

    return RetentionCurve(
        values=curve,
        hazard=hazard,
        n_cohorts_by_age=observed.sum(axis=0),
        max_observed_age=max_age,
        tail_hazard=tail,
        weighted_by_recency=bool(recency_halflife),
    )
