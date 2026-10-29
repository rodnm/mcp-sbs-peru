"""Del Excel de la SBS a filas ordenadas. Cada función lee una familia de boletines.

Los Excel de la SBS están hechos para imprimirse: títulos, celdas combinadas, notas al pie y a veces la misma tabla
partida en bloques lado a lado. Estas funciones buscan la estructura (encabezados, etiquetas, bloques) en vez de
depender de números de fila fijos, para que un mes con una entidad más o una nota nueva no rompa nada.
"""
import math
import numbers
import re
from datetime import date

_NOTA = re.compile(r"(?<![\d/])\d{1,2}/(?![\d/])")   # llamadas a nota al pie ("1/", "7/ 8/"), no fechas (31/07/2026)
_PIE = re.compile(r"^(\d{1,2}/|nota|fuente)", re.IGNORECASE)


def limpiar(texto):
    """Saca saltos de línea, asteriscos y llamadas a notas al pie: 'CMAC\\n Piura 1/' -> 'CMAC Piura'."""
    texto = _NOTA.sub(" ", str(texto)).replace("*", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _numero(x):
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and not math.isnan(x)


def _texto(x):
    return isinstance(x, str) and x.strip() != ""


def valor(x):
    if isinstance(x, date):                       # datetime y pandas.Timestamp también son date
        return x.isoformat()[:10]
    if _numero(x):
        return float(x)
    return limpiar(x) if _texto(x) else None


def indicadores_por_entidad(df):
    """Hojas con indicadores en filas y entidades en columnas (B-2401, C-1301, S-302...).

    El encabezado es la fila con más textos antes de los datos. Las columnas con números son entidades; las
    columnas con textos son etiquetas (puede haber varias: B-2401 repite la suya a mitad de hoja y S-302 pone las
    secciones en una columna y los indicadores en otra). Una fila sin números en la primera columna de etiquetas
    abre una sección (SOLVENCIA, RENTABILIDAD...).
    """
    df = df.reset_index(drop=True)
    filas, cols = df.shape
    primera = next((r for r in range(filas) if sum(_numero(v) for v in df.iloc[r]) >= 2), None)
    if not primera:
        return []
    encabezado = max(range(primera), key=lambda r: (sum(_texto(v) for v in df.iloc[r]), -r))
    debajo = df.iloc[encabezado + 1:]
    entidades = {c: limpiar(df.iat[encabezado, c]) for c in range(cols)
                 if _texto(df.iat[encabezado, c]) and any(_numero(v) for v in debajo.iloc[:, c])}
    etiquetas = [c for c in range(cols) if c not in entidades and any(_texto(v) for v in debajo.iloc[:, c])]
    if not etiquetas:
        return []

    seccion, salida = None, []
    for r in range(encabezado + 1, filas):
        textos = {c: df.iat[r, c] for c in etiquetas if _texto(df.iat[r, c])}
        valores = {c: df.iat[r, c] for c in entidades if _numero(df.iat[r, c])}
        if not valores:
            if etiquetas[0] in textos:
                seccion = limpiar(textos[etiquetas[0]])
            continue
        for c, v in valores.items():
            izquierda = [e for e in textos if e < c]
            if izquierda:
                salida.append({"entidad": entidades[c], "seccion": seccion,
                               "indicador": limpiar(textos[max(izquierda)]), "valor": float(v)})
    return salida


def rankings(df):
    """Hojas de ranking (B-2332, B-2333, C-1205, S-342...): bloques con puesto, empresa, monto y participación.

    Cada celda 'Empresas' abre un bloque; su título es el texto más cercano de las filas de arriba. Los bloques
    pueden estar apilados o lado a lado, así que cada uno solo mira sus propias columnas.
    """
    df = df.reset_index(drop=True)
    filas, cols = df.shape
    cabeceras = sorted((r, c) for r in range(filas) for c in range(cols)
                       if _texto(df.iat[r, c]) and limpiar(df.iat[r, c]).lower() == "empresas")
    salida = []
    for r, c in cabeceras:
        siguiente = min((cc for rr, cc in cabeceras if rr == r and cc > c), default=cols + 1)
        desde, hasta = max(c - 1, 0), min(siguiente - 2, cols - 1)
        titulo = next((limpiar(df.iat[k, j]) for k in range(r - 1, max(r - 5, -1), -1)
                       for j in range(desde, min(c + 4, hasta + 1)) if _texto(df.iat[k, j])), None)
        empezo = False
        for k in range(r + 1, filas):
            celdas = [(j, df.iat[k, j]) for j in range(desde, hasta + 1)
                      if _numero(df.iat[k, j]) or _texto(df.iat[k, j])]
            puesto = celdas[0][1] if celdas else None
            if not (_numero(puesto) and float(puesto).is_integer()):
                if empezo:
                    break
                continue                      # filas vacías o subtítulos como "( % )" antes de los datos
            nombre = next(((j, v) for j, v in celdas[1:] if _texto(v)), None)
            if nombre is None:
                break
            numeros = [float(v) for j, v in celdas if j > nombre[0] and _numero(v)] + [None] * 3
            salida.append({"bloque": titulo, "puesto": int(puesto), "entidad": limpiar(nombre[1]),
                           "monto": numeros[0], "participacion_pct": numeros[1], "acumulado_pct": numeros[2]})
            empezo = True
    return salida


def tabla(df, primera_columna):
    """Una tabla simple cuyo encabezado empieza con `primera_columna` ('AFP' en FP-1232, 'Día' en FP-1359).

    Termina en la primera fila vacía o nota al pie después de los datos. Las fechas salen como '2026-09-01'.
    """
    df = df.reset_index(drop=True)
    inicio = next((r for r in range(len(df))
                   if _texto(df.iat[r, 0]) and limpiar(df.iat[r, 0]).lower() == primera_columna.lower()), None)
    if inicio is None:
        return []
    nombres = {c: limpiar(v) for c, v in enumerate(df.iloc[inicio]) if _texto(v)}
    salida = []
    for r in range(inicio + 1, len(df)):
        clave = df.iat[r, 0]
        vacia = not (_texto(clave) or isinstance(clave, date) or _numero(clave))
        if vacia or (_texto(clave) and _PIE.match(clave.strip())):
            if salida:
                break
            continue
        fila = {nombres[c]: valor(df.iat[r, c]) for c in nombres}
        salida.append({k: v for k, v in fila.items() if v is not None})
    return salida


def rentabilidades(df):
    """Rentabilidad de un fondo AFP (FP-1219-0, FP-1360...): tablas 'Acumulada' y 'Anualizada'.

    Encima de los datos hay tres filas de encabezado: la comparación ('Set 2026 / Set 2025'), el plazo ('(1 año)')
    y el tipo ('Nominal' / 'Real'). Las dos primeras son celdas combinadas, por eso se arrastran a la derecha.
    """
    df = df.reset_index(drop=True)
    filas, cols = df.shape
    salida, r = [], 0
    while r < filas:
        titulo = df.iat[r, 0]
        if not (_texto(titulo) and limpiar(titulo).lower().startswith("rentabilidad nominal y real")):
            r += 1
            continue
        tipo = "anualizada" if "anualizada" in titulo.lower() else "acumulada"
        fila_tipo = next((k for k in range(r + 1, min(r + 8, filas))
                          if any(_texto(v) and v.strip().lower() == "nominal" for v in df.iloc[k])), None)
        if fila_tipo is None:
            r += 1
            continue
        columnas, comparacion, plazo = {}, None, None
        for c in range(1, cols):
            if _texto(df.iat[fila_tipo - 2, c]):
                comparacion = limpiar(df.iat[fila_tipo - 2, c])
            if _texto(df.iat[fila_tipo - 1, c]):
                plazo = limpiar(df.iat[fila_tipo - 1, c]).strip("()")
            if _texto(df.iat[fila_tipo, c]):
                columnas[c] = (comparacion, plazo, df.iat[fila_tipo, c].strip().lower())
        k = fila_tipo + 1
        while k < filas and _texto(df.iat[k, 0]):
            por_plazo = {}
            for c, (comp, pl, clase) in columnas.items():
                if _numero(df.iat[k, c]):
                    por_plazo.setdefault((comp, pl), {})[clase] = float(df.iat[k, c])
            for (comp, pl), v in por_plazo.items():
                salida.append({"tipo": tipo, "afp": limpiar(df.iat[k, 0]), "plazo": pl, "comparacion": comp,
                               "nominal_pct": v.get("nominal"), "real_pct": v.get("real")})
            k += 1
        r = k
    return salida
