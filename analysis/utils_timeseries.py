"""
Capsule Club Analytics — utilidades compartidas de serie temporal.

Lógica común a las tres páginas de serie temporal del informe (suscriptores,
ingresos y demanda por sabor), para no reimplementarla en cada notebook:

  1. Preparación    — pasar un mart a una serie regular, sin huecos de calendario.
  2. Descomposición — STL y MSTL, con fuerza de tendencia y de estacionalidad.
  3. Estacionariedad — ADF, KPSS y sugerencia de orden de diferenciación.
  4. Backtesting    — walk-forward genérico sobre cualquier función de forecast.

Lo que este módulo NO hace, a propósito:

  - No limpia ni modela negocio: eso vive en dbt (ver CLAUDE.md). Aquí se asume
    que la entrada ya viene de un mart.
  - No implementa modelos de forecast. `walk_forward_backtest` recibe el modelo
    como función, así que Prophet, SARIMA o un modelo de cohortes entran por la
    misma puerta y se comparan con las mismas métricas.
  - No escribe ficheros. Cada resultado expone `to_dict()` con tipos nativos de
    Python, listo para `json.dump` en `analysis/outputs/`.

Convenio de frecuencias: se usan los alias de pandas ("D" diario, "W" semanal,
"MS" inicio de mes). El histórico del proyecto son 3 años (2023-09 a 2026-08),
así que la serie mensual tiene 36 puntos: suficiente para STL anual (necesita
2 periodos completos) pero justo para el backtesting, que ahí conviene lanzar
con horizontes cortos y `n_folds` explícito.
"""

from __future__ import annotations

import inspect
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import MSTL, STL
from statsmodels.tsa.stattools import adfuller, kpss

# statsmodels 0.15 avisa en cada llamada de que `adfuller` pasará a devolver un
# objeto en vez de una tupla. Se fija el comportamiento actual donde el
# argumento existe (y se omite en 0.14, que aún no lo tiene) para que los
# notebooks no se llenen de FutureWarning idénticos.
_ADFULLER_COMPAT: dict[str, Any] = (
    {"result_object": False}
    if "result_object" in inspect.signature(adfuller).parameters
    else {}
)

__all__ = [
    # preparación
    "build_series",
    "infer_season_length",
    "infer_seasonal_periods",
    "series_to_records",
    # descomposición
    "DecompositionResult",
    "stl_decompose",
    "mstl_decompose",
    # estacionariedad
    "TestResult",
    "StationarityReport",
    "adf_test",
    "kpss_test",
    "suggest_differencing",
    "stationarity_report",
    # backtesting
    "BacktestResult",
    "forecast_metrics",
    "seasonal_naive_forecast",
    "make_seasonal_naive",
    "walk_forward_backtest",
    "empirical_interval",
    "compare_backtests",
]


# =============================================================================
# 1. PREPARACIÓN DE SERIES
# =============================================================================

# Ciclo corto dominante de cada frecuencia. Para datos diarios el ciclo corto es
# la semana: el patrón anual se trata aparte (ver ANNUAL_PERIODS), porque STL
# sólo admite una estacionalidad a la vez.
SEASON_LENGTHS: dict[str, int] = {
    "h": 24, "H": 24,
    "D": 7,
    "B": 5,
    "W": 52,
    "MS": 12, "ME": 12, "M": 12,
    "QS": 4, "QE": 4, "Q": 4,
    "YS": 1, "YE": 1, "Y": 1, "A": 1,
}

# Longitud del ciclo anual en cada frecuencia. 365 (no 365.25) porque STL y MSTL
# exigen un periodo entero; el desfase de los bisiestos es despreciable en un
# histórico de 3 años.
ANNUAL_PERIODS: dict[str, int] = {
    "h": 8766, "H": 8766,
    "D": 365,
    "B": 261,
    "W": 52,
    "MS": 12, "ME": 12, "M": 12,
    "QS": 4, "QE": 4, "Q": 4,
}


def _base_freq(freq: str) -> str:
    """Normaliza un alias de pandas a su base: "2W-SUN" -> "W"."""
    base = str(freq).split("-", 1)[0]
    return base.lstrip("0123456789") or base


def _freq_of(series: pd.Series) -> str | None:
    """Frecuencia de la serie, tomada del índice o inferida de sus fechas."""
    freq = getattr(series.index, "freqstr", None) or getattr(series.index, "freq", None)
    if freq is None and len(series) >= 3:
        try:
            freq = pd.infer_freq(series.index)
        except (ValueError, TypeError):
            freq = None
    return str(freq) if freq is not None else None


def infer_season_length(source: str | pd.Series) -> int:
    """
    Longitud del ciclo estacional corto de una frecuencia o de una serie.

    Devuelve 1 (= sin estacionalidad) cuando la frecuencia no se reconoce, para
    que las métricas escaladas (MASE) degraden a naive en vez de romper.
    """
    freq = source if isinstance(source, str) else _freq_of(source)
    if freq is None:
        return 1
    return SEASON_LENGTHS.get(_base_freq(freq), 1)


def infer_seasonal_periods(source: str | pd.Series) -> tuple[int, ...]:
    """
    Periodos estacionales a modelar juntos con MSTL, de más corto a más largo.

    Para datos diarios devuelve (7, 365): la página 2 del informe pide enseñar
    estacionalidad semanal *y* anual, y STL sola no puede con las dos.
    """
    freq = source if isinstance(source, str) else _freq_of(source)
    if freq is None:
        return ()
    base = _base_freq(freq)
    periods = [p for p in (SEASON_LENGTHS.get(base), ANNUAL_PERIODS.get(base)) if p and p > 1]
    return tuple(sorted(set(periods)))


def build_series(
    frame: pd.DataFrame,
    date_col: str,
    value_col: str,
    freq: str = "MS",
    agg: str | Callable[..., Any] = "sum",
    fill_value: float | None = 0.0,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.Series:
    """
    Agrega un mart a una serie temporal regular y sin huecos de calendario.

    El reindexado sobre el calendario completo es deliberado: un día sin filas en
    `fct_shop_orders` no debe desaparecer de la serie, porque ese cero de demanda
    es justo la señal que hay que interpretar — rotura de stock frente a "nadie
    lo quiso comprar" (ver docs/data_imperfections.md). Con `fill_value=None` los
    huecos se quedan como NaN, que es lo correcto cuando el cero no es un valor
    legítimo: el hueco de la migración de pasarela en la serie de caja no es un
    mes sin ingresos, es un mes sin dato.

    `start`/`end` fuerzan el rango cuando la serie no debe empezar en su primera
    fila (sabores lanzados a mitad del histórico) o debe llegar hasta el cierre
    del histórico aunque el SKU esté ya descatalogado.
    """
    if date_col not in frame.columns:
        raise KeyError(f"No existe la columna de fecha {date_col!r} en el DataFrame.")
    if value_col not in frame.columns:
        raise KeyError(f"No existe la columna de valor {value_col!r} en el DataFrame.")

    dates = pd.to_datetime(frame[date_col])
    values = pd.to_numeric(frame[value_col], errors="coerce")
    tidy = pd.Series(np.asarray(values), index=pd.DatetimeIndex(dates), name=value_col)
    tidy = tidy[tidy.index.notna()].sort_index()

    series = tidy.resample(freq).agg(agg)

    lo = pd.Timestamp(start) if start is not None else None
    hi = pd.Timestamp(end) if end is not None else None
    if lo is not None or hi is not None:
        # Se reconstruye el calendario completo para respetar el rango pedido,
        # que puede ser más ancho que el de los datos observados.
        first = lo if lo is not None else (series.index[0] if len(series) else None)
        last = hi if hi is not None else (series.index[-1] if len(series) else None)
        if first is None or last is None:
            raise ValueError("Serie vacía: hay que indicar `start` y `end` explícitos.")
        series = series.reindex(pd.date_range(first, last, freq=freq))

    if fill_value is not None:
        series = series.fillna(fill_value)

    series.name = value_col
    series.index.name = date_col
    return series.asfreq(freq)


def series_to_records(series: pd.Series, value_key: str = "value") -> list[dict[str, Any]]:
    """Serie -> lista de {"date": "YYYY-MM-DD", value_key: float|None} para JSON."""
    return [
        {"date": ts.strftime("%Y-%m-%d"), value_key: _jsonable_number(v)}
        for ts, v in series.items()
    ]


def _jsonable_number(value: Any) -> float | None:
    """NaN/inf -> None (JSON no los admite); numpy -> float nativo."""
    if value is None:
        return None
    number = float(value)
    return None if not np.isfinite(number) else number


def _as_clean_series(series: pd.Series, what: str) -> pd.Series:
    """Valida que la entrada es una serie numérica con índice temporal ordenado."""
    if not isinstance(series, pd.Series):
        raise TypeError(f"{what} espera un pd.Series, no {type(series).__name__}.")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError(f"{what} espera un índice DatetimeIndex.")
    if not series.index.is_monotonic_increasing:
        series = series.sort_index()
    return series.astype(float)


# =============================================================================
# 2. DESCOMPOSICIÓN (STL / MSTL)
# =============================================================================

@dataclass
class DecompositionResult:
    """
    Resultado de una descomposición, con una o varias estacionalidades.

    `seasonal` va siempre indexado por periodo: {7: Series, 365: Series}. Así el
    notebook trata igual el caso STL (un periodo) y el MSTL (varios), y la
    plantilla del informe puede iterar sin saber cuál de los dos se usó.
    """

    method: str
    observed: pd.Series
    trend: pd.Series
    seasonal: dict[int, pd.Series]
    resid: pd.Series
    periods: tuple[int, ...]
    trend_strength: float
    seasonal_strength: dict[int, float]
    robust: bool = True

    @property
    def seasonal_total(self) -> pd.Series:
        """Suma de todas las componentes estacionales."""
        if not self.seasonal:
            return pd.Series(0.0, index=self.observed.index)
        return sum(self.seasonal.values())

    @property
    def seasonally_adjusted(self) -> pd.Series:
        """Serie desestacionalizada (observado - estacionalidad)."""
        return self.observed - self.seasonal_total

    def to_frame(self) -> pd.DataFrame:
        """Componentes en un DataFrame, para graficar de un tirón."""
        data = {"observed": self.observed, "trend": self.trend}
        for period, component in self.seasonal.items():
            data[f"seasonal_{period}"] = component
        data["resid"] = self.resid
        return pd.DataFrame(data)

    def to_dict(self) -> dict[str, Any]:
        """Estructura JSON-safe para analysis/outputs/*.json."""
        return {
            "method": self.method,
            "periods": list(self.periods),
            "robust": self.robust,
            "trend_strength": _jsonable_number(self.trend_strength),
            "seasonal_strength": {
                str(p): _jsonable_number(v) for p, v in self.seasonal_strength.items()
            },
            "dates": [ts.strftime("%Y-%m-%d") for ts in self.observed.index],
            "observed": [_jsonable_number(v) for v in self.observed],
            "trend": [_jsonable_number(v) for v in self.trend],
            "seasonal": {
                str(p): [_jsonable_number(v) for v in comp]
                for p, comp in self.seasonal.items()
            },
            "resid": [_jsonable_number(v) for v in self.resid],
        }


def _variance(values: pd.Series | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.var(arr, ddof=1)) if arr.size > 1 else 0.0


def _component_strength(component: pd.Series, resid: pd.Series) -> float:
    """
    Fuerza de una componente (Hyndman & Athanasopoulos, FPP3 §4.3):
    1 - Var(R) / Var(componente + R), acotada a [0, 1].

    Sirve para decidir con un número, y no a ojo, si merece la pena modelar la
    estacionalidad de un SKU o si lo que se ve en el gráfico es ruido.
    """
    denom = _variance(component + resid)
    if denom <= 0:
        return 0.0
    return float(np.clip(1.0 - _variance(resid) / denom, 0.0, 1.0))


def _require_no_nan(series: pd.Series, what: str) -> None:
    n_missing = int(series.isna().sum())
    if n_missing:
        raise ValueError(
            f"{what} no admite huecos: la serie tiene {n_missing} NaN. "
            "Rellénalos al construirla (`build_series(..., fill_value=...)`) o "
            "interpólalos explícitamente, dejando constancia de la decisión."
        )


def _check_length(series: pd.Series, period: int, what: str) -> None:
    if period < 2:
        raise ValueError(f"{what} necesita un periodo >= 2; recibido {period}.")
    if len(series) < 2 * period:
        raise ValueError(
            f"{what} necesita al menos 2 ciclos completos: {2 * period} "
            f"observaciones para period={period}, y la serie tiene {len(series)}. "
            "Baja la frecuencia de agregación o usa un periodo más corto."
        )


def stl_decompose(
    series: pd.Series,
    period: int | None = None,
    seasonal: int | None = None,
    robust: bool = True,
) -> DecompositionResult:
    """
    Descomposición STL en tendencia + estacionalidad + residuo.

    `period` se infiere de la frecuencia del índice si no se indica (12 para
    mensual, 7 para diario). `robust=True` por defecto a propósito: el histórico
    tiene picos de campaña y meses de dunning que, sin ponderación robusta, se
    reparten entre tendencia y estacionalidad y contaminan las dos.
    """
    series = _as_clean_series(series, "stl_decompose")
    _require_no_nan(series, "STL")

    if period is None:
        period = infer_season_length(series)
        if period < 2:
            raise ValueError(
                "No se pudo inferir el periodo estacional del índice. "
                "Pásalo explícito: stl_decompose(serie, period=12)."
            )
    _check_length(series, period, "STL")

    kwargs: dict[str, Any] = {"period": int(period), "robust": robust}
    if seasonal is not None:
        if seasonal < 7 or seasonal % 2 == 0:
            raise ValueError(f"`seasonal` debe ser impar y >= 7; recibido {seasonal}.")
        kwargs["seasonal"] = int(seasonal)

    fitted = STL(series, **kwargs).fit()
    trend = pd.Series(np.asarray(fitted.trend, dtype=float), index=series.index, name="trend")
    seas = pd.Series(
        np.asarray(fitted.seasonal, dtype=float), index=series.index, name=f"seasonal_{period}"
    )
    resid = pd.Series(np.asarray(fitted.resid, dtype=float), index=series.index, name="resid")

    return DecompositionResult(
        method="STL",
        observed=series,
        trend=trend,
        seasonal={int(period): seas},
        resid=resid,
        periods=(int(period),),
        trend_strength=_component_strength(trend, resid),
        seasonal_strength={int(period): _component_strength(seas, resid)},
        robust=robust,
    )


def mstl_decompose(
    series: pd.Series,
    periods: Sequence[int] | None = None,
    robust: bool = True,
    **stl_kwargs: Any,
) -> DecompositionResult:
    """
    Descomposición con varias estacionalidades a la vez (MSTL).

    Pensada para las series diarias, donde conviven el patrón semanal y el anual.
    Los periodos que no caben en el histórico (hacen falta 2 ciclos completos) se
    descartan con un aviso en vez de reventar: con 3 años de datos el ciclo anual
    entra justo, y en cuanto se recorta la ventana deja de entrar.
    """
    series = _as_clean_series(series, "mstl_decompose")
    _require_no_nan(series, "MSTL")

    if periods is None:
        periods = infer_seasonal_periods(series)
    requested = sorted({int(p) for p in periods if p and int(p) >= 2})
    if not requested:
        raise ValueError(
            "No hay periodos estacionales que modelar. Indícalos explícitos: "
            "mstl_decompose(serie, periods=(7, 365))."
        )

    too_long = [p for p in requested if len(series) < 2 * p]
    usable = [p for p in requested if p not in too_long]
    if too_long:
        warnings.warn(
            f"Periodos descartados por serie corta ({len(series)} obs.): {too_long}. "
            "Hacen falta 2 ciclos completos de cada periodo.",
            stacklevel=2,
        )
    if not usable:
        raise ValueError(
            f"La serie tiene {len(series)} observaciones: no admite ninguno de los "
            f"periodos pedidos {requested}."
        )

    if len(usable) == 1:
        # Con una sola estacionalidad, MSTL es STL con más indirección.
        return stl_decompose(series, period=usable[0], robust=robust, **stl_kwargs)

    fitted = MSTL(series, periods=usable, stl_kwargs={"robust": robust, **stl_kwargs}).fit()

    seasonal_frame = fitted.seasonal
    if isinstance(seasonal_frame, pd.Series):
        seasonal_frame = seasonal_frame.to_frame()
    seasonal = {
        int(period): pd.Series(
            np.asarray(seasonal_frame.iloc[:, i], dtype=float),
            index=series.index,
            name=f"seasonal_{period}",
        )
        for i, period in enumerate(usable)
    }
    trend = pd.Series(np.asarray(fitted.trend, dtype=float), index=series.index, name="trend")
    resid = pd.Series(np.asarray(fitted.resid, dtype=float), index=series.index, name="resid")

    return DecompositionResult(
        method="MSTL",
        observed=series,
        trend=trend,
        seasonal=seasonal,
        resid=resid,
        periods=tuple(usable),
        trend_strength=_component_strength(trend, resid),
        seasonal_strength={p: _component_strength(s, resid) for p, s in seasonal.items()},
        robust=robust,
    )


# =============================================================================
# 3. ESTACIONARIEDAD (ADF / KPSS)
# =============================================================================

@dataclass
class TestResult:
    """Resultado de un contraste de hipótesis sobre la serie."""

    test: str
    statistic: float
    p_value: float
    used_lags: int
    n_obs: int
    critical_values: dict[str, float]
    alpha: float
    stationary: bool
    null_hypothesis: str
    p_value_is_bound: bool = False   # KPSS tabula el p-valor sólo en [0.01, 0.10]
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "test": self.test,
            "statistic": _jsonable_number(self.statistic),
            "p_value": _jsonable_number(self.p_value),
            "p_value_is_bound": self.p_value_is_bound,
            "used_lags": self.used_lags,
            "n_obs": self.n_obs,
            "critical_values": {
                k: _jsonable_number(v) for k, v in self.critical_values.items()
            },
            "alpha": self.alpha,
            "stationary": self.stationary,
            "null_hypothesis": self.null_hypothesis,
            "note": self.note,
        }


@dataclass
class StationarityReport:
    """
    ADF + KPSS + orden de diferenciación sugerido.

    Los dos contrastes van juntos porque plantean hipótesis nulas opuestas: ADF
    asume raíz unitaria y KPSS asume estacionariedad. Que coincidan da una
    conclusión firme; que discrepen también es información (serie corta, o
    tendencia determinista frente a estocástica), y con 36 puntos mensuales pasa
    más de lo que parece.
    """

    adf: TestResult
    kpss: TestResult | None
    verdict: str
    n_diffs: int
    n_seasonal_diffs: int
    season_length: int
    n_obs: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "adf": self.adf.to_dict(),
            "kpss": self.kpss.to_dict() if self.kpss else None,
            "verdict": self.verdict,
            "n_diffs": self.n_diffs,
            "n_seasonal_diffs": self.n_seasonal_diffs,
            "season_length": self.season_length,
            "n_obs": self.n_obs,
        }

    def summary(self) -> str:
        """Texto corto para imprimir en el notebook."""
        if self.kpss is None:
            kpss_bit = "KPSS n/d"
        else:
            kpss_bit = f"KPSS p={self.kpss.p_value:.4f}" + (
                " (recortado)" if self.kpss.p_value_is_bound else ""
            )
        return (
            f"{self.verdict} | ADF p={self.adf.p_value:.4f} | {kpss_bit} | "
            f"d={self.n_diffs}, D={self.n_seasonal_diffs} (m={self.season_length})"
        )


def adf_test(
    series: pd.Series,
    alpha: float = 0.05,
    regression: Literal["c", "ct", "ctt", "n"] = "c",
    autolag: str | None = "AIC",
    maxlag: int | None = None,
) -> TestResult:
    """
    Augmented Dickey-Fuller. H0: hay raíz unitaria (la serie NO es estacionaria).

    p <= alpha -> se rechaza H0 -> estacionaria. Usar `regression="ct"` cuando lo
    que se quiere contrastar es estacionariedad *alrededor de una tendencia*, que
    es el caso de la serie de suscriptores: crece durante todo el histórico, y
    con "c" va a salir no estacionaria siempre.

    Cuidado con `autolag="AIC"` en series cortas: la regla por defecto de
    statsmodels propone hasta 10 retardos para 36 observaciones — casi un tercio
    de la muestra — y el contraste deja de ser fiable (llega a declarar
    estacionaria una serie con tendencia evidente). Con menos de ~60 puntos,
    pasar `maxlag` explícito (3-4) y `autolag=None`.
    """
    values = _as_clean_series(series, "adf_test").dropna()
    if len(values) < 8:
        raise ValueError(f"ADF necesita al menos 8 observaciones; hay {len(values)}.")

    # La tupla de `adfuller` tiene 6 elementos con autolag y 5 sin él (el último,
    # icbest, sólo existe si hubo selección de retardos). Se cortan los 5 primeros
    # para admitir las dos formas.
    stat, p_value, used_lags, n_obs, crit = adfuller(
        values.to_numpy(),
        maxlag=maxlag,
        regression=regression,
        autolag=autolag,
        **_ADFULLER_COMPAT,
    )[:5]
    return TestResult(
        test="ADF",
        statistic=float(stat),
        p_value=float(p_value),
        used_lags=int(used_lags),
        n_obs=int(n_obs),
        critical_values={k: float(v) for k, v in crit.items()},
        alpha=alpha,
        stationary=bool(p_value <= alpha),
        null_hypothesis="raíz unitaria (no estacionaria)",
        note=f"regression={regression}",
    )


def kpss_test(
    series: pd.Series,
    alpha: float = 0.05,
    regression: Literal["c", "ct"] = "c",
    nlags: str | int = "auto",
) -> TestResult:
    """
    KPSS. H0: la serie ES estacionaria (en nivel, o alrededor de tendencia).

    Complementa al ADF invirtiendo la hipótesis nula. statsmodels sólo tabula el
    p-valor entre 0.01 y 0.10: fuera de ese rango lo recorta y avisa, así que se
    marca con `p_value_is_bound` en vez de dejar pasar un 0.10 que en realidad
    quiere decir "0.10 o más".
    """
    values = _as_clean_series(series, "kpss_test").dropna()
    if len(values) < 8:
        raise ValueError(f"KPSS necesita al menos 8 observaciones; hay {len(values)}.")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        stat, p_value, used_lags, crit = kpss(
            values.to_numpy(), regression=regression, nlags=nlags
        )
    is_bound = any("p-value" in str(w.message).lower() for w in caught)

    return TestResult(
        test="KPSS",
        statistic=float(stat),
        p_value=float(p_value),
        used_lags=int(used_lags),
        n_obs=int(len(values)),
        critical_values={k: float(v) for k, v in crit.items()},
        alpha=alpha,
        stationary=bool(p_value > alpha),
        null_hypothesis="estacionaria",
        p_value_is_bound=is_bound,
        note=f"regression={regression}"
        + (" | p-valor recortado por tabla" if is_bound else ""),
    )


def suggest_differencing(
    series: pd.Series,
    season_length: int | None = None,
    alpha: float = 0.05,
    max_diff: int = 2,
    max_seasonal_diff: int = 1,
    seasonal_strength_threshold: float = 0.64,
    maxlag: int | None = None,
) -> tuple[int, int]:
    """
    Sugiere (d, D): órdenes de diferenciación regular y estacional.

    D se decide por fuerza de la estacionalidad (umbral 0.64 de
    Wang-Smith-Hyndman, el mismo criterio que usa `nsdiffs` en R), y d aplicando
    ADF iterativamente sobre la serie ya diferenciada estacionalmente. Es una
    *sugerencia* para arrancar el SARIMA, no un veredicto: el notebook debería
    mirar además la ACF/PACF antes de fijar el orden.

    En series cortas conviene pasar `maxlag` (ver la nota de `adf_test`).
    """
    values = _as_clean_series(series, "suggest_differencing").dropna()
    m = int(season_length if season_length is not None else infer_season_length(series))

    n_seasonal_diffs = 0
    working = values
    if m >= 2 and max_seasonal_diff > 0 and len(values) >= 2 * m:
        try:
            strength = stl_decompose(values, period=m).seasonal_strength[m]
        except ValueError:
            strength = 0.0
        if strength > seasonal_strength_threshold:
            n_seasonal_diffs = 1
            working = values.diff(m).dropna()

    n_diffs = 0
    while n_diffs < max_diff and len(working) >= 8:
        try:
            if adf_test(working, alpha=alpha, maxlag=maxlag).stationary:
                break
        except ValueError:
            break
        working = working.diff().dropna()
        n_diffs += 1

    return n_diffs, n_seasonal_diffs


def stationarity_report(
    series: pd.Series,
    season_length: int | None = None,
    alpha: float = 0.05,
    regression: Literal["c", "ct"] = "c",
    with_kpss: bool = True,
    max_diff: int = 2,
    maxlag: int | None = None,
) -> StationarityReport:
    """
    Diagnóstico completo de estacionariedad de una serie.

    Es la función que llaman los tres notebooks: un único sitio donde se fija
    alpha y se redacta el veredicto, para que las tres páginas del informe digan
    lo mismo con las mismas palabras.

    `maxlag` se propaga al ADF; en series cortas hay que fijarlo (ver `adf_test`).
    """
    values = _as_clean_series(series, "stationarity_report").dropna()
    m = int(season_length if season_length is not None else infer_season_length(series))

    adf = adf_test(values, alpha=alpha, regression=regression, maxlag=maxlag)
    kp = kpss_test(values, alpha=alpha, regression=regression) if with_kpss else None

    if kp is None:
        verdict = "estacionaria" if adf.stationary else "no estacionaria"
    elif adf.stationary and kp.stationary:
        verdict = "estacionaria (ADF y KPSS coinciden)"
    elif not adf.stationary and not kp.stationary:
        verdict = "no estacionaria (ADF y KPSS coinciden)"
    elif adf.stationary and not kp.stationary:
        verdict = "discrepancia: ADF rechaza la raíz unitaria pero KPSS rechaza la estacionariedad"
    else:
        verdict = "discrepancia: ADF no rechaza la raíz unitaria pero KPSS no rechaza la estacionariedad"

    n_diffs, n_seasonal_diffs = suggest_differencing(
        values, season_length=m, alpha=alpha, max_diff=max_diff, maxlag=maxlag
    )
    return StationarityReport(
        adf=adf,
        kpss=kp,
        verdict=verdict,
        n_diffs=n_diffs,
        n_seasonal_diffs=n_seasonal_diffs,
        season_length=m,
        n_obs=int(len(values)),
    )


# =============================================================================
# 4. BACKTESTING WALK-FORWARD
# =============================================================================

# Alias aceptados en la salida de un forecast_fn que devuelva DataFrame o dict.
# Cubren de fábrica Prophet (yhat / yhat_lower / yhat_upper) y statsmodels
# (mean / mean_ci_lower / mean_ci_upper) sin tener que envolverlos.
_YHAT_KEYS = ("yhat", "forecast", "mean", "prediction", "y_pred", "value")
_LOWER_KEYS = ("yhat_lower", "lower", "lower_ci", "mean_ci_lower", "y_lower")
_UPPER_KEYS = ("yhat_upper", "upper", "upper_ci", "mean_ci_upper", "y_upper")


def seasonal_naive_forecast(
    train: pd.Series, horizon: int, season_length: int | None = None
) -> np.ndarray:
    """
    Baseline: repetir el último ciclo estacional observado.

    Es el suelo que cualquier modelo tiene que superar para justificar su
    complejidad, y el denominador del MASE. Con `season_length=1` degrada al
    naive puro (repetir el último valor).
    """
    values = _as_clean_series(train, "seasonal_naive_forecast").dropna().to_numpy()
    if values.size == 0:
        raise ValueError("No se puede pronosticar desde un train vacío.")

    m = int(season_length if season_length is not None else infer_season_length(train))
    if m < 1 or values.size < m:
        m = 1
    last_cycle = values[-m:]
    return np.asarray([last_cycle[i % m] for i in range(horizon)], dtype=float)


def make_seasonal_naive(
    season_length: int | None = None,
) -> Callable[[pd.Series, int], np.ndarray]:
    """Devuelve un `forecast_fn` de naive estacional listo para el backtesting."""

    def _fn(train: pd.Series, horizon: int) -> np.ndarray:
        return seasonal_naive_forecast(train, horizon, season_length=season_length)

    _fn.__name__ = f"seasonal_naive_m{season_length if season_length else 'auto'}"
    return _fn


def forecast_metrics(
    y_true: Sequence[float] | pd.Series,
    y_pred: Sequence[float] | pd.Series,
    y_train: Sequence[float] | pd.Series | None = None,
    season_length: int = 1,
    y_lower: Sequence[float] | pd.Series | None = None,
    y_upper: Sequence[float] | pd.Series | None = None,
) -> dict[str, Any]:
    """
    Métricas de error de un forecast frente a lo observado.

    - MAE / RMSE: en unidades de la serie; comparables sólo dentro de una misma
      serie, no entre suscriptores y euros.
    - MAPE: excluye los ceros reales, que en demanda por SKU son frecuentes.
      `mape_n_excluded` dice cuántos puntos se quedaron fuera, porque un MAPE
      calculado sobre la mitad de los puntos no significa lo mismo.
    - sMAPE: alternativa acotada cuando hay ceros.
    - MASE: error relativo al naive estacional sobre el *train*. < 1 significa
      que el modelo bate al baseline; es la única comparable entre series.
    - bias: error medio con signo. Un modelo puede tener buen MAE y estar
      sistemáticamente por encima, que en previsión de demanda no es lo mismo.
    - coverage: % de observaciones dentro del intervalo, si se aportó.
    """
    true = np.asarray(y_true, dtype=float)
    pred = np.asarray(y_pred, dtype=float)
    if true.shape != pred.shape:
        raise ValueError(f"y_true {true.shape} y y_pred {pred.shape} no casan.")

    valid = np.isfinite(true) & np.isfinite(pred)
    true, pred = true[valid], pred[valid]
    if true.size == 0:
        raise ValueError("No queda ningún par (real, predicho) válido para evaluar.")

    error = pred - true
    abs_error = np.abs(error)

    nonzero = true != 0
    mape = (
        float(np.mean(np.abs(error[nonzero] / true[nonzero])) * 100)
        if nonzero.any()
        else float("nan")
    )

    denom = np.abs(true) + np.abs(pred)
    smape_terms = np.divide(2.0 * abs_error, denom, out=np.zeros_like(denom), where=denom != 0)

    mase = float("nan")
    if y_train is not None:
        train = np.asarray(pd.Series(y_train).dropna(), dtype=float)
        m = max(1, int(season_length))
        if train.size > m:
            scale = float(np.mean(np.abs(train[m:] - train[:-m])))
            if scale > 0:
                mase = float(np.mean(abs_error) / scale)

    metrics: dict[str, Any] = {
        "n": int(true.size),
        "mae": float(np.mean(abs_error)),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "mape": mape,
        "mape_n_excluded": int((~nonzero).sum()),
        "smape": float(np.mean(smape_terms) * 100),
        "mase": mase,
        "bias": float(np.mean(error)),
    }

    if y_lower is not None and y_upper is not None:
        lower = np.asarray(y_lower, dtype=float)[valid]
        upper = np.asarray(y_upper, dtype=float)[valid]
        inside = np.isfinite(lower) & np.isfinite(upper)
        if inside.any():
            covered = (true[inside] >= lower[inside]) & (true[inside] <= upper[inside])
            metrics["coverage"] = float(np.mean(covered) * 100)
            metrics["mean_interval_width"] = float(np.mean(upper[inside] - lower[inside]))

    return metrics


@dataclass
class BacktestResult:
    """
    Resultado de un backtesting walk-forward.

    `predictions` es el detalle completo (una fila por origen y horizonte), y de
    ahí salen las tres vistas que pide el informe: el error global, cómo se
    degrada con el horizonte, y si hay pliegues concretos que se rompen — por
    ejemplo los que caen sobre la campaña de Navidad.
    """

    model_name: str
    predictions: pd.DataFrame
    metrics: dict[str, Any]
    metrics_by_horizon: pd.DataFrame
    metrics_by_fold: pd.DataFrame
    horizon: int
    step: int
    window: str
    season_length: int
    n_folds: int
    failed_folds: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_predictions: bool = True) -> dict[str, Any]:
        """Estructura JSON-safe para analysis/outputs/*.json."""
        payload: dict[str, Any] = {
            "model": self.model_name,
            "horizon": self.horizon,
            "step": self.step,
            "window": self.window,
            "season_length": self.season_length,
            "n_folds": self.n_folds,
            "metrics": {
                k: (_jsonable_number(v) if isinstance(v, float) else v)
                for k, v in self.metrics.items()
            },
            "metrics_by_horizon": _frame_to_records(self.metrics_by_horizon),
            "failed_folds": self.failed_folds,
        }
        if include_predictions:
            payload["predictions"] = _frame_to_records(self.predictions)
        return payload


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> records con fechas ISO y NaN convertidos a None."""
    out: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, pd.Timestamp):
                clean[key] = value.strftime("%Y-%m-%d")
            elif isinstance(value, (np.integer, int)) and not isinstance(value, bool):
                clean[key] = int(value)
            elif isinstance(value, (np.floating, float)):
                clean[key] = _jsonable_number(value)
            else:
                clean[key] = value
        out.append(clean)
    return out


def _normalize_forecast_output(
    output: Any, horizon: int, model_name: str
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """
    Acepta lo que devuelva el modelo y lo reduce a (yhat, lower, upper).

    Se admiten array, Series, DataFrame, dict y tupla (yhat, lower, upper), para
    que Prophet, statsmodels y un modelo de cohortes escrito a mano entren en el
    backtesting sin un adaptador distinto en cada notebook.
    """
    lower: Any = None
    upper: Any = None

    def _pick(container: Any, keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in container:
                return container[key]
        return None

    if isinstance(output, pd.DataFrame):
        yhat = _pick(output, _YHAT_KEYS)
        if yhat is None:
            if output.shape[1] != 1:
                raise ValueError(
                    f"{model_name}: el DataFrame devuelto no tiene ninguna columna de "
                    f"predicción reconocible {_YHAT_KEYS} y tiene {output.shape[1]} columnas."
                )
            yhat = output.iloc[:, 0]
        lower, upper = _pick(output, _LOWER_KEYS), _pick(output, _UPPER_KEYS)
    elif isinstance(output, Mapping):
        yhat = _pick(output, _YHAT_KEYS)
        if yhat is None:
            raise ValueError(
                f"{model_name}: el dict devuelto no trae ninguna clave de "
                f"predicción reconocible {_YHAT_KEYS}."
            )
        lower, upper = _pick(output, _LOWER_KEYS), _pick(output, _UPPER_KEYS)
    elif (
        isinstance(output, tuple)
        and 2 <= len(output) <= 3
        and all(hasattr(part, "__len__") for part in output)
    ):
        yhat = output[0]
        lower = output[1]
        upper = output[2] if len(output) > 2 else None
    else:
        yhat = output

    def _to_array(part: Any) -> np.ndarray:
        if isinstance(part, (pd.Series, pd.Index)):
            part = part.to_numpy()
        return np.asarray(part, dtype=float).ravel()

    yhat_arr = _to_array(yhat)
    if yhat_arr.size != horizon:
        raise ValueError(
            f"{model_name}: devolvió {yhat_arr.size} valores y se esperaban {horizon}. "
            "`forecast_fn(train, horizon)` debe devolver exactamente `horizon` puntos."
        )

    def _bound(part: Any) -> np.ndarray | None:
        if part is None:
            return None
        arr = _to_array(part)
        return arr if arr.size == horizon else None

    return yhat_arr, _bound(lower), _bound(upper)


def walk_forward_backtest(
    series: pd.Series,
    forecast_fn: Callable[..., Any],
    horizon: int = 3,
    initial_train_size: int | None = None,
    n_folds: int | None = None,
    step: int | None = None,
    window: Literal["expanding", "rolling"] = "expanding",
    season_length: int | None = None,
    model_name: str | None = None,
    on_error: Literal["raise", "skip"] = "raise",
    **forecast_kwargs: Any,
) -> BacktestResult:
    """
    Backtesting walk-forward (origen rodante) sobre cualquier modelo.

    `forecast_fn(train, horizon, **kwargs)` recibe el histórico disponible hasta
    el origen del pliegue y devuelve `horizon` valores, opcionalmente con
    intervalos (ver `_normalize_forecast_output`). Nunca ve datos posteriores al
    origen, que es justo el punto: evaluar el modelo como se va a usar en
    producción, y no sobre datos que ya conocía.

    Parámetros de ventana:
      - `window="expanding"`: el train crece en cada pliegue (por defecto).
      - `window="rolling"`: el train mantiene el tamaño fijo `initial_train_size`,
        útil si se sospecha que el pasado lejano ya no describe el negocio.

    Tamaño del train: o bien `initial_train_size`, o bien `n_folds` (se calcula
    hacia atrás para que salgan exactamente esos pliegues). Si no se indica
    ninguno se reserva el 60% inicial. Con la serie mensual (36 puntos) eso deja
    pocos pliegues: ahí mejor fijar `n_folds` y un horizonte corto.

    Sólo se evalúan pliegues con el horizonte completo, para que el error por
    horizonte se compare siempre sobre el mismo número de pliegues.

    `on_error="skip"` registra el fallo en `failed_folds` y sigue, en vez de
    abortar: Prophet y SARIMA pueden no converger en los primeros pliegues, que
    son los de train más corto.
    """
    series = _as_clean_series(series, "walk_forward_backtest")
    n = len(series)
    if horizon < 1:
        raise ValueError(f"`horizon` debe ser >= 1; recibido {horizon}.")
    if initial_train_size is not None and n_folds is not None:
        raise ValueError("Indica `initial_train_size` o `n_folds`, no los dos.")

    m = int(season_length if season_length is not None else infer_season_length(series))
    step = int(step) if step is not None else horizon
    if step < 1:
        raise ValueError(f"`step` debe ser >= 1; recibido {step}.")

    if n_folds is not None:
        if n_folds < 1:
            raise ValueError(f"`n_folds` debe ser >= 1; recibido {n_folds}.")
        initial_train_size = n - horizon - (n_folds - 1) * step
        if initial_train_size < 2:
            raise ValueError(
                f"No caben {n_folds} pliegues de horizonte {horizon} y paso {step} en "
                f"{n} observaciones: el train inicial saldría de {initial_train_size}."
            )
    elif initial_train_size is None:
        initial_train_size = max(min(2 * m, n - horizon), int(round(0.6 * n)))

    initial_train_size = int(initial_train_size)
    if initial_train_size < 2:
        raise ValueError(
            f"`initial_train_size` debe ser >= 2; recibido {initial_train_size}."
        )
    if initial_train_size + horizon > n:
        raise ValueError(
            f"Serie demasiado corta: train inicial {initial_train_size} + horizonte "
            f"{horizon} > {n} observaciones."
        )

    origins = list(range(initial_train_size, n - horizon + 1, step))
    if not origins:
        raise ValueError("La combinación de train inicial, horizonte y paso no deja pliegues.")

    name = model_name or getattr(forecast_fn, "__name__", "forecast_fn")
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for fold, cut in enumerate(origins, start=1):
        start = cut - initial_train_size if window == "rolling" else 0
        train = series.iloc[start:cut]
        actual = series.iloc[cut:cut + horizon]

        try:
            output = forecast_fn(train, horizon, **forecast_kwargs)
            yhat, lower, upper = _normalize_forecast_output(output, horizon, name)
        except Exception as exc:  # noqa: BLE001 — se re-lanza salvo on_error="skip"
            if on_error == "raise":
                raise
            failed.append({
                "fold": fold,
                "origin": train.index[-1].strftime("%Y-%m-%d"),
                "train_size": int(len(train)),
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        # Escala del MASE: se calcula sobre el train de ESTE pliegue, nunca sobre
        # la serie completa, que incluiría el futuro que el modelo no vio.
        train_values = train.dropna().to_numpy()
        scale = (
            float(np.mean(np.abs(train_values[m:] - train_values[:-m])))
            if train_values.size > m
            else float("nan")
        )

        for h in range(horizon):
            rows.append({
                "fold": fold,
                "origin": train.index[-1],
                "train_size": int(len(train)),
                "ds": actual.index[h],
                "h": h + 1,
                "y_true": float(actual.iloc[h]),
                "y_pred": float(yhat[h]),
                "y_lower": float(lower[h]) if lower is not None else np.nan,
                "y_upper": float(upper[h]) if upper is not None else np.nan,
                "naive_scale": scale,
            })

    if not rows:
        raise RuntimeError(f"{name}: ningún pliegue se pudo evaluar. Fallos: {failed}")

    predictions = pd.DataFrame(rows)
    predictions["error"] = predictions["y_pred"] - predictions["y_true"]
    predictions["abs_error"] = predictions["error"].abs()
    predictions["scaled_abs_error"] = predictions["abs_error"] / predictions["naive_scale"]

    has_intervals = bool(
        predictions["y_lower"].notna().any() and predictions["y_upper"].notna().any()
    )
    interval_args = (
        {"y_lower": predictions["y_lower"], "y_upper": predictions["y_upper"]}
        if has_intervals
        else {}
    )

    metrics = forecast_metrics(predictions["y_true"], predictions["y_pred"], **interval_args)
    # El MASE global se promedia sobre los errores ya escalados pliegue a pliegue,
    # en vez de recalcular una escala única: cada origen tiene su propio histórico.
    metrics["mase"] = float(predictions["scaled_abs_error"].mean(skipna=True))
    metrics["n_folds"] = int(predictions["fold"].nunique())

    return BacktestResult(
        model_name=name,
        predictions=predictions,
        metrics=metrics,
        metrics_by_horizon=_metrics_by(predictions, "h", has_intervals),
        metrics_by_fold=_metrics_by(predictions, "fold", has_intervals),
        horizon=horizon,
        step=step,
        window=window,
        season_length=m,
        n_folds=int(predictions["fold"].nunique()),
        failed_folds=failed,
    )


def _metrics_by(predictions: pd.DataFrame, key: str, has_intervals: bool) -> pd.DataFrame:
    """Agrega las métricas del detalle por horizonte o por pliegue."""
    rows = []
    for value, chunk in predictions.groupby(key, sort=True):
        interval_args = (
            {"y_lower": chunk["y_lower"], "y_upper": chunk["y_upper"]}
            if has_intervals
            else {}
        )
        metrics = forecast_metrics(chunk["y_true"], chunk["y_pred"], **interval_args)
        metrics["mase"] = float(chunk["scaled_abs_error"].mean(skipna=True))
        rows.append({key: int(value), **metrics})
    return pd.DataFrame(rows)


def empirical_interval(
    predictions: pd.DataFrame, level: float = 0.80
) -> pd.DataFrame:
    """
    Intervalo de previsión empírico, a partir de los errores del backtesting.

    Un modelo estructural como éste no produce intervalos propios, así que la
    única fuente honesta de incertidumbre son sus errores fuera de muestra.

    El problema es que con cinco pliegues hay **cinco errores por horizonte**, y
    una desviación típica estimada sobre cinco puntos es casi ruido: en la serie
    de suscriptores salía no monótona con el horizonte, que es justo lo que no
    puede ser. Y no se puede ampliar el número de pliegues, porque bajar de 26
    meses de entrenamiento deja al modelo sin dos ciclos anuales completos.

    La solución es agrupar la información de todos los horizontes en vez de
    tratarlos por separado: se ajusta sd(h) = a·√h sobre los 30 puntos, que es
    la forma que toma el error acumulado de un proceso con incrementos
    aproximadamente independientes. El resultado es monótono por construcción y
    usa seis veces más información en cada horizonte.

    El sesgo medio sí se estima por horizonte, porque ahí sí es sistemático y
    monótono (crece del +0,1% al +8%), no ruido.

    Devuelve un DataFrame indexado por horizonte con el sesgo medio, la
    desviación suavizada y los factores multiplicativos del intervalo.
    """
    from scipy.stats import norm

    frame = predictions.copy()
    frame["rel_error"] = (frame["y_pred"] - frame["y_true"]) / frame["y_true"]

    by_h = frame.groupby("h")["rel_error"]
    bias = by_h.mean()
    raw_sd = by_h.std(ddof=1)
    n_folds = by_h.size()

    # Ajuste de sd(h) = a·sqrt(h) por mínimos cuadrados sin término independiente,
    # sobre los residuos ya descontado el sesgo de su horizonte.
    centred = frame["rel_error"] - frame["h"].map(bias)
    h_values = frame["h"].to_numpy(dtype=float)
    # E[e²] = a²·h  ->  a² = mean(e²/h)
    a_squared = float(np.mean(centred.to_numpy() ** 2 / h_values))
    smooth_sd = pd.Series(np.sqrt(a_squared * bias.index.to_numpy(dtype=float)),
                          index=bias.index, name="sd")

    z = float(norm.ppf(0.5 + level / 2))
    return pd.DataFrame({
        "mean_rel_error": bias,
        "sd_raw": raw_sd,
        "sd_smoothed": smooth_sd,
        "n_folds": n_folds,
        # El punto se corrige por el sesgo y el intervalo se centra en el valor ya
        # corregido, para que no quede un intervalo que excluye su propia estimación.
        "calibration_factor": 1.0 / (1.0 + bias),
        "lower_factor": (1.0 / (1.0 + bias)) * (1 - z * smooth_sd),
        "upper_factor": (1.0 / (1.0 + bias)) * (1 + z * smooth_sd),
    })


def compare_backtests(
    results: Mapping[str, BacktestResult] | Sequence[BacktestResult],
    sort_by: str = "mase",
) -> pd.DataFrame:
    """
    Tabla comparativa de varios backtests, ordenada por la métrica elegida.

    Es la tabla de "modelo clásico vs. modelo de cohortes" que piden las páginas
    2, 3 y 4 del informe. Se ordena por MASE por defecto porque es la única
    métrica que dice si el modelo aporta algo sobre el naive estacional.
    """
    items = (
        results.items()
        if isinstance(results, Mapping)
        else [(r.model_name, r) for r in results]
    )
    rows = []
    for label, result in items:
        rows.append({
            "model": label,
            "horizon": result.horizon,
            "window": result.window,
            "n_folds": result.n_folds,
            **{k: v for k, v in result.metrics.items() if k != "n_folds"},
            "failed_folds": len(result.failed_folds),
        })
    frame = pd.DataFrame(rows)
    if sort_by in frame.columns:
        frame = frame.sort_values(sort_by, na_position="last").reset_index(drop=True)
    return frame
