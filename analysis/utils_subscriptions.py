"""
Capsule Club Analytics — modelo de cohortes de suscripción, compartido.

Vive aparte de `utils_timeseries.py` a propósito: aquello es lógica genérica de
serie temporal y esto es un modelo de negocio concreto, el que descompone los
suscriptores activos en

    activos_netos(t) = [ cohortes vivas · retención(edad)
                         + altas nuevas · retención(edad) ] · (1 − pausa(mes))
                       \\____ efecto de EDAD ____/   \\__ efecto de CALENDARIO __/

Lo usan dos notebooks y por razones distintas:

  - `01_time_series_suscriptores` lo compara contra un SARIMA sobre el agregado;
  - `02_time_series_ingresos` lo encadena con el ingreso por activo para
    pronosticar el canal de suscripción, que es el 40% del ingreso.

Que viva aquí es lo que evita que el notebook 02 tenga que leer el JSON de
salida del 01: no hay orden de ejecución impuesto entre notebooks, sólo una
dependencia de código.

Separar edad de calendario es la decisión de diseño que da valor al modelo. La
retención se mide sobre `is_active_eom`, que ignora las pausas, porque si se
midiera sobre los activos netos las pausas de agosto entrarían como "churn a los
N meses" en cohortes que se dieron de alta en meses distintos y contaminarían la
curva. La pausa se aplica después, como factor del mes natural.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "RetentionCurve",
    "build_retention_curve",
    "pause_rate_by_month",
    "project_signups",
    "forecast_active_subscribers",
    "make_subscriber_forecaster",
    "inner_bias_correction",
    "MIN_COHORT_SIZE",
    "TREND_WINDOW",
    "TAIL_AGES",
    "SIGNUP_DAMPING",
]

MIN_COHORT_SIZE = 10   # cohortes más pequeñas dan ratios de retención inestables
TREND_WINDOW = 18      # meses de tendencia para proyectar altas nuevas
TAIL_AGES = 6          # edades del final de la curva que fijan el hazard de estado estable

# Amortiguación de la tendencia de altas (damped trend, Gardner & McKenzie). El
# crecimiento del negocio se está desacelerando —el interanual pasa del 150% al
# 90%— así que extrapolar la pendiente recta sobrestima, y el error crece con el
# horizonte. Descomponer el error del modelo lo confirmó: con altas y pausas
# reales el MASE baja de 0,133 a 0,041, es decir, casi todo el error del modelo
# está en proyectar las altas, no en la curva de retención.
#
# 0,85 está dentro del rango 0,8-0,98 que recomienda la literatura y se fija a
# priori. El backtesting mejora de forma monótona hasta valores más agresivos,
# pero con cinco pliegues afinar más sería ajustar al ruido.
SIGNUP_DAMPING = 0.85


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
    anteriores). Sin ponderar, la cola de la curva es optimista y el forecast
    hereda un sesgo positivo. Con `None` se desactiva.
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


# =============================================================================
# 2. PAUSAS Y ALTAS
# =============================================================================

def pause_rate_by_month(
    facts: pd.DataFrame, cutoff: pd.Timestamp | None = None
) -> pd.Series:
    """
    Tasa media de pausa por mes natural (1-12), sobre los activos a cierre.

    Es el efecto de calendario del modelo. La forma se repite los tres años
    —agosto siempre el máximo, mayo y junio a cero— pero la intensidad varía, y
    ahí está el mayor error del modelo en verano.
    """
    frame = facts if cutoff is None else facts[facts["month_start"] <= cutoff]
    stats = frame.groupby("month_start").agg(
        eom=("is_active_eom", "sum"), paused=("is_paused", "sum"))
    rate = stats.paused / stats.eom
    return rate.groupby(rate.index.month).mean()


def project_signups(
    signups: pd.Series,
    horizon: int,
    trend_window: int = TREND_WINDOW,
    damping: float = SIGNUP_DAMPING,
) -> tuple[np.ndarray, pd.DatetimeIndex, pd.Series]:
    """
    Proyecta altas nuevas separando estacionalidad de tendencia.

    Los factores de mes se estiman sobre TODO el histórico disponible (ratio
    sobre media móvil centrada de 12 meses) y la tendencia log-lineal sólo sobre
    la ventana reciente. Estimar ambas cosas con la misma ventana corta hacía el
    modelo muy inestable: la ventana pasaba a decidir a la vez el nivel y la
    forma estacional, y el error del backtesting oscilaba 3x según el valor.

    `damping` (φ) amortigua la pendiente: en vez de sumar b en cada paso se suma
    b·(φ + φ² + … + φ^h), de modo que el crecimiento proyectado se aplana con el
    horizonte. Con φ=1 se recupera la tendencia recta. Ver SIGNUP_DAMPING.

    Devuelve (altas proyectadas, meses futuros, factores de mes).
    """
    if len(signups) < 12:
        raise ValueError(f"Hacen falta al menos 12 meses de altas; hay {len(signups)}.")

    series = signups.clip(lower=1)
    centered = series.rolling(12, center=True, min_periods=6).mean()
    ratio = (series / centered).dropna()
    month_factor = ratio.groupby(ratio.index.month).mean()
    month_factor = month_factor / month_factor.mean()

    deseasonalised = series / series.index.month.map(month_factor).to_numpy()
    recent = deseasonalised.tail(trend_window)
    x = np.arange(len(recent))
    slope, intercept = np.polyfit(x, np.log(recent.to_numpy()), 1)

    future = pd.date_range(series.index[-1] + pd.offsets.MonthBegin(1),
                           periods=horizon, freq="MS")
    last_level = intercept + slope * (len(recent) - 1)
    drift = np.array([slope * sum(damping ** j for j in range(1, i + 1))
                      for i in range(1, horizon + 1)])
    trend = np.exp(last_level + drift)
    factors = pd.Index(future.month).map(month_factor).to_numpy(dtype=float)
    return trend * np.nan_to_num(factors, nan=1.0), future, month_factor


# =============================================================================
# 3. FORECAST DE ACTIVOS
# =============================================================================

def forecast_active_subscribers(
    facts: pd.DataFrame,
    cutoff: pd.Timestamp,
    horizon: int,
    trend_window: int = TREND_WINDOW,
    min_cohort: int = MIN_COHORT_SIZE,
    recency_halflife: float | None = None,
    damping: float = SIGNUP_DAMPING,
    apply_pause: bool = True,
) -> np.ndarray:
    """
    Suscriptores activos netos de pausas, a `horizon` meses vista desde `cutoff`.

    Todo se reestima usando sólo filas con `month_start <= cutoff`: el modelo
    nunca ve nada posterior al origen, que es lo que hace válido el backtesting.

    Con `apply_pause=False` devuelve activos a cierre de mes (sin descontar
    pausas), que es lo que necesita el canal de suscripción del notebook 02: la
    suscripción pausada no factura ese mes, pero el ingreso reconocido reparte
    el cobro del ciclo, así que la base correcta ahí es otra.
    """
    history = facts[facts["month_start"] <= cutoff]
    curve = build_retention_curve(history, min_cohort=min_cohort,
                                  recency_halflife=recency_halflife)
    pause = pause_rate_by_month(history) if apply_pause else None

    signups = (history[history["months_since_start"] == 0]
               .groupby("cohort_month").size().asfreq("MS").fillna(0))
    projected_new, future, _ = project_signups(signups, horizon, trend_window, damping)

    alive = history[history["month_start"] == cutoff].groupby("cohort_month")["is_active_eom"].sum()
    ages = {c: (cutoff.year - c.year) * 12 + cutoff.month - c.month for c in alive.index}

    out = []
    for h, month in enumerate(future, start=1):
        # Cohortes ya existentes, envejecidas h meses.
        eom = sum(float(n) * curve.survival_ratio(ages[c], ages[c] + h)
                  for c, n in alive.items())
        # Altas futuras: la del mes j llega al mes h con edad h - j.
        eom += sum(projected_new[j - 1] * curve.at(h - j) for j in range(1, h + 1))
        if pause is not None:
            eom *= 1 - float(pause.get(month.month, 0.0))
        out.append(eom)
    return np.asarray(out, dtype=float)


def inner_bias_correction(
    facts: pd.DataFrame,
    actual: pd.Series,
    cutoff: pd.Timestamp,
    horizon: int,
    n_inner: int = 4,
    min_inner_train: int = 18,
    **forecast_kwargs: Any,
) -> np.ndarray:
    """
    Sesgo relativo por horizonte, estimado con un backtesting **interno** al train.

    Esto es lo que convierte la calibración de parche en parte del modelo. Antes el
    sesgo se corregía con los errores del mismo backtesting que luego se reportaba,
    lo cual es circular: el modelo evaluado no era el modelo calibrado. Aquí los
    pliegues internos usan sólo meses anteriores a `cutoff`, así que el modelo
    devuelto ya está calibrado y el backtesting externo lo mide honestamente.

    El sesgo existe porque el crecimiento del negocio se desacelera dentro de la
    ventana de evaluación y ningún modelo tendencial puede anticiparlo: no es un
    defecto corregible, es algo que hay que medir y descontar.

    **Compromiso conocido:** corregir reduce el sesgo siempre, pero a horizontes
    cortos cuesta precisión, porque ahí el sesgo es una fracción pequeña del error
    y la estimación interna añade varianza. A seis meses el MASE baja de 0,115 a
    0,087; a tres meses sube de 0,067 a 0,092 mientras el sesgo cae de 33 a 8.
    Conviene calibrar cuando importa acertar el nivel y no cuando importa el error
    punto a punto.
    """
    history = actual.loc[:cutoff]
    rows: list[dict[str, float]] = []
    for k in range(n_inner):
        position = -1 - horizon - k
        if len(history) + position < min_inner_train:
            continue
        inner_cutoff = history.index[position]
        try:
            predicted = forecast_active_subscribers(facts, inner_cutoff, horizon,
                                                    **forecast_kwargs)
        except (ValueError, KeyError):
            continue
        observed = history.loc[inner_cutoff:].iloc[1:horizon + 1]
        if len(observed) < horizon:
            continue
        for i in range(horizon):
            rows.append({"h": i + 1,
                         "rel": (predicted[i] - observed.iloc[i]) / observed.iloc[i]})

    if not rows:
        return np.zeros(horizon)
    errors = pd.DataFrame(rows).groupby("h")["rel"].mean()
    return errors.reindex(range(1, horizon + 1)).fillna(0.0).to_numpy()


def make_subscriber_forecaster(
    facts: pd.DataFrame, **kwargs: Any
) -> Callable[[pd.Series, int], np.ndarray]:
    """
    Envuelve el modelo como `forecast_fn(train, horizon)` para el backtesting.

    El origen del pliegue se toma de `train.index[-1]`, así que la función
    reestima con el histórico correcto en cada pliegue sin que el llamante tenga
    que pasárselo.
    """
    actual = kwargs.pop("actual", None)
    calibrate = kwargs.pop("calibrate", False)
    n_inner = kwargs.pop("n_inner", 4)
    if calibrate and actual is None:
        raise ValueError("Para calibrar hace falta `actual`: la serie observada de activos.")

    def _fn(train: pd.Series, horizon: int) -> np.ndarray:
        cutoff = train.index[-1]
        point = forecast_active_subscribers(facts, cutoff, horizon, **kwargs)
        if not calibrate:
            return point
        bias = inner_bias_correction(facts, actual, cutoff, horizon,
                                     n_inner=n_inner, **kwargs)
        return point / (1 + bias)

    suffix = "_recency" if kwargs.get("recency_halflife") else ""
    suffix += "_autocalibrado" if calibrate else ""
    _fn.__name__ = f"cohortes{suffix}"
    return _fn
