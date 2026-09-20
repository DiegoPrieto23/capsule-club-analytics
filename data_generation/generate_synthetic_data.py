"""
Capsule Club Analytics — generador de datos sintéticos.

Genera el dataset completo descrito en docs/data_schema.md e inyecta TODAS las
imperfecciones catalogadas en docs/data_imperfections.md. El dataset es
reproducible: toda la aleatoriedad cuelga de SEED.

Salidas:
  - data/raw/<tabla>.parquet                (una por tabla del esquema)
  - data/warehouse.duckdb                   (mismas tablas como raw_<tabla>)
  - data/raw/_imperfections_manifest.json   (ground truth para QA; NO se carga en
    DuckDB a propósito: el análisis debe *detectar* las imperfecciones, no leerlas)

Uso:
    python data_generation/generate_synthetic_data.py
"""

from __future__ import annotations

import json
import random
import sys
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from faker import Faker

# =============================================================================
# PARÁMETROS DE GENERACIÓN
# =============================================================================

SEED = 20240215

# Rango del histórico: 3 años completos de meses naturales.
START_DATE = date(2023, 9, 1)
END_DATE = date(2026, 8, 31)

# Volumen del negocio simulado
N_CUSTOMERS = 12_000           # altas "reales" (antes de duplicados de identidad)
N_STORES = 8                   # boutiques físicas
N_FLAVORS = 12                 # sabores de cápsula distintos
N_MERCH_PRODUCTS = 8
N_MACHINE_MODELS = 5

# Propensiones de negocio
P_CUSTOMER_SUBSCRIBES = 0.42           # % de clientes que llega a suscribirse
P_CUSTOMER_BUYS_MACHINE = 0.26         # % de clientes que compra una máquina
P_STORE_SIGNUP = 0.16                  # altas originadas en boutique física
BASE_MONTHLY_CHURN = 0.030             # hazard base de cancelación mensual
SHOP_ORDERS_PER_CUSTOMER_YEAR = 1.9    # intensidad de compra puntual

# --- Parámetros de las imperfecciones (docs/data_imperfections.md) ------------

# Identidad de cliente
P_DUPLICATE_IDENTITY = 0.04            # altas que reaparecen con email variante
P_NULL_ACQUISITION_CHANNEL = 0.12      # touchpoint de origen no atribuible

# Cohortes
P_WELCOME_DISCOUNT = 0.55              # suscripciones con descuento de bienvenida
WELCOME_DISCOUNT_CHURN_SPIKE = 0.19    # churn extra al acabar el descuento (mes 2)
P_GIFTED_SUBSCRIPTION = 0.06
GIFT_TERM_MONTHS = (3, 6)              # duración típica del regalo
P_GIFT_RENEWED = 0.28                  # regalos que el titular real sí renueva
P_MACHINE_BUNDLED_TRIAL = 0.35         # máquinas con cápsulas de regalo
P_TRIAL_TO_SUBSCRIPTION = 0.30         # de esas, cuántas acaban en suscripción
TRIAL_CONVERSION_LAG_DAYS = (14, 75)   # semanas después, nunca el mismo día
P_PLAN_DOWNGRADE_MONTHLY = 0.012
P_PLAN_UPGRADE_MONTHLY = 0.009

# Series temporales / forecasting
P_SUMMER_PAUSE = 0.14                  # pausa estacional en julio/agosto
P_XMAS_PAUSE = 0.07                    # pausa en torno a Navidad
P_PAUSE_RESUME_MONTHLY = 0.62          # probabilidad de volver tras una pausa
P_PAYMENT_FAILURE = 0.035              # fallo de cobro (dunning)
P_DUNNING_RECOVERED = 0.78             # fallos que se recuperan al reintentar
GATEWAY_MIGRATION_START = date(2025, 3, 10)   # hueco de pagos por migración
GATEWAY_MIGRATION_DAYS = 7
N_SKU_RELAUNCHES = 3                   # sabores descatalogados y relanzados
N_STOCKOUT_WINDOWS = 6                 # roturas de stock -> demanda censurada
STOCKOUT_LENGTH_DAYS = (9, 26)
MIN_STOCKOUT_CENSORED_LINES = 20       # una rotura sin demanda censurada no deja rastro
STOCKOUT_PLACEMENT_ATTEMPTS = 60

# Atribución de marketing
P_TOUCHPOINT_UNRESOLVED = 0.22         # touchpoints que no resuelven a customer_id
N_ORPHAN_TOUCHPOINTS = 9_000           # tráfico anónimo puro (direct_unknown)
P_STORE_ORDER_NO_LOYALTY = 0.38        # compra en tienda sin cliente identificado
ATT_WINDOW_START = date(2025, 1, 15)   # "iOS ATT": caída de atribución paid_social
ATT_WINDOW_END = date(2025, 6, 30)
ATT_SUPPRESSION_RATE = 0.62            # % de paid_social que pierde la conversión
SHARED_INFLUENCER_CODE = "CREMA20"     # mismo código, dos creadores a la vez
SHARED_CODE_CREATORS = ("LAURAK", "CAFECONJUAN")
SHARED_CODE_WINDOW = (date(2024, 9, 1), date(2025, 2, 28))
P_SHARED_CODE_IN_WINDOW = 0.35   # uso del código compartido dentro de su ventana

# Rutas
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DUCKDB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"

# =============================================================================
# ESTADO ALEATORIO Y CONTADORES
# =============================================================================

rng = np.random.default_rng(SEED)
pyrand = random.Random(SEED)
fake = Faker("es_ES")
Faker.seed(SEED)

# Contador de imperfecciones efectivamente inyectadas, para el resumen final.
IMP: dict[str, int] = {}


def bump(key: str, n: int = 1) -> None:
    IMP[key] = IMP.get(key, 0) + n


# =============================================================================
# HELPERS DE FECHA Y ESTACIONALIDAD
# =============================================================================

ALL_DAYS = list(pd.date_range(START_DATE, END_DATE, freq="D").date)
N_DAYS = len(ALL_DAYS)

# Estacionalidad del consumo de café: pico en otoño/invierno, valle en verano.
MONTH_FACTOR = {
    1: 1.08, 2: 1.02, 3: 1.00, 4: 0.95, 5: 0.90, 6: 0.78,
    7: 0.62, 8: 0.58, 9: 1.00, 10: 1.15, 11: 1.22, 12: 1.18,
}
WEEKDAY_FACTOR = {0: 1.10, 1: 1.08, 2: 1.06, 3: 1.05, 4: 0.98, 5: 0.80, 6: 0.68}


def add_months(d: date, n: int) -> date:
    """Suma n meses conservando el día cuando el mes destino lo permite."""
    total = (d.year * 12 + d.month - 1) + n
    y, m = divmod(total, 12)
    m += 1
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    last_day = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last_day))


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def rand_date(start: date, end: date) -> date:
    span = (end - start).days
    if span <= 0:
        return start
    return start + timedelta(days=int(rng.integers(0, span + 1)))


def clamp(d: date, low: date = START_DATE, high: date = END_DATE) -> date:
    return max(low, min(d, high))


def event_day(base: date, jitter: int = 27) -> date | None:
    """Día de un evento dentro del histórico, o None si cae fuera de la ventana.

    Deliberadamente NO usa clamp(). Aplastar contra END_DATE apilaba sobre el
    último día todos los eventos programados para después del corte: 1.025
    envíos el 2026-08-31 frente a una media de 75/día, y lo mismo en pagos,
    cancelaciones y altas duplicadas. Un evento que ocurre fuera de la ventana
    de observación sencillamente no se observa, así que se descarta en lugar de
    recolocarse.

    El sorteo se consume siempre, emita o no, para que corregir la cola no
    altere el resto del dataset.
    """
    day = base + timedelta(days=int(rng.integers(0, jitter)))
    return None if day > END_DATE else max(START_DATE, day)


# Perfil horario del tráfico: valle de madrugada, picos a media mañana y por
# la noche. La columna se llama `timestamp` en el esquema, así que debe llevar
# hora de verdad; generándolo todo a medianoche, el orden de los touchpoints
# dentro de un mismo día quedaba indefinido y el "último toque" era arbitrario.
HOUR_WEIGHTS = np.array([
    0.4, 0.2, 0.2, 0.2, 0.3, 0.6, 1.2, 2.2, 3.4, 4.2, 4.0, 3.6,
    3.4, 3.2, 3.0, 3.1, 3.4, 4.0, 4.6, 5.2, 5.6, 5.0, 3.2, 1.6,
])
HOUR_PROBS = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()


def random_time_on(d: date) -> datetime:
    """Convierte un día en un instante concreto dentro de ese día."""
    return datetime(
        d.year, d.month, d.day,
        int(rng.choice(24, p=HOUR_PROBS)),
        int(rng.integers(0, 60)),
        int(rng.integers(0, 60)),
    )


def has_value(v) -> bool:
    """True si v no es None/NaN (pandas convierte los None de object a NaN)."""
    return v is not None and not (isinstance(v, float) and np.isnan(v))


def trend_factor(d: date) -> float:
    """Crecimiento del negocio a lo largo del histórico."""
    t = (d - START_DATE).days / max(N_DAYS - 1, 1)
    return 0.45 + 1.35 * t


DAY_WEIGHTS = np.array([
    trend_factor(d) * MONTH_FACTOR[d.month] * WEEKDAY_FACTOR[d.weekday()]
    for d in ALL_DAYS
])
DAY_PROBS = DAY_WEIGHTS / DAY_WEIGHTS.sum()


def sample_days(n: int) -> list[date]:
    """Muestrea n fechas del histórico siguiendo tendencia + estacionalidad."""
    idx = rng.choice(N_DAYS, size=n, p=DAY_PROBS)
    return [ALL_DAYS[i] for i in idx]


# =============================================================================
# 1. STORES
# =============================================================================

CITIES = ["Madrid", "Barcelona", "Valencia", "Sevilla", "Bilbao",
          "Málaga", "Zaragoza", "Palma", "Valladolid", "A Coruña"]


def gen_stores() -> pd.DataFrame:
    rows = []
    for i in range(N_STORES):
        # Las primeras ya existían; el resto abre dentro del histórico, así la
        # serie de ingresos de tienda arranca escalonada y no plana.
        if i < max(3, N_STORES // 2):
            opening = START_DATE - timedelta(days=int(rng.integers(200, 1200)))
        else:
            opening = rand_date(START_DATE + timedelta(days=60),
                                END_DATE - timedelta(days=200))
        rows.append({
            "store_id": f"ST{i + 1:03d}",
            "city": CITIES[i % len(CITIES)],
            "opening_date": opening,
        })
    return pd.DataFrame(rows)


# =============================================================================
# 2. PRODUCTS  (incluye SKUs descatalogados y relanzados)
# =============================================================================

# El orden importa: N_FLAVORS corta esta lista por el principio, así que los
# primeros elementos tienen que cubrir todas las familias — incluidas las
# seasonal, que son las únicas que se lanzan DENTRO del histórico y las únicas
# con estacionalidad propia de sabor. Con las seasonal al final, N_FLAVORS=12
# las dejaba fuera y la serie de demanda por SKU salía plana.
FLAVOR_POOL = [
    "origin_colombia", "origin_ethiopia", "origin_brazil",
    "intense_8", "intense_10", "intense_12",
    "classic_espresso", "classic_lungo",
    "decaf_vanilla", "decaf_classic",
    "seasonal_pumpkin", "seasonal_gingerbread",
    # A partir de aquí sólo entran si se sube N_FLAVORS.
    "origin_sumatra", "classic_ristretto", "seasonal_horchata",
]

# Estacionalidad propia del sabor, como multiplicador de su demanda ese mes.
# Un sabor de temporada no se vende igual en julio que en diciembre; sin esto,
# la página de demanda por SKU no tiene estacionalidad que descomponer.
FLAVOR_SEASON_PEAKS = {
    "seasonal_pumpkin":     {9: 2.8, 10: 3.6, 11: 2.4, 12: 1.2},
    "seasonal_gingerbread": {11: 2.6, 12: 4.0, 1: 1.6},
    "seasonal_horchata":    {6: 2.4, 7: 3.2, 8: 3.0, 9: 1.4},
}
OFF_SEASON_FACTOR = 0.25      # fuera de temporada casi no rota
FAVORITE_FLAVOR_WEIGHT = 8.0  # cuánto pesa el sabor favorito frente al resto


def flavor_season_factor(flavor: str, d: date) -> float:
    peaks = FLAVOR_SEASON_PEAKS.get(flavor)
    if peaks is None:
        return 1.0
    return peaks.get(d.month, OFF_SEASON_FACTOR)

MERCH_NAMES = ["mug_classic", "mug_double", "capsule_holder", "tote_bag",
               "travel_cup", "cleaning_kit", "gift_box", "milk_frother"]

TIER_FLAVOR_PREFIX = {
    "classic": ("classic_", "origin_"),
    "intense": ("intense_", "origin_"),
    "decaf": ("decaf_",),
    "explorer": ("origin_", "seasonal_", "intense_", "classic_"),
}


@dataclass
class FlavorTimeline:
    """Un sabor puede materializarse en más de un SKU a lo largo del tiempo."""
    flavor: str
    versions: list = field(default_factory=list)  # (sku, launch, discontinue|None)

    def sku_on(self, d: date) -> str | None:
        for sku, launch, disc in self.versions:
            if d >= launch and (disc is None or d <= disc):
                return sku
        return None

    @property
    def relaunched(self) -> bool:
        return len(self.versions) > 1


def gen_products() -> tuple[pd.DataFrame, dict[str, FlavorTimeline],
                           dict[str, float], dict[str, float]]:
    flavors = FLAVOR_POOL[:N_FLAVORS]
    timelines: dict[str, FlavorTimeline] = {}
    prices: dict[str, float] = {}
    rows = []

    # Sabores que sufren relanzamiento: rompen la continuidad de la serie de
    # demanda si el análisis no resuelve replaced_by_sku.
    relaunch_flavors = set(rng.choice(flavors, size=N_SKU_RELAUNCHES, replace=False))

    for flavor in flavors:
        if flavor.startswith("seasonal_"):
            launch = rand_date(START_DATE + timedelta(days=90),
                               START_DATE + timedelta(days=500))
        else:
            launch = START_DATE - timedelta(days=int(rng.integers(300, 1500)))

        sku_v1 = f"CAP-{flavor.upper().replace('_', '-')}-V1"
        price_v1 = round(float(rng.uniform(4.40, 6.20)), 2)
        tl = FlavorTimeline(flavor=flavor)

        if flavor in relaunch_flavors:
            disc = rand_date(START_DATE + timedelta(days=270),
                             END_DATE - timedelta(days=200))
            sku_v2 = f"CAP-{flavor.upper().replace('_', '-')}-V2"
            price_v2 = round(price_v1 * float(rng.uniform(1.06, 1.18)), 2)
            tl.versions = [(sku_v1, launch, disc),
                           (sku_v2, disc + timedelta(days=1), None)]
            rows.append({"product_sku": sku_v1, "product_type": "capsule",
                         "flavor": flavor, "launch_date": launch,
                         "discontinue_date": disc, "replaced_by_sku": sku_v2,
                         "unit_price": price_v1})
            rows.append({"product_sku": sku_v2, "product_type": "capsule",
                         "flavor": flavor, "launch_date": disc + timedelta(days=1),
                         "discontinue_date": None, "replaced_by_sku": None,
                         "unit_price": price_v2})
            prices[sku_v1] = price_v1
            prices[sku_v2] = price_v2
            bump("ts_sku_relaunched_flavors")
        else:
            tl.versions = [(sku_v1, launch, None)]
            rows.append({"product_sku": sku_v1, "product_type": "capsule",
                         "flavor": flavor, "launch_date": launch,
                         "discontinue_date": None, "replaced_by_sku": None,
                         "unit_price": price_v1})
            prices[sku_v1] = price_v1

        timelines[flavor] = tl

    for j, name in enumerate(MERCH_NAMES[:N_MERCH_PRODUCTS]):
        sku = f"MER-{j + 1:03d}"
        price = round(float(rng.uniform(8.90, 44.90)), 2)
        rows.append({"product_sku": sku, "product_type": "merch", "flavor": None,
                     "launch_date": START_DATE - timedelta(days=int(rng.integers(100, 900))),
                     "discontinue_date": None, "replaced_by_sku": None,
                     "unit_price": price})
        prices[sku] = price

    # Popularidad relativa de cada sabor, única para todo el negocio: un sabor
    # que se vende poco en tienda tampoco debería ser el favorito de medio club.
    # Antes vivía sólo dentro de gen_shop_orders y los envíos repartían por
    # igual, así que los sabores de una misma gama salían empatados.
    weights = rng.dirichlet(np.ones(len(flavors)) * 2.2)
    popularity = {f: float(w) for f, w in zip(flavors, weights)}

    return pd.DataFrame(rows), timelines, prices, popularity


# =============================================================================
# 3. MACHINES
# =============================================================================

MACHINE_NAMES = ["Aroma Mini", "Aroma Plus", "Aroma Pro",
                 "Aroma Lattissima", "Aroma Compact", "Aroma Studio"]


def gen_machines() -> pd.DataFrame:
    rows = []
    for i in range(N_MACHINE_MODELS):
        if i < 3:
            launch = START_DATE - timedelta(days=int(rng.integers(200, 1100)))
        else:
            launch = rand_date(START_DATE + timedelta(days=30),
                               END_DATE - timedelta(days=300))
        # El modelo más antiguo se descataloga dentro del histórico.
        disc = (rand_date(START_DATE + timedelta(days=400), END_DATE - timedelta(days=120))
                if i == 0 else None)
        rows.append({
            "machine_model_id": f"MCH{i + 1:03d}",
            "name": MACHINE_NAMES[i % len(MACHINE_NAMES)],
            "launch_date": launch,
            "discontinue_date": disc,
            "price": round(float(rng.uniform(79, 329)), 2),
        })
    return pd.DataFrame(rows)


# =============================================================================
# 4. CUSTOMERS  (+ duplicados de identidad por variantes de email)
# =============================================================================

ACQ_CHANNELS = ["paid_social", "organic", "influencer_code", "referral",
                "podcast_ads", "direct_unknown"]
ACQ_WEIGHTS = np.array([0.26, 0.24, 0.15, 0.13, 0.11, 0.11])
ACQ_WEIGHTS = ACQ_WEIGHTS / ACQ_WEIGHTS.sum()

EMAIL_DOMAINS = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.es", "icloud.com"]

_ACCENTS = str.maketrans("áéíóúàèìòùñçäëïöü", "aeiouaeiouncaeiou")


def _email_for(first: str, last: str, i: int) -> str:
    dom = EMAIL_DOMAINS[int(rng.integers(0, len(EMAIL_DOMAINS)))]
    style = int(rng.integers(0, 3))
    base = {0: f"{first}.{last}", 1: f"{first}{last}", 2: f"{first[:1]}{last}{i % 97}"}[style]
    base = base.lower().replace(" ", "").translate(_ACCENTS)
    return f"{base}@{dom}"


def _email_variant(email: str) -> str:
    """Variante del MISMO email real: mayúsculas, alias '+', dominio o puntos."""
    local, domain = email.split("@")
    mode = int(rng.integers(0, 4))
    if mode == 0:                                   # capitalización inconsistente
        return f"{local.capitalize()}@{domain.upper()}"
    if mode == 1:                                   # alias con '+'
        tag = pyrand.choice(["club", "capsulas", "newsletter", "compras"])
        return f"{local}+{tag}@{domain}"
    if mode == 2:                                   # dominio alternativo del mismo proveedor
        alt = {"gmail.com": "googlemail.com", "hotmail.com": "outlook.com",
               "outlook.com": "hotmail.com", "yahoo.es": "yahoo.com",
               "icloud.com": "me.com"}.get(domain, "gmail.com")
        return f"{local}@{alt}"
    if len(local) > 4:                              # puntos extra en el local part
        cut = len(local) // 2
        return f"{local[:cut]}.{local[cut:]}@{domain}"
    return f"{local}.x@{domain}"


def gen_customers(stores: pd.DataFrame) -> pd.DataFrame:
    signup_days = sample_days(N_CUSTOMERS)
    store_ids = stores["store_id"].tolist()
    store_open = dict(zip(stores["store_id"], stores["opening_date"]))

    rows = []
    for i in range(N_CUSTOMERS):
        signup = signup_days[i]
        email = _email_for(fake.first_name(), fake.last_name(), i)

        home_store = None
        is_store_signup = rng.random() < P_STORE_SIGNUP
        if is_store_signup:
            open_stores = [s for s in store_ids if store_open[s] <= signup]
            if open_stores:
                home_store = open_stores[int(rng.integers(0, len(open_stores)))]
            else:
                is_store_signup = False

        # Imperfección: canal de adquisición no atribuible -> NULL
        if rng.random() < P_NULL_ACQUISITION_CHANNEL:
            channel = None
            bump("att_customers_null_acquisition_channel")
        elif is_store_signup and rng.random() < 0.55:
            channel = "direct_unknown"
        else:
            channel = str(rng.choice(ACQ_CHANNELS, p=ACQ_WEIGHTS))

        rows.append({
            "customer_id": f"C{i + 1:06d}",
            "signup_date": signup,
            "acquisition_channel": channel,
            "home_store_id": home_store,
            "email_raw": email,
        })

    # --- Imperfección: identidad duplicada por variantes de email -------------
    # El mismo humano se da de alta otra vez más tarde con un email variante y
    # recibe un customer_id nuevo. dbt tendrá que resolverlo antes de cohortes.
    n_dup = int(N_CUSTOMERS * P_DUPLICATE_IDENTITY)
    dup_sources = rng.choice(N_CUSTOMERS, size=n_dup, replace=False)
    next_id = N_CUSTOMERS
    for src_idx in dup_sources:
        src = rows[int(src_idx)]
        new_signup = src["signup_date"] + timedelta(days=int(rng.integers(21, 500)))
        next_id += 1
        # La fila se construye siempre (consume los mismos sorteos) pero sólo se
        # registra si el alta duplicada cae dentro del histórico.
        duplicate_row = {
            "customer_id": f"C{next_id:06d}",
            "signup_date": new_signup,
            "acquisition_channel": (None if rng.random() < 0.25
                                    else str(rng.choice(ACQ_CHANNELS, p=ACQ_WEIGHTS))),
            "home_store_id": src["home_store_id"] if rng.random() < 0.40 else None,
            "email_raw": _email_variant(src["email_raw"]),
        }
        if new_signup <= END_DATE:
            rows.append(duplicate_row)
            bump("identity_duplicate_customers")

    return pd.DataFrame(rows).sort_values("signup_date").reset_index(drop=True)


# =============================================================================
# 5. MACHINE ORDERS
# =============================================================================

def gen_machine_orders(customers: pd.DataFrame, machines: pd.DataFrame,
                       stores: pd.DataFrame) -> pd.DataFrame:
    store_ids = stores["store_id"].tolist()
    store_open = dict(zip(stores["store_id"], stores["opening_date"]))
    machine_rows = machines.to_dict("records")

    def available_machines(d: date) -> list[dict]:
        return [m for m in machine_rows
                if m["launch_date"] <= d
                and (m["discontinue_date"] is None or m["discontinue_date"] >= d)]

    def open_stores(d: date) -> list[str]:
        return [s for s in store_ids if store_open[s] <= d]

    rows = []
    counter = 0

    def emit(customer_id, order_date, channel):
        nonlocal counter
        avail = available_machines(order_date)
        if not avail:
            return None
        m = avail[int(rng.integers(0, len(avail)))]
        store_id = None
        if channel == "store":
            opened = open_stores(order_date)
            if not opened:
                return None
            store_id = opened[int(rng.integers(0, len(opened)))]
        # Descuentos puntuales de campaña sobre el precio de catálogo.
        price_paid = round(m["price"] * float(rng.choice([1.0, 1.0, 1.0, 0.9, 0.8, 0.7])), 2)
        bundled = bool(rng.random() < P_MACHINE_BUNDLED_TRIAL)
        counter += 1
        rows.append({
            "order_id": f"MO{counter:07d}",
            "customer_id": customer_id,
            "machine_model_id": m["machine_model_id"],
            "order_date": order_date,
            "channel": channel,
            "store_id": store_id,
            "price_paid": price_paid,
            "bundled_capsules_trial": bundled,
        })
        return rows[-1]

    # 5a. Compras ligadas a un cliente identificado
    for cust in customers.itertuples(index=False):
        if rng.random() >= P_CUSTOMER_BUYS_MACHINE:
            continue
        # La máquina suele ser la puerta de entrada: el mismo día del alta o poco después.
        lag = 0 if rng.random() < 0.45 else int(rng.integers(1, 400))
        order_date = cust.signup_date + timedelta(days=lag)
        if order_date > END_DATE:
            continue
        channel = "store" if (has_value(cust.home_store_id) and rng.random() < 0.6) \
            else ("store" if rng.random() < 0.25 else "online")
        emit(cust.customer_id, order_date, channel)

    # 5b. Imperfección: compra en boutique sin fidelización -> customer_id NULL
    n_walkin = int(len(rows) * 0.22)
    for d in sample_days(n_walkin):
        if emit(None, d, "store") is not None:
            bump("att_machine_orders_without_customer")

    df = pd.DataFrame(rows).sort_values("order_date").reset_index(drop=True)
    bump("cohort_machine_bundled_trials", int(df["bundled_capsules_trial"].sum()))
    return df


# =============================================================================
# 6. SUBSCRIPTIONS + CICLO DE VIDA (eventos, pagos, envíos)
# =============================================================================

PLANS = ["monthly", "quarterly", "annual"]
PLAN_WEIGHTS = np.array([0.62, 0.25, 0.13])
PLAN_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
PLAN_DISCOUNT = {"monthly": 1.00, "quarterly": 0.95, "annual": 0.88}

TIERS = ["classic", "intense", "decaf", "explorer"]
TIER_WEIGHTS = np.array([0.35, 0.30, 0.13, 0.22])
TIER_MONTHLY_PRICE = {"classic": 26.90, "intense": 31.90, "decaf": 24.90, "explorer": 38.90}

CANCEL_REASONS = ["price", "taste", "moved", "no_reason"]
CANCEL_REASON_WEIGHTS = np.array([0.38, 0.22, 0.14, 0.26])


def _tier_flavors(tier: str, timelines: dict[str, FlavorTimeline]) -> list[str]:
    """Sabores compatibles con la gama contratada, sin mirar fechas."""
    return [f for f in timelines if f.startswith(TIER_FLAVOR_PREFIX[tier])]


def _pick_favorite_flavor(tier: str, timelines: dict[str, FlavorTimeline],
                          popularity: dict[str, float]) -> str | None:
    """Sabor favorito, fijado al alta y estable durante toda la suscripción."""
    candidates = _tier_flavors(tier, timelines) or list(timelines)
    if not candidates:
        return None
    w = np.array([popularity[f] for f in candidates])
    return candidates[int(rng.choice(len(candidates), p=w / w.sum()))]


def _pick_shipment_flavor(tier: str, favorite: str | None,
                          timelines: dict[str, FlavorTimeline], d: date) -> str | None:
    """
    Sabor de un envío concreto.

    Un suscriptor real no sortea sabor cada mes: repite el suyo y prueba otros
    de vez en cuando. Elegir uniformemente dejaba la demanda de cada sabor
    dentro de una gama en el mismo nivel exacto, sin nada que modelar por SKU.
    """
    candidates = [f for f in _tier_flavors(tier, timelines)
                  if timelines[f].sku_on(d) is not None]
    if not candidates:
        candidates = [f for f in timelines if timelines[f].sku_on(d) is not None]
    if not candidates:
        return None
    weights = np.array([
        flavor_season_factor(f, d) * (FAVORITE_FLAVOR_WEIGHT if f == favorite else 1.0)
        for f in candidates
    ])
    return candidates[int(rng.choice(len(candidates), p=weights / weights.sum()))]


def gen_subscriptions(customers: pd.DataFrame,
                      machine_orders: pd.DataFrame) -> pd.DataFrame:
    """Suscripciones base + conversiones diferidas de compradores de máquina."""
    rows = []
    counter = 0
    subscriber_ids: set[str] = set()

    def emit(customer_id: str, start_date: date, source: str) -> None:
        nonlocal counter
        counter += 1
        plan = str(rng.choice(PLANS, p=PLAN_WEIGHTS))
        tier = str(rng.choice(TIERS, p=TIER_WEIGHTS))
        gifted = bool(rng.random() < P_GIFTED_SUBSCRIPTION)
        # Un regalo no lleva descuento de bienvenida: lo paga un tercero.
        welcome = (False if gifted else bool(rng.random() < P_WELCOME_DISCOUNT))
        rows.append({
            "subscription_id": f"SUB{counter:07d}",
            "customer_id": customer_id,
            "plan": plan,
            "tier": tier,
            "start_date": start_date,
            "status": "active",          # se recalcula en la simulación
            "cancel_date": None,
            "cancel_reason": None,
            "had_welcome_discount": welcome,
            "gifted": gifted,
            "_source": source,           # columna interna, no se persiste
        })
        subscriber_ids.add(customer_id)
        if welcome:
            bump("cohort_welcome_discount_subs")
        if gifted:
            bump("cohort_gifted_subscriptions")

    # 6a. Altas de suscripción "normales"
    for cust in customers.itertuples(index=False):
        if rng.random() >= P_CUSTOMER_SUBSCRIBES:
            continue
        lag = int(rng.integers(0, 120)) if rng.random() < 0.55 else 0
        start = cust.signup_date + timedelta(days=lag)
        if start > END_DATE:
            continue
        emit(cust.customer_id, start, "organic_signup")

    # 6b. Imperfección (cohortes): comprador de máquina con cápsulas de regalo que
    #     se suscribe SEMANAS después. Un join ingenuo por fecha exacta lo pierde.
    trials = machine_orders[
        machine_orders["bundled_capsules_trial"] & machine_orders["customer_id"].notna()
    ]
    for mo in trials.itertuples(index=False):
        if mo.customer_id in subscriber_ids:
            continue
        if rng.random() >= P_TRIAL_TO_SUBSCRIPTION:
            continue
        lag = int(rng.integers(*TRIAL_CONVERSION_LAG_DAYS))
        start = mo.order_date + timedelta(days=lag)
        if start > END_DATE:
            continue
        emit(mo.customer_id, start, "machine_trial_conversion")
        bump("cohort_machine_trial_conversions")

    return pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)


def simulate_lifecycle(subscriptions: pd.DataFrame,
                       timelines: dict[str, FlavorTimeline],
                       prices: dict[str, float],
                       popularity: dict[str, float]):
    """Simula mes a mes cada suscripción y emite eventos, pagos y envíos."""
    events, payments, shipments = [], [], []
    ev_n = pay_n = shp_n = 0

    # Se mutan sobre el DataFrame al final
    final_status: list[str] = []
    final_cancel_date: list[date | None] = []
    final_cancel_reason: list[str | None] = []
    final_plan: list[str] = []

    for sub in subscriptions.itertuples(index=False):
        plan = sub.plan
        tier = sub.tier
        start = sub.start_date
        gift_term = int(rng.integers(*GIFT_TERM_MONTHS)) if sub.gifted else None
        favorite_flavor = _pick_favorite_flavor(tier, timelines, popularity)

        ev_n += 1
        events.append({"event_id": f"EV{ev_n:08d}", "subscription_id": sub.subscription_id,
                       "event_type": "created", "event_date": start,
                       "previous_plan": None, "new_plan": plan})

        state = "active"
        cancel_date = None
        cancel_reason = None
        months_elapsed = 0
        paused_months = 0
        cursor = start

        while cursor <= END_DATE and state != "cancelled":
            k = months_elapsed                       # 0 = mes de alta
            in_summer = cursor.month in (7, 8)
            in_xmas = cursor.month == 12
            # Marca de agua del mes: ninguna baja puede fecharse antes del
            # último hecho que le ocurrió a la suscripción (cobro, envío,
            # cambio de plan). Sin esto salían envíos y pagos posteriores a
            # la fecha de cancelación.
            last_activity_day = cursor

            # --- Reanudación tras pausa estacional ---------------------------
            if state == "paused":
                paused_months += 1
                if rng.random() < P_PAUSE_RESUME_MONTHLY or paused_months >= 4:
                    resume_day = event_day(cursor)
                    if resume_day is not None:
                        state = "active"
                        paused_months = 0
                        ev_n += 1
                        events.append({"event_id": f"EV{ev_n:08d}",
                                       "subscription_id": sub.subscription_id,
                                       "event_type": "resumed", "event_date": resume_day,
                                       "previous_plan": None, "new_plan": None})
                        bump("ts_seasonal_resume_events")
                cursor = add_months(cursor, 1)
                months_elapsed += 1
                continue

            # --- Imperfección (TS): pausas estacionales masivas ---------------
            # No son churn, pero rompen la continuidad de "activos" si se cuentan igual.
            pause_p = P_SUMMER_PAUSE if in_summer else (P_XMAS_PAUSE if in_xmas else 0.0)
            if k > 0 and pause_p and rng.random() < pause_p:
                pause_day = event_day(cursor)
                if pause_day is not None:
                    state = "paused"
                    ev_n += 1
                    events.append({"event_id": f"EV{ev_n:08d}",
                                   "subscription_id": sub.subscription_id,
                                   "event_type": "paused", "event_date": pause_day,
                                   "previous_plan": None, "new_plan": None})
                    bump("ts_seasonal_pause_events")
                cursor = add_months(cursor, 1)
                months_elapsed += 1
                continue

            # --- Cambios de plan (downgrade = menos ingreso, pero NO es churn) -
            if k > 0 and rng.random() < P_PLAN_DOWNGRADE_MONTHLY:
                idx = PLANS.index(plan)
                if idx > 0:
                    new_plan = PLANS[idx - 1]
                    change_day = event_day(cursor)
                    if change_day is not None:
                        last_activity_day = max(last_activity_day, change_day)
                        ev_n += 1
                        events.append({"event_id": f"EV{ev_n:08d}",
                                       "subscription_id": sub.subscription_id,
                                       "event_type": "downgraded",
                                       "event_date": change_day,
                                       "previous_plan": plan, "new_plan": new_plan})
                        plan = new_plan
                        bump("cohort_plan_downgrades")
            elif k > 0 and rng.random() < P_PLAN_UPGRADE_MONTHLY:
                idx = PLANS.index(plan)
                if idx < len(PLANS) - 1:
                    new_plan = PLANS[idx + 1]
                    change_day = event_day(cursor)
                    if change_day is not None:
                        last_activity_day = max(last_activity_day, change_day)
                        ev_n += 1
                        events.append({"event_id": f"EV{ev_n:08d}",
                                       "subscription_id": sub.subscription_id,
                                       "event_type": "upgraded",
                                       "event_date": change_day,
                                       "previous_plan": plan, "new_plan": new_plan})
                        plan = new_plan
                        bump("cohort_plan_upgrades")

            # --- Facturación de este mes -------------------------------------
            months_per_cycle = PLAN_MONTHS[plan]
            is_billing_month = (k % months_per_cycle == 0)
            payment_failed_this_month = False

            if is_billing_month:
                amount = TIER_MONTHLY_PRICE[tier] * months_per_cycle * PLAN_DISCOUNT[plan]
                if k == 0 and sub.had_welcome_discount:
                    amount *= 0.5            # descuento de bienvenida del primer ciclo
                amount = round(amount, 2)
                # pay_raw se conserva sin recortar porque de él se derivan las
                # fechas de reintento y de baja; pay_date es None cuando el cobro
                # cae fuera del histórico, y entonces no se registra nada.
                pay_raw = cursor + timedelta(days=int(rng.integers(0, 27)))
                pay_date = pay_raw if pay_raw <= END_DATE else None
                if pay_date is not None:
                    last_activity_day = max(last_activity_day, pay_date)

                # Imperfección (TS): fallo de cobro -> dunning. El suscriptor
                # "desaparece" temporalmente sin que haya churn real.
                if rng.random() < P_PAYMENT_FAILURE:
                    payment_failed_this_month = True
                    if pay_date is not None:
                        ev_n += 1
                        events.append({"event_id": f"EV{ev_n:08d}",
                                       "subscription_id": sub.subscription_id,
                                       "event_type": "payment_failed", "event_date": pay_date,
                                       "previous_plan": None, "new_plan": None})
                        bump("ts_dunning_payment_failures")

                    if rng.random() < P_DUNNING_RECOVERED:
                        retry_raw = pay_raw + timedelta(days=int(rng.integers(2, 12)))
                        retry_date = retry_raw if retry_raw <= END_DATE else None
                        if retry_date is not None:
                            last_activity_day = max(last_activity_day, retry_date)
                            pay_n += 1
                            payments.append({"payment_id": f"PAY{pay_n:08d}",
                                             "subscription_id": sub.subscription_id,
                                             "payment_date": retry_date, "amount": amount,
                                             "status": "retried_success"})
                            ev_n += 1
                            events.append({"event_id": f"EV{ev_n:08d}",
                                           "subscription_id": sub.subscription_id,
                                           "event_type": "payment_retried_ok",
                                           "event_date": retry_date,
                                           "previous_plan": None, "new_plan": None})
                            bump("ts_dunning_recovered")
                    else:
                        if pay_date is not None:
                            pay_n += 1
                            payments.append({"payment_id": f"PAY{pay_n:08d}",
                                             "subscription_id": sub.subscription_id,
                                             "payment_date": pay_date, "amount": amount,
                                             "status": "failed"})
                        # Churn involuntario. Si la baja cae fuera de la ventana,
                        # dentro del histórico la suscripción sigue viva.
                        cancel_raw = max(
                            last_activity_day,
                            pay_raw + timedelta(days=int(rng.integers(3, 20))))
                        if cancel_raw <= END_DATE:
                            state = "cancelled"
                            cancel_date = cancel_raw
                            cancel_reason = "involuntary_payment_failure"
                            ev_n += 1
                            events.append({"event_id": f"EV{ev_n:08d}",
                                           "subscription_id": sub.subscription_id,
                                           "event_type": "cancelled", "event_date": cancel_date,
                                           "previous_plan": plan, "new_plan": None})
                            bump("ts_dunning_involuntary_churn")
                        break
                else:
                    if pay_date is not None:
                        pay_n += 1
                        payments.append({"payment_id": f"PAY{pay_n:08d}",
                                         "subscription_id": sub.subscription_id,
                                         "payment_date": pay_date, "amount": amount,
                                         "status": "success"})

            # --- Envío mensual de cápsulas al suscriptor activo ---------------
            if not payment_failed_this_month:
                ship_raw = cursor + timedelta(days=int(rng.integers(0, 27)))
                ship_date = ship_raw if ship_raw <= END_DATE else None
                # El sabor y el SKU se resuelven sobre el día recortado, igual que
                # antes, para no alterar los sorteos; lo que cambia es que el envío
                # sólo se registra si su fecha cae dentro del histórico.
                lookup_day = ship_date if ship_date is not None else END_DATE
                flavor = _pick_shipment_flavor(tier, favorite_flavor, timelines, lookup_day)
                if flavor is not None:
                    sku = timelines[flavor].sku_on(lookup_day)
                    qty = int(rng.integers(1, 5))
                    on_time = bool(rng.random() > (0.16 if in_xmas else 0.06))
                    if ship_date is not None:
                        last_activity_day = max(last_activity_day, ship_date)
                        shp_n += 1
                        shipments.append({
                            "shipment_id": f"SHP{shp_n:08d}",
                            "subscription_id": sub.subscription_id,
                            "ship_date": ship_date,
                            "capsule_sku": sku,
                            "quantity": qty,
                            "cost": round(qty * prices[sku], 2),
                            # Los retrasos empeoran en campaña de Navidad.
                            "on_time": on_time,
                        })

            # --- Cancelación voluntaria ---------------------------------------
            hazard = BASE_MONTHLY_CHURN
            # Imperfección (cohortes): el descuento de bienvenida genera un pico
            # de cancelación previsible en el mes 2, al cobrarse el precio pleno.
            if sub.had_welcome_discount and k == 1:
                hazard += WELCOME_DISCOUNT_CHURN_SPIKE
            # Imperfección (cohortes): los regalos no siguen el patrón del titular:
            # caen en bloque al acabar el periodo regalado.
            if sub.gifted:
                if gift_term is not None and k == gift_term:
                    hazard = 1.0 - P_GIFT_RENEWED
                else:
                    hazard = BASE_MONTHLY_CHURN * 0.35
            if in_summer:
                hazard *= 1.25

            if k > 0 and rng.random() < hazard:
                cancel_raw = max(
                    last_activity_day,
                    cursor + timedelta(days=int(rng.integers(0, 27))))
                reason = str(rng.choice(CANCEL_REASONS, p=CANCEL_REASON_WEIGHTS))
                # Una baja posterior al corte no se observa: dentro del histórico
                # la suscripción se queda viva.
                if cancel_raw <= END_DATE:
                    state = "cancelled"
                    cancel_date = cancel_raw
                    cancel_reason = reason
                    ev_n += 1
                    events.append({"event_id": f"EV{ev_n:08d}",
                                   "subscription_id": sub.subscription_id,
                                   "event_type": "cancelled", "event_date": cancel_date,
                                   "previous_plan": plan, "new_plan": None})
                    if sub.had_welcome_discount and k == 1:
                        bump("cohort_welcome_discount_month2_churn")
                    if sub.gifted and gift_term is not None and k == gift_term:
                        bump("cohort_gift_term_end_churn")
                break

            cursor = add_months(cursor, 1)
            months_elapsed += 1

        final_status.append(state)
        final_cancel_date.append(cancel_date)
        final_cancel_reason.append(cancel_reason)
        final_plan.append(plan)

    subscriptions = subscriptions.copy()
    subscriptions["status"] = final_status
    subscriptions["cancel_date"] = final_cancel_date
    subscriptions["cancel_reason"] = final_cancel_reason
    # El plan final refleja upgrades/downgrades acumulados.
    subscriptions["plan"] = final_plan

    ev_df = pd.DataFrame(events).sort_values("event_date").reset_index(drop=True)
    pay_df = pd.DataFrame(payments).sort_values("payment_date").reset_index(drop=True)
    shp_df = pd.DataFrame(shipments).sort_values("ship_date").reset_index(drop=True)
    return subscriptions, ev_df, pay_df, shp_df


def apply_gateway_migration(payments: pd.DataFrame) -> pd.DataFrame:
    """Imperfección (TS): migración de pasarela -> ~1 semana sin datos de pagos."""
    end = GATEWAY_MIGRATION_START + timedelta(days=GATEWAY_MIGRATION_DAYS - 1)
    mask = ((payments["payment_date"] >= GATEWAY_MIGRATION_START)
            & (payments["payment_date"] <= end))
    bump("ts_gateway_migration_payments_dropped", int(mask.sum()))
    return payments.loc[~mask].reset_index(drop=True)


# =============================================================================
# 7. SHOP ORDERS  (+ demanda censurada por rotura de stock)
# =============================================================================

def gen_shop_orders(customers: pd.DataFrame, products: pd.DataFrame,
                    timelines: dict[str, FlavorTimeline], prices: dict[str, float],
                    stores: pd.DataFrame, popularity: dict[str, float]):
    store_ids = stores["store_id"].tolist()
    store_open = dict(zip(stores["store_id"], stores["opening_date"]))
    merch_skus = products.loc[products["product_type"] == "merch", "product_sku"].tolist()

    flavors = list(timelines.keys())
    flavor_pop = np.array([popularity[f] for f in flavors])

    orders, lines = [], []
    o_n = 0

    def emit_order(customer_id, order_date, channel) -> bool:
        """Crea un pedido. Devuelve False si no ha llegado a existir."""
        nonlocal o_n
        store_id = None
        if channel == "store":
            opened = [s for s in store_ids if store_open[s] <= order_date]
            if not opened:
                return False
            store_id = opened[int(rng.integers(0, len(opened)))]

        # La cesta se monta ANTES que el pedido: si no hay nada que vender ese
        # día, el pedido no existe. Antes se creaba primero y podía quedarse
        # sin líneas, y esos huérfanos acababan contados como demanda
        # censurada por rotura de stock sin serlo.
        # Y se agrega por SKU: la misma referencia añadida dos veces a la cesta
        # es una línea con más unidades, no dos líneas.
        basket: dict[str, int] = {}
        n_picks = int(rng.integers(1, 4)) + (1 if rng.random() < 0.25 else 0)
        # La estacionalidad del sabor pondera su popularidad base.
        season_w = flavor_pop * np.array(
            [flavor_season_factor(f, order_date) for f in flavors])
        season_w = season_w / season_w.sum()
        for _ in range(n_picks):
            if merch_skus and rng.random() < 0.18:
                sku = merch_skus[int(rng.integers(0, len(merch_skus)))]
                qty = int(rng.integers(1, 3))
            else:
                flavor = str(rng.choice(flavors, p=season_w))
                sku = timelines[flavor].sku_on(order_date)
                if sku is None:          # sabor aún no lanzado o ya descatalogado
                    continue
                qty = int(rng.integers(1, 7))
            basket[sku] = basket.get(sku, 0) + qty

        if not basket:
            return False

        o_n += 1
        order_id = f"SO{o_n:07d}"
        orders.append({"order_id": order_id, "customer_id": customer_id,
                       "order_date": order_date, "channel": channel,
                       "store_id": store_id})
        for sku, qty in basket.items():
            lines.append({"order_id": order_id, "product_sku": sku,
                          "quantity": qty,
                          "unit_price": round(
                              prices[sku] * float(rng.choice([1.0, 1.0, 0.95, 0.9])), 2)})
        return True

    # 7a. Compras de clientes identificados, repartidas desde su alta.
    for cust in customers.itertuples(index=False):
        days_alive = (END_DATE - cust.signup_date).days
        if days_alive <= 0:
            continue
        expected = SHOP_ORDERS_PER_CUSTOMER_YEAR * days_alive / 365.0
        n_orders = int(rng.poisson(expected))
        if n_orders == 0:
            continue

        # Fechas muestreadas directamente del tramo POSTERIOR al alta, con los
        # mismos pesos de tendencia y estacionalidad. Antes se sorteaba sobre
        # todo el histórico y se reintentaba hasta caer después del alta: eso
        # descartaba pedidos en silencio y penalizaba dos veces a los clientes
        # de alta reciente.
        start_idx = bisect_left(ALL_DAYS, cust.signup_date)
        window_w = DAY_WEIGHTS[start_idx:]
        window_p = window_w / window_w.sum()
        for offset in rng.choice(len(window_w), size=n_orders, p=window_p):
            d = ALL_DAYS[start_idx + int(offset)]
            channel = "store" if (has_value(cust.home_store_id) and rng.random() < 0.45) \
                else ("store" if rng.random() < 0.18 else "online")
            emit_order(cust.customer_id, d, channel)

    # 7b. Imperfección (atribución): venta en boutique sin fidelización.
    #     customer_id NULL -> no toda venta offline es atribuible a un cliente.
    n_walkin = int(len(orders) * P_STORE_ORDER_NO_LOYALTY)
    for d in sample_days(n_walkin):
        if emit_order(None, d, "store"):
            bump("att_shop_orders_without_customer")

    orders_df = pd.DataFrame(orders)
    lines_df = pd.DataFrame(lines)

    # --- 7c. Imperfección (TS): roturas de stock -> demanda censurada ---------
    # Se eliminan las líneas de ese sabor en la ventana: en los datos parece
    # demanda 0 cuando en realidad no había producto que vender.
    #
    # La ventana no se coloca a ciegas. Una rotura sobre un sabor recién
    # lanzado, ya descatalogado o fuera de su temporada no censura nada, y una
    # imperfección que no deja rastro no se puede detectar ni tratar en el
    # análisis: sería ruido en el manifiesto y nada en los datos. Por eso se
    # sortea el sabor según su popularidad, la ventana dentro de su vida de
    # catálogo, y se reintenta hasta que censure demanda de verdad.
    order_dates = orders_df.set_index("order_id")["order_date"]
    line_dates = lines_df["order_id"].map(order_dates)

    stockouts = []
    censored_any = pd.Series(False, index=lines_df.index)
    for _ in range(N_STOCKOUT_WINDOWS):
        best = None
        for _attempt in range(STOCKOUT_PLACEMENT_ATTEMPTS):
            flavor = str(rng.choice(flavors, p=flavor_pop))
            versions = timelines[flavor].versions
            skus = [v[0] for v in versions]
            length = int(rng.integers(*STOCKOUT_LENGTH_DAYS))
            lo = max(START_DATE + timedelta(days=120), min(v[1] for v in versions))
            hi = min(END_DATE, max((v[2] or END_DATE) for v in versions))                 - timedelta(days=length + 5)
            if hi <= lo:
                continue
            w_start = rand_date(lo, hi)
            w_end = w_start + timedelta(days=length)
            mask = (lines_df["product_sku"].isin(skus)
                    & (line_dates >= w_start) & (line_dates <= w_end)
                    & ~censored_any)
            n_censored = int(mask.sum())
            if best is None or n_censored > best[0]:
                best = (n_censored, flavor, w_start, w_end, mask)
            if n_censored >= MIN_STOCKOUT_CENSORED_LINES:
                break

        n_censored, flavor, w_start, w_end, mask = best
        censored_any = censored_any | mask
        stockouts.append({"flavor": flavor, "start": str(w_start), "end": str(w_end),
                          "censored_order_lines": n_censored})
        bump("ts_stockout_windows")
        bump("ts_stockout_censored_order_lines", n_censored)

    lines_df = lines_df.loc[~censored_any].reset_index(drop=True)

    # Pedidos que se quedaron sin ninguna línea tras la censura -> se descartan.
    keep = set(lines_df["order_id"])
    dropped = orders_df.loc[~orders_df["order_id"].isin(keep)]
    if len(dropped):
        bump("ts_stockout_emptied_orders", len(dropped))
    orders_df = orders_df.loc[orders_df["order_id"].isin(keep)].reset_index(drop=True)

    orders_df = orders_df.sort_values("order_date").reset_index(drop=True)
    return orders_df, lines_df, stockouts


# =============================================================================
# 8. MARKETING TOUCHPOINTS
# =============================================================================

CHANNEL_COST = {
    "paid_social": (0.35, 2.60),
    "influencer_code": (0.80, 4.20),
    "podcast_ads": (0.55, 3.10),
    "referral": (4.00, 8.00),
    "organic": (0.0, 0.0),
    "direct_unknown": (0.0, 0.0),
}
PAID_CHANNELS = ["paid_social", "influencer_code", "podcast_ads", "referral", "organic"]
PAID_WEIGHTS = np.array([0.34, 0.20, 0.16, 0.10, 0.20])

# Cada código pertenece a UN creador... salvo SHARED_INFLUENCER_CODE, que se
# reparte entre dos (ver gen_touchpoints).
INFLUENCER_CODES = ["TUESTE10", "BARISTA15", "AROMA25", "RITUAL10"]
CODE_CREATOR = {"TUESTE10": "MARTACAFE", "BARISTA15": "ELBARISTA",
                "AROMA25": "NOELIAG", "RITUAL10": "PABLOTUESTE"}
PODCAST_SHOWS = ["ENTREPAUSAS", "CAFEYCODIGO", "DESPIERTA", "SOBREMESA"]


def _campaign_id(channel: str, d: date) -> str:
    q = (d.month - 1) // 3 + 1
    if channel == "paid_social":
        return f"PS-{d.year}Q{q}-{['PROSPECT', 'RETARGET', 'LOOKALIKE'][int(rng.integers(0, 3))]}"
    if channel == "podcast_ads":
        return f"POD-{PODCAST_SHOWS[int(rng.integers(0, len(PODCAST_SHOWS)))]}-{d.year}Q{q}"
    if channel == "influencer_code":
        code = INFLUENCER_CODES[int(rng.integers(0, len(INFLUENCER_CODES)))]
        return f"INFL-{code}"
    if channel == "referral":
        return f"REF-MEMBER-{d.year}"
    if channel == "organic":
        return f"ORG-{['SEO', 'NEWSLETTER', 'BLOG'][int(rng.integers(0, 3))]}"
    return "NONE"


def _cost_for(channel: str) -> float:
    lo, hi = CHANNEL_COST[channel]
    return round(float(rng.uniform(lo, hi)), 2) if hi > 0 else 0.0


def gen_touchpoints(customers: pd.DataFrame) -> pd.DataFrame:
    rows = []
    t_n = 0

    def emit(customer_id, channel, campaign_id, ts, resolved, cost=None, at=None):
        nonlocal t_n
        t_n += 1
        rows.append({
            "touchpoint_id": f"TP{t_n:08d}",
            "customer_id": customer_id,
            "channel": channel,
            "campaign_id": campaign_id,
            "cost": _cost_for(channel) if cost is None else cost,
            # `at` sólo se pasa cuando varias filas representan el MISMO
            # impacto (código de influencer compartido): deben compartir hora.
            "timestamp": at if at is not None else random_time_on(ts),
            "resolved_to_conversion": resolved,
        })
        return rows[-1]

    for cust in customers.itertuples(index=False):
        signup = cust.signup_date
        n_tp = int(rng.integers(1, 6))
        # Recorrido previo al alta: hasta ~70 días de ventana de consideración.
        offsets = sorted(int(rng.integers(0, 70)) for _ in range(n_tp))
        journey_dates = [clamp(signup - timedelta(days=o), START_DATE, signup)
                         for o in reversed(offsets)]

        for i, ts in enumerate(journey_dates):
            is_last = (i == len(journey_dates) - 1)
            acq = cust.acquisition_channel
            acq = None if (acq is None or pd.isna(acq)) else str(acq)
            if is_last and acq is not None and acq != "direct_unknown":
                channel = acq
            else:
                channel = str(rng.choice(PAID_CHANNELS, p=PAID_WEIGHTS))

            # --- Imperfección: mismo código de influencer, dos creadores -------
            # Durante su ventana, ambos creadores promocionan el MISMO código y
            # los dos reclaman la conversión: el touchpoint aparece duplicado con
            # dos campaign_id que comparten código. Doble conteo de CAC si no se
            # deduplica. El resto de códigos son 1:1 con su creador.
            if channel == "influencer_code":
                if (SHARED_CODE_WINDOW[0] <= ts <= SHARED_CODE_WINDOW[1]
                        and rng.random() < P_SHARED_CODE_IN_WINDOW):
                    shared_at = random_time_on(ts)
                    for creator in SHARED_CODE_CREATORS:
                        emit(cust.customer_id, channel,
                             f"INFL-{SHARED_INFLUENCER_CODE}-{creator}", ts, is_last,
                             at=shared_at)
                        bump("att_shared_influencer_code_touchpoints")
                    continue
                code = INFLUENCER_CODES[int(rng.integers(0, len(INFLUENCER_CODES)))]
                campaign = f"INFL-{code}-{CODE_CREATOR[code]}"
            else:
                campaign = _campaign_id(channel, ts)

            # --- Imperfección: touchpoint que no resuelve a customer_id -------
            if rng.random() < P_TOUCHPOINT_UNRESOLVED:
                emit(None, channel, campaign, ts, False)
                bump("att_unresolved_touchpoints")
                continue

            tp = emit(cust.customer_id, channel, campaign, ts, is_last)

            # --- Imperfección: caída de atribución paid_social (iOS ATT) ------
            # La conversión ocurrió, pero el canal deja de poder reclamarla.
            if (channel == "paid_social" and ATT_WINDOW_START <= ts <= ATT_WINDOW_END
                    and rng.random() < ATT_SUPPRESSION_RATE):
                tp["customer_id"] = None
                tp["resolved_to_conversion"] = False
                bump("att_ios_att_suppressed_touchpoints")

    # Tráfico anónimo puro que se acumula como direct_unknown.
    for ts in sample_days(N_ORPHAN_TOUCHPOINTS):
        emit(None, "direct_unknown", "NONE", ts, False)
        bump("att_direct_unknown_orphan_touchpoints")

    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


# =============================================================================
# PERSISTENCIA
# =============================================================================

DATE_COLUMNS = {
    "signup_date", "start_date", "cancel_date", "event_date", "ship_date",
    "launch_date", "discontinue_date", "order_date", "opening_date",
    "payment_date", "timestamp",
}


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Tipa las columnas de fecha como datetime64 para parquet/DuckDB."""
    out = df.copy()
    for col in out.columns:
        if col in DATE_COLUMNS:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out.loc[:, [c for c in out.columns if not c.startswith("_")]]


def persist(tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}

    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        for name, df in tables.items():
            df = normalize(df)
            counts[name] = len(df)
            df.to_parquet(RAW_DIR / f"{name}.parquet", index=False)
            con.register("tmp_df", df)
            con.execute(f"CREATE OR REPLACE TABLE raw_{name} AS SELECT * FROM tmp_df")
            con.unregister("tmp_df")
    finally:
        con.close()
    return counts


# =============================================================================
# RESUMEN
# =============================================================================

IMPERFECTION_LABELS = {
    # Series temporales / forecasting
    "ts_seasonal_pause_events": "Pausas estacionales (verano/Navidad)",
    "ts_seasonal_resume_events": "  └ reanudaciones tras pausa",
    "ts_dunning_payment_failures": "Fallos de cobro (dunning)",
    "ts_dunning_recovered": "  └ recuperados al reintentar",
    "ts_dunning_involuntary_churn": "  └ churn involuntario",
    "ts_gateway_migration_payments_dropped": "Pagos perdidos por migración de pasarela",
    "ts_sku_relaunched_flavors": "Sabores descatalogados y relanzados (nuevo SKU)",
    "ts_stockout_windows": "Ventanas de rotura de stock",
    "ts_stockout_censored_order_lines": "  └ líneas de pedido censuradas",
    "ts_stockout_emptied_orders": "  └ pedidos vaciados por completo",
    # Cohortes
    "cohort_welcome_discount_subs": "Suscripciones con descuento de bienvenida",
    "cohort_welcome_discount_month2_churn": "  └ cancelan en el mes 2 (fin descuento)",
    "cohort_gifted_subscriptions": "Suscripciones regaladas",
    "cohort_gift_term_end_churn": "  └ cancelan al acabar el regalo",
    "cohort_plan_downgrades": "Downgrades de plan (menos ingreso, no churn)",
    "cohort_plan_upgrades": "Upgrades de plan",
    "cohort_machine_bundled_trials": "Máquinas con cápsulas de regalo",
    "cohort_machine_trial_conversions": "  └ convierten a suscripción semanas después",
    # Atribución
    "att_shared_influencer_code_touchpoints": "Código de influencer compartido por 2 creadores",
    "att_ios_att_suppressed_touchpoints": "paid_social sin atribución (efecto iOS ATT)",
    "att_unresolved_touchpoints": "Touchpoints sin customer_id resuelto",
    "att_direct_unknown_orphan_touchpoints": "  └ tráfico anónimo puro (direct_unknown)",
    "att_shop_orders_without_customer": "Pedidos de tienda sin fidelización",
    "att_machine_orders_without_customer": "Máquinas vendidas sin cliente identificado",
    "att_customers_null_acquisition_channel": "Clientes sin canal de adquisición (NULL)",
    # Identidad
    "identity_duplicate_customers": "Clientes duplicados por variantes de email",
}

SECTIONS = [
    ("SERIES TEMPORALES / FORECASTING", "ts_"),
    ("COHORTES", "cohort_"),
    ("ATRIBUCIÓN", "att_"),
    ("IDENTIDAD DE CLIENTE", "identity_"),
]


def print_summary(counts: dict[str, int], extra: dict) -> None:
    line = "=" * 74
    print(f"\n{line}\nRESUMEN DE GENERACIÓN — Capsule Club Analytics\n{line}")
    print(f"Semilla: {SEED}   Histórico: {START_DATE} → {END_DATE} "
          f"({(END_DATE - START_DATE).days // 365} años)")
    print(f"Parquet: {RAW_DIR}\nDuckDB : {DUCKDB_PATH}")

    print(f"\n{'-' * 74}\nFILAS POR TABLA\n{'-' * 74}")
    for name, n in counts.items():
        print(f"  raw_{name:<24} {n:>10,}")
    print(f"  {'TOTAL':<28} {sum(counts.values()):>10,}")

    print(f"\n{'-' * 74}\nIMPERFECCIONES INYECTADAS (docs/data_imperfections.md)\n{'-' * 74}")
    for title, prefix in SECTIONS:
        print(f"\n  {title}")
        for key, label in IMPERFECTION_LABELS.items():
            if key.startswith(prefix):
                print(f"    {label:<56} {IMP.get(key, 0):>8,}")

    print(f"\n{'-' * 74}\nDETALLE DE VENTANAS INYECTADAS\n{'-' * 74}")
    gw_end = GATEWAY_MIGRATION_START + timedelta(days=GATEWAY_MIGRATION_DAYS - 1)
    print(f"  Migración de pasarela : {GATEWAY_MIGRATION_START} → {gw_end}")
    print(f"  Ventana iOS ATT       : {ATT_WINDOW_START} → {ATT_WINDOW_END} "
          f"(supresión {ATT_SUPPRESSION_RATE:.0%} de paid_social)")
    print(f"  Código compartido     : INFL-{SHARED_INFLUENCER_CODE} "
          f"({' + '.join(SHARED_CODE_CREATORS)}), "
          f"{SHARED_CODE_WINDOW[0]} → {SHARED_CODE_WINDOW[1]}")
    print("  Roturas de stock      :")
    for s in extra["stockouts"]:
        print(f"    - {s['flavor']:<22} {s['start']} → {s['end']} "
              f"({s['censored_order_lines']:>4} líneas censuradas)")
    print("  SKUs relanzados       :")
    for r in extra["relaunches"]:
        print(f"    - {r['flavor']:<22} {r['old_sku']} → {r['new_sku']} (desde {r['switch_date']})")

    missing = [k for k in IMPERFECTION_LABELS if IMP.get(k, 0) == 0]
    print(f"\n{'-' * 74}")
    if missing:
        print("  AVISO — imperfecciones con 0 registros:")
        for k in missing:
            print(f"    ! {k}")
    else:
        print("  OK — todas las imperfecciones del catálogo están presentes.")
    print(f"{line}\n")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    # La consola de Windows usa cp1252 por defecto y revienta con "→"/acentos.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    print("Generando datos sintéticos (semilla fija, puede tardar ~1 min)...")

    stores = gen_stores()
    products, timelines, prices, flavor_popularity = gen_products()
    machines = gen_machines()
    print("  · catálogo (stores, products, machines) listo")

    customers = gen_customers(stores)
    print(f"  · {len(customers):,} clientes")

    machine_orders = gen_machine_orders(customers, machines, stores)
    print(f"  · {len(machine_orders):,} pedidos de máquina")

    subscriptions = gen_subscriptions(customers, machine_orders)
    print(f"  · {len(subscriptions):,} suscripciones — simulando ciclo de vida")

    subscriptions, events, payments, shipments = simulate_lifecycle(
        subscriptions, timelines, prices, flavor_popularity)
    payments = apply_gateway_migration(payments)
    print(f"  · {len(events):,} eventos, {len(payments):,} pagos, {len(shipments):,} envíos")

    shop_orders, shop_order_lines, stockouts = gen_shop_orders(
        customers, products, timelines, prices, stores, flavor_popularity)
    print(f"  · {len(shop_orders):,} pedidos de tienda ({len(shop_order_lines):,} líneas)")

    touchpoints = gen_touchpoints(customers)
    print(f"  · {len(touchpoints):,} touchpoints de marketing")

    tables = {
        "customers": customers,
        "subscriptions": subscriptions,
        "subscription_events": events,
        "shipments": shipments,
        "machines": machines,
        "machine_orders": machine_orders,
        "shop_orders": shop_orders,
        "shop_order_lines": shop_order_lines,
        "products": products,
        "marketing_touchpoints": touchpoints,
        "stores": stores,
        "payments": payments,
    }

    counts = persist(tables)
    print("  · parquet + DuckDB escritos")

    relaunches = [
        {"flavor": f, "old_sku": tl.versions[0][0], "new_sku": tl.versions[1][0],
         "switch_date": str(tl.versions[1][1])}
        for f, tl in timelines.items() if tl.relaunched
    ]
    extra = {"stockouts": stockouts, "relaunches": relaunches}

    manifest = {
        "seed": SEED,
        "start_date": str(START_DATE),
        "end_date": str(END_DATE),
        "row_counts": counts,
        "imperfections": IMP,
        "gateway_migration": {
            "start": str(GATEWAY_MIGRATION_START),
            "end": str(GATEWAY_MIGRATION_START + timedelta(days=GATEWAY_MIGRATION_DAYS - 1)),
        },
        "ios_att_window": {"start": str(ATT_WINDOW_START), "end": str(ATT_WINDOW_END),
                           "suppression_rate": ATT_SUPPRESSION_RATE},
        "shared_influencer_code": {
            "code": SHARED_INFLUENCER_CODE, "creators": list(SHARED_CODE_CREATORS),
            "window": [str(SHARED_CODE_WINDOW[0]), str(SHARED_CODE_WINDOW[1])],
        },
        "stockouts": stockouts,
        "sku_relaunches": relaunches,
    }
    (RAW_DIR / "_imperfections_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print_summary(counts, extra)


if __name__ == "__main__":
    main()
