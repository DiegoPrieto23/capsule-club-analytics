"""
Capsule Club Analytics — glosario del informe.

El informe va dirigido a negocio, así que ningún término técnico aparece sin
explicación a mano. Cada entrada se usa de dos formas: subrayada en el texto,
con un globo al pasar por encima o al tabular hasta ella, y listada entera en la
caja plegable de cada página para quien imprima o use lector de pantalla.

Las definiciones están escritas para alguien que dirige el negocio, no para
alguien que hace el análisis: dicen qué significa el número y qué decisión
depende de él, no cómo se calcula.
"""

from __future__ import annotations

from markupsafe import Markup, escape

GLOSSARY: dict[str, dict[str, str]] = {
    "cohorte": {
        "name": "Cohorte",
        "definition": ("El grupo de clientes que se dieron de alta el mismo mes. Se siguen "
                       "juntos a lo largo del tiempo para poder comparar peras con peras: "
                       "la cohorte de enero a los seis meses frente a la de junio a los seis "
                       "meses, en vez de mezclar clientes nuevos con veteranos."),
    },
    "retencion": {
        "name": "Curva de retención",
        "definition": ("Qué porcentaje de una cohorte sigue suscrito a cada edad. Es la "
                       "forma honesta de medir cuánto dura un cliente cuando la mayoría "
                       "todavía no se ha ido: usa la información de los que siguen vivos "
                       "sin tener que esperar a que cancelen."),
    },
    "churn": {
        "name": "Churn",
        "definition": ("Cancelación. El churn voluntario lo decide el cliente; el "
                       "involuntario ocurre porque falla el cobro (una tarjeta caducada, "
                       "por ejemplo) y el cliente ni se entera de que le han dado de baja."),
    },
    "hazard": {
        "name": "Hazard",
        "definition": ("El riesgo de cancelar en un mes concreto, contando sólo a los que "
                       "llegaron vivos a ese mes. Sirve para localizar *cuándo* se van: un "
                       "pico de hazard en el mes 2 señala algo que pasa en el mes 2."),
    },
    "ltv": {
        "name": "LTV",
        "definition": ("Valor de vida del cliente: todo el ingreso que deja desde que se "
                       "da de alta hasta que se va. Aquí se proyecta a 36 meses con la "
                       "curva de retención de su canal, no se espera a verlo."),
    },
    "cac": {
        "name": "CAC",
        "definition": ("Coste de adquisición: lo que cuesta de media conseguir un cliente "
                       "nuevo. En este informe se publica cargado, es decir repartiendo "
                       "también el gasto que no se pudo asignar a nadie."),
    },
    "arpu": {
        "name": "ARPU",
        "definition": ("Ingreso medio por cliente y mes. Junto con los meses que dura el "
                       "cliente forma el LTV: LTV = ARPU × meses de vida."),
    },
    "mrr": {
        "name": "MRR",
        "definition": ("Ingreso recurrente mensual: la suma de las cuotas vigentes. Es la "
                       "foto de la base contratada, antes de saber si se cobra o no."),
    },
    "rfm": {
        "name": "RFM",
        "definition": ("Una forma clásica de segmentar compradores con tres datos: cuándo "
                       "compró por última vez (Recencia), cuántas veces (Frecuencia) y "
                       "cuánto se ha gastado (Monetario). Cada cliente recibe una nota del "
                       "1 al 5 en cada eje y el cruce da segmentos accionables."),
    },
    "touchpoint": {
        "name": "Touchpoint",
        "definition": ("Cada contacto de marketing con una persona antes de que se "
                       "suscriba: un anuncio visto, un clic, un código de influencer. El "
                       "recorrido completo de contactos es lo que se reparte entre canales."),
    },
    "gap": {
        "name": "Attribution gap",
        "definition": ("La parte del marketing que no se puede atribuir a nadie: contactos "
                       "que no se logran unir a un cliente, y altas que aparecen sin "
                       "ningún contacto previo. Es gasto real que no se puede optimizar."),
    },
    "markov": {
        "name": "Cadena de Markov",
        "definition": ("Un modelo que trata el recorrido del cliente como un paseo entre "
                       "canales y mide cuánto caería la conversión si un canal "
                       "desapareciera. A diferencia de dar el mérito al primer o al último "
                       "contacto, reparte por contribución y no por posición."),
    },
    "backtesting": {
        "name": "Backtesting",
        "definition": ("Poner a prueba una previsión con el pasado: se tapa el último tramo "
                       "del histórico, se pronostica a ciegas y se compara con lo que de "
                       "verdad pasó. Es lo único que permite decir si una previsión es "
                       "creíble antes de usarla."),
    },
    "mape": {
        "name": "MAPE",
        "definition": ("El error medio de una previsión, en porcentaje. Un MAPE del 3% "
                       "significa que, de media, la previsión se equivoca un 3% respecto a "
                       "lo que acabó ocurriendo."),
    },
    "censura": {
        "name": "Demanda censurada",
        "definition": ("Ventas que no ocurrieron porque no había producto, no porque nadie "
                       "lo quisiera. En los datos las dos cosas son un cero idéntico, y "
                       "confundirlas hace que la previsión pida menos stock del necesario."),
    },
    "payback": {
        "name": "Payback",
        "definition": ("Cuántos meses tarda un cliente en devolver lo que costó captarlo. "
                       "Por debajo de doce meses se considera que el crecimiento se puede "
                       "financiar con el propio negocio."),
    },
    "estacionalidad": {
        "name": "Estacionalidad",
        "definition": ("El patrón que se repite cada año o cada semana: agosto siempre "
                       "flojo, marzo siempre fuerte. Separarla de la tendencia evita "
                       "confundir 'baja el negocio' con 'es agosto'."),
    },
    "pausa": {
        "name": "Pausa",
        "definition": ("El suscriptor congela su suscripción temporalmente. No es una baja "
                       "—vuelve— pero ese mes no entra ingreso, así que cuenta como activo "
                       "en la curva de clientes y no en la de ingreso."),
    },
}


def term(key: str, label: str | None = None) -> str:
    """Devuelve el término subrayado con su globo. El texto visible puede cambiar."""
    entry = GLOSSARY[key]
    visible = label if label is not None else entry["name"].lower()
    return (f'<span class="term" tabindex="0">{visible}'
            f'<span class="term-pop"><b>{entry["name"]}</b>{entry["definition"]}</span>'
            f'</span>')


def rich(text: str) -> Markup:
    """
    Convierte `[[clave|texto visible]]` en un término del glosario y `**esto**`
    en negrita.

    Se escribe así en la prosa para que el texto siga siendo legible en el
    fuente y no haya que concatenar HTML a mano en mitad de una frase. El
    escapado se hace aquí, término a término, porque el resultado va marcado
    como seguro y Jinja ya no lo revisa.
    """
    out, rest = [], text
    while "[[" in rest:
        before, _, tail = rest.partition("[[")
        marker, _, rest = tail.partition("]]")
        key, _, label = marker.partition("|")
        out.append(_emphasis(before))
        out.append(term(key, label or None))
    out.append(_emphasis(rest))
    return Markup("".join(out))


def _emphasis(fragment: str) -> str:
    """`**así**` pasa a negrita; el resto del texto se escapa."""
    parts = fragment.split("**")
    rendered = []
    for index, part in enumerate(parts):
        safe = escape(part)
        rendered.append(f"<strong>{safe}</strong>" if index % 2 else str(safe))
    return "".join(rendered)


def entries(keys: list[str]) -> list[dict[str, str]]:
    """Las definiciones que usa una página, en el orden en que se piden."""
    return [{"name": GLOSSARY[k]["name"], "definition": GLOSSARY[k]["definition"]}
            for k in keys]
