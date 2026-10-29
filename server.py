"""Servidor MCP de la SBS del Perú: banca, cajas, AFP y seguros, leídos directo de los boletines oficiales.

    uv run pytest -q                                          # el contrato
    uv run server.py                                          # el servidor, por stdio
    claude mcp add --scope project sbs -- uv run server.py    # conectarlo a Claude Code

Los datos salen de intranet2.sbs.gob.pe, el servidor de archivos de la propia SBS (ver sbs/fuente.py). Las cuentas
las hace Python, no el modelo: cada cifra sale de un Excel con URL que cualquiera puede abrir para comprobarla.
"""
import json
import re
from datetime import date

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from openpyxl.utils import get_column_letter

from sbs import catalogo, fuente, parsers

SOLO_LECTURA = {"readOnlyHint": True, "openWorldHint": True}

mcp = FastMCP("sbs", instructions=(
    "Boletines estadísticos oficiales de la Superintendencia de Banca, Seguros y AFP del Perú (SBS), leídos directo "
    "de sus archivos. Para comparar bancos, financieras y cajas usa indicadores (morosidad, ROE, solvencia, "
    "liquidez) y ranking (créditos, depósitos, patrimonio); para las AFP, afp_comisiones, afp_valor_cuota y "
    "afp_rentabilidad; para seguros, seguros_ranking y seguros_indicadores. Si el dato está en otro boletín, busca "
    "el código con listar_reportes y léelo con reporte. No calcules a mano: cita en cada cifra el código del "
    "boletín, el periodo y la URL de la fuente. Este servidor no tiene las tasas de interés por entidad de Retasas: "
    "la SBS solo las publica en una web que bloquea a los programas."))

_ALIAS_INDICADOR = {   # palabra común -> textos que debe tener el nombre oficial (sin tildes). Bancos y cajas los
    "morosidad": ("creditos atrasados (criterio sbs) / creditos directos",),   # escriben distinto: "/" o "sobre"
    "mora": ("creditos atrasados (criterio sbs) / creditos directos",),
    "roe": ("utilidad neta", "patrimonio"),
    "roa": ("utilidad neta", "activo promedio"),
    "solvencia": ("ratio de capital global",),
    "capital": ("ratio de capital global",),
    "rendimiento": ("ingresos financieros anualizados", "activo productivo"),
    "eficiencia": ("gastos de operacion", "margen financiero"),
}
_CLAVES_COMISION = (("descuento", "descuento_total_pct"), ("saldo", "comision_sobre_saldo_pct"),
                    ("prima", "prima_de_seguro_pct"), ("aporte", "aporte_obligatorio_pct"))


# ---------------------------------------------------------------- piezas comunes

def _boletin(codigo, periodo=None):
    """Baja y lee un boletín; devuelve sus hojas y la cabecera de fuente que acompaña a cada respuesta."""
    f = catalogo.ficha(codigo)
    periodo = fuente.normalizar(periodo) if periodo else \
        fuente.ultimo_periodo(f["codigo"], f["extension"])["periodo"]
    archivo = fuente.descargar(f["codigo"], periodo, f["extension"])
    titulo = f["titulo"] or f["codigo"]
    cabecera = {"codigo": f["codigo"], "titulo": titulo, "periodo": periodo, "fuente": archivo.url,
                "actualizado": archivo.actualizado,
                "cita": f"Fuente: SBS, {titulo} ({f['codigo']}), {periodo}. {archivo.url}"}
    return fuente.leer_libro(archivo.contenido), cabecera


def _primera(hojas):
    return next(iter(hojas.values()))


def _indicadores(codigo, indicador, periodo):
    hojas, cabecera = _boletin(codigo, periodo)
    filas = parsers.indicadores_por_entidad(_primera(hojas))
    if not filas:
        raise ToolError(f"No pude leer los indicadores de {cabecera['fuente']}: la SBS pudo cambiar el formato.")
    nombres = list(dict.fromkeys((f["seccion"], f["indicador"]) for f in filas))
    if not indicador:
        return {**cabecera, "entidades": list(dict.fromkeys(f["entidad"] for f in filas)),
                "indicadores_disponibles": [{"seccion": s, "indicador": i} for s, i in nombres]}

    q = catalogo.sin_tildes(indicador)
    alias = _ALIAS_INDICADOR.get(q)
    reglas = (lambda s, i: catalogo.sin_tildes(i) == q,
              lambda s, i: alias is not None and all(t in catalogo.sin_tildes(i) for t in alias),
              lambda s, i: all(p in catalogo.sin_tildes(i) for p in q.split()),
              lambda s, i: all(p in catalogo.sin_tildes(s or "") for p in q.split()))
    elegidos = next((e for regla in reglas if (e := [(s, i) for s, i in nombres if regla(s, i)])), None)
    if not elegidos:
        raise ToolError(f"No encontré el indicador {indicador!r}. Disponibles: " + "; ".join(i for _, i in nombres))

    salida = []
    for seccion, nombre in elegidos:
        valores = [{"entidad": f["entidad"], "valor": f["valor"]} for f in filas
                   if (f["seccion"], f["indicador"]) == (seccion, nombre)]
        totales = [v for v in valores if v["entidad"].lower().startswith("total")]
        salida.append({"seccion": seccion, "indicador": nombre,
                       "valores": sorted((v for v in valores if v not in totales), key=lambda v: -v["valor"]),
                       "total": totales[-1] if totales else None, "subtotales": totales[:-1]})
    return {**cabecera, "orden": "de mayor a menor valor", "indicadores": salida}


def _ranking(codigos, concepto, periodo, limite, escala=1.0):
    vistos = []
    for codigo in codigos:
        hojas, cabecera = _boletin(codigo, periodo)
        filas = parsers.rankings(_primera(hojas))
        bloques = list(dict.fromkeys(f["bloque"] for f in filas if f["bloque"]))
        vistos += bloques
        palabras = catalogo.sin_tildes(concepto).split()
        bloque = next((b for b in bloques if all(p in catalogo.sin_tildes(b) for p in palabras)), None)
        if bloque:
            puestos = [{k: v for k, v in f.items() if k != "bloque"} for f in filas if f["bloque"] == bloque]
            for p in puestos:
                p["monto"] = p["monto"] * escala if p["monto"] is not None else None
            return {**cabecera, "bloque": bloque, "unidad": "miles de soles", "ranking": puestos[:limite]}
    raise ToolError(f"No encontré un ranking de {concepto!r}. Disponibles: {', '.join(vistos)}.")


def _fecha(texto):
    try:
        return date.fromisoformat(str(texto).strip())
    except ValueError:
        raise ToolError(f"Fecha {texto!r} no válida: usen AAAA-MM-DD, por ejemplo 2026-09-15.") from None


def _meses(inicio, fin):
    anio, mes, meses = inicio.year, inicio.month, []
    while (anio, mes) <= (fin.year, fin.month):
        meses.append(f"{anio}-{mes:02d}")
        anio, mes = (anio, mes + 1) if mes < 12 else (anio + 1, 1)
    return meses


# ---------------------------------------------------------------- herramientas

@mcp.tool(annotations=SOLO_LECTURA)
def listar_reportes(sector: str | None = None, texto: str | None = None) -> list[dict]:
    """Lista los boletines de la SBS que conoce este servidor, con su código y título oficial.

    Úsenla cuando ninguna otra herramienta cubre la pregunta, para encontrar el código que luego se lee con reporte.
    sector: "bancos", "financieras", "cajas municipales", "cajas rurales", "empresas de creditos", "afp" o "seguros".
    texto: palabras del título, por ejemplo "liquidez", "morosidad" o "afiliados".
    """
    return catalogo.buscar(sector, texto)


@mcp.tool(annotations=SOLO_LECTURA)
def ultimo_periodo(codigo: str) -> dict:
    """El último mes que la SBS publicó de un boletín, con la fecha en que lo actualizó y su URL.

    Úsenla antes de responder «¿cuál es el dato más reciente?»: la SBS publica con rezago (AFP unas 2 semanas,
    seguros 3, bancos y cajas 4 a 5). Ejemplo: codigo="B-2401".
    """
    f = catalogo.ficha(codigo)
    return {**fuente.ultimo_periodo(f["codigo"], f["extension"]), "titulo": f["titulo"]}


@mcp.tool(annotations=SOLO_LECTURA)
def indicadores(tipo_entidad: str, indicador: str | None = None, periodo: str | None = None) -> dict:
    """Compara entidades financieras con los indicadores oficiales de la SBS, de mayor a menor.

    Úsenla para «¿qué banco tiene menor morosidad?», «ROE de las cajas municipales» o «solvencia de las
    financieras». tipo_entidad: "bancos", "financieras", "cajas municipales", "cajas rurales" o
    "empresas de creditos" (antes edpymes). indicador: "morosidad", "roe", "roa", "solvencia", "liquidez",
    "eficiencia", "rendimiento" (ingresos financieros / activo productivo, lo más parecido a una tasa promedio que
    publica la SBS por entidad) o palabras del nombre oficial; sin indicador devuelve la lista de indicadores y
    entidades. periodo: "AAAA-MM"; por defecto el último publicado. Valores en porcentaje salvo que el nombre diga
    otra cosa; "total" es el del sistema.
    """
    tipo = catalogo.tipo_entidad(tipo_entidad)
    return {"tipo_entidad": tipo, **_indicadores(catalogo.TIPOS[tipo][0], indicador, periodo)}


@mcp.tool(annotations=SOLO_LECTURA)
def ranking(tipo_entidad: str, concepto: str = "creditos", periodo: str | None = None, limite: int = 10) -> dict:
    """Ranking oficial de entidades por tamaño, con monto (miles de soles) y participación de mercado (%).

    Úsenla para «¿cuál es el banco más grande?», «participación de las cajas municipales en depósitos» o «quién
    lidera los créditos a microempresas». tipo_entidad: "bancos", "financieras", "cajas municipales" o "cajas
    rurales". concepto: "creditos", "depositos" o "patrimonio"; para bancos también un tipo de crédito:
    "corporativos", "grandes empresas", "medianas empresas", "pequenas empresas", "microempresas", "hipotecarios",
    "consumo revolvente" o "consumo no revolvente". periodo: "AAAA-MM"; por defecto el último publicado.
    """
    tipo = catalogo.tipo_entidad(tipo_entidad)
    codigo = catalogo.TIPOS[tipo][1]
    if codigo is None:
        raise ToolError(f"Este servidor todavía no tiene el ranking de {tipo}; prueben con indicadores.")
    codigos = [codigo, "B-2333"] if tipo == "bancos" else [codigo]
    return {"tipo_entidad": tipo, **_ranking(codigos, concepto, periodo, limite)}


@mcp.tool(annotations=SOLO_LECTURA)
def afp_comisiones(periodo: str | None = None) -> dict:
    """Comisión sobre el saldo, prima de seguro, aporte obligatorio y descuento total de cada AFP, en %.

    Úsenla para «¿qué AFP cobra menos?» o «¿cuánto me descuentan del sueldo?». periodo: "AAAA-MM" del devengue;
    por defecto el último publicado. "columnas" trae el nombre oficial de cada campo.
    """
    hojas, cabecera = _boletin("FP-1232", periodo)
    filas = parsers.tabla(_primera(hojas), "AFP")
    if not filas:
        raise ToolError(f"No pude leer las comisiones de {cabecera['fuente']}.")
    columnas = {}
    for nombre in filas[0]:
        if nombre != "AFP":
            clave = next((nueva for palabra, nueva in _CLAVES_COMISION if palabra in catalogo.sin_tildes(nombre)),
                         nombre)
            columnas[clave] = nombre
    renombradas = [{"afp": f["AFP"], **{c: f.get(n) for c, n in columnas.items()}} for f in filas]
    return {**cabecera, "unidad": "porcentaje", "columnas": columnas,
            "afp": [f for f in renombradas if not f["afp"].lower().startswith("promedio")],
            "promedios": [f for f in renombradas if f["afp"].lower().startswith("promedio")]}


@mcp.tool(annotations=SOLO_LECTURA)
def afp_valor_cuota(fondo: int, desde: str, hasta: str | None = None, afp: str | None = None) -> dict:
    """Valor cuota diario (en soles) de cada AFP para un fondo, y su variación % entre la primera y la última fecha.

    Úsenla para «¿cuánto vale la cuota del fondo 2 de Integra?» o «¿cuánto rindió el fondo 1 en setiembre?».
    fondo: 0, 1, 2 o 3. desde y hasta: "AAAA-MM-DD" (sin hasta, solo ese día; si no fue hábil, el anterior).
    afp: "Habitat", "Integra", "Prima" o "Profuturo"; por defecto todas. Para rangos de más de tres meses solo
    baja el primer y el último mes. La SBS publica cada mes unas dos semanas después de que termina.
    """
    if fondo not in (0, 1, 2, 3):
        raise ToolError("fondo debe ser 0, 1, 2 o 3.")
    inicio = _fecha(desde)
    fin = _fecha(hasta) if hasta else inicio
    inicio, fin = min(inicio, fin), max(inicio, fin)
    meses = _meses(inicio, fin)
    if len(meses) > 3:
        meses = [meses[0], meses[-1]]

    filas, fuentes = [], []
    for periodo in meses:
        hojas, cabecera = _boletin("FP-1359", periodo)
        fuentes.append(cabecera["fuente"])
        hoja = hojas.get(f"VC-Diario-Fondo{fondo}")
        if hoja is None:
            raise ToolError(f"{cabecera['fuente']} no trae la hoja del fondo {fondo}.")
        filas += [{"fecha": f["Día"], **{k: v for k, v in f.items() if k != "Día"}}
                  for f in parsers.tabla(hoja, "Día")]
    datos = [f for f in filas if inicio.isoformat() <= f["fecha"] <= fin.isoformat()] or \
        [f for f in filas if f["fecha"] <= fin.isoformat()][-1:]
    if not datos:
        raise ToolError(f"No hay valor cuota del fondo {fondo} entre {inicio} y {fin}.")
    if afp:
        nombre = next((k for k in datos[0] if catalogo.sin_tildes(k).startswith(catalogo.sin_tildes(afp))), None)
        if nombre is None:
            raise ToolError(f"AFP {afp!r} no encontrada; hay: {', '.join(k for k in datos[0] if k != 'fecha')}.")
        datos = [{"fecha": d["fecha"], nombre: d.get(nombre)} for d in datos]
    variacion = {k: round((datos[-1][k] / datos[0][k] - 1) * 100, 4) for k in datos[0]
                 if k != "fecha" and len(datos) > 1 and datos[0].get(k) and datos[-1].get(k)}
    return {"codigo": "FP-1359", "fondo": fondo, "unidad": "soles por cuota", "fuentes": fuentes, "datos": datos,
            "variacion_pct": variacion,
            "cita": f"Fuente: SBS, Valor Cuota Diario del Fondo de Pensiones Tipo {fondo} por AFP (FP-1359)."}


@mcp.tool(annotations=SOLO_LECTURA)
def afp_rentabilidad(fondo: int, tipo: str = "anualizada", plazo: str | None = None,
                     periodo: str | None = None) -> dict:
    """Rentabilidad nominal y real (%) de cada AFP para un fondo, a 1, 2, 3... años, según la SBS.

    Úsenla para «¿qué AFP rindió más en el fondo 2?» o «rentabilidad real a 10 años del fondo 3». fondo: 0, 1, 2
    o 3. tipo: "anualizada" (por año, para comparar plazos) o "acumulada" (total del periodo). plazo: "1 año",
    "5 años"...; por defecto todos. periodo: "AAAA-MM"; por defecto el último publicado.
    """
    codigo = catalogo.RENTABILIDAD.get(fondo)
    if codigo is None:
        raise ToolError("fondo debe ser 0, 1, 2 o 3.")
    tipo = catalogo.sin_tildes(tipo)
    if tipo not in ("anualizada", "acumulada"):
        raise ToolError("tipo debe ser 'anualizada' o 'acumulada'.")
    hojas, cabecera = _boletin(codigo, periodo)
    filas = [f for f in parsers.rentabilidades(_primera(hojas)) if f["tipo"] == tipo]
    if plazo:
        anios = re.search(r"\d+", plazo)
        if not anios:
            raise ToolError(f"Plazo {plazo!r} no válido: usen '1 año', '5 años'...")
        filas = [f for f in filas if re.match(rf"{anios[0]}\b", f["plazo"] or "")]
    if not filas:
        raise ToolError(f"No encontré rentabilidad {tipo} del fondo {fondo} para ese plazo en {cabecera['fuente']}.")
    return {**cabecera, "fondo": fondo, "tipo": tipo, "unidad": "porcentaje",
            "rentabilidad": [{k: v for k, v in f.items() if k != "tipo"} for f in filas]}


@mcp.tool(annotations=SOLO_LECTURA)
def seguros_ranking(ramo: str | None = None, periodo: str | None = None, limite: int = 10) -> dict:
    """Ranking de aseguradoras por primas netas (miles de soles) y participación de mercado (%).

    Úsenla para «¿cuál es la aseguradora más grande?» o «¿quién vende más SOAT?». ramo: por defecto el total;
    también "ramos generales", "ramos de vida" o un riesgo como "soat", "vehiculos", "asistencia medica",
    "incendio", "terremoto", "vida individual", "vida en grupo", "renta de jubilacion" o "previsionales".
    periodo: "AAAA-MM" (acumulado del año a ese mes); por defecto el último publicado.
    """
    return _ranking(["S-342", "S-343", "S-344"], ramo or "total primas", periodo, limite, escala=0.001)


@mcp.tool(annotations=SOLO_LECTURA)
def seguros_indicadores(indicador: str | None = None, periodo: str | None = None) -> dict:
    """Indicadores oficiales de cada aseguradora: solvencia, siniestralidad, rentabilidad, liquidez y gestión.

    Úsenla para «¿qué aseguradora tiene mayor ROE?» o «siniestralidad de Rímac». indicador: "roe", "roa",
    "siniestralidad", "liquidez", una sección como "solvencia" o palabras del nombre oficial; sin indicador
    devuelve la lista disponible. periodo: "AAAA-MM"; por defecto el último publicado.
    """
    return _indicadores("S-302", indicador, periodo)


@mcp.tool(annotations=SOLO_LECTURA)
def reporte(codigo: str, periodo: str | None = None, hoja: str | None = None, filtro: str | None = None,
            limite: int = 40) -> dict:
    """Lee cualquier boletín de la SBS fila por fila, con la columna (A, B, C...) de cada celda.

    Úsenla cuando ninguna otra herramienta tiene el dato: balances (B-2201), liquidez (B-2340), afiliados AFP
    (FP-1201) u otro código de listar_reportes. filtro: palabras que debe tener la fila, por ejemplo "disponible"
    o "BBVA". hoja: nombre de la hoja; por defecto la primera (la respuesta trae la lista). Los valores son los
    guardados en cada celda: algunos boletines los muestran en miles con el formato del Excel, revisen el título.
    """
    hojas, cabecera = _boletin(codigo, periodo)
    if hoja is not None and hoja not in hojas:
        raise ToolError(f"La hoja {hoja!r} no existe; hay: {', '.join(hojas)}.")
    nombre = hoja or next(iter(hojas))
    df = hojas[nombre]
    buscado = catalogo.sin_tildes(filtro) if filtro else None
    filas = []
    for r in range(len(df)):
        celdas = {get_column_letter(c + 1): v for c in range(df.shape[1])
                  if (v := parsers.valor(df.iat[r, c])) is not None}
        if celdas and (not buscado or buscado in catalogo.sin_tildes(" ".join(map(str, celdas.values())))):
            filas.append({"fila": r + 1, "celdas": celdas})
    return {**cabecera, "hojas": list(hojas), "hoja": nombre, "filas_encontradas": len(filas),
            "filas": filas[:limite]}


# ---------------------------------------------------------------- recurso y prompts

@mcp.resource("sbs://reporte/{codigo}", annotations={"readOnlyHint": True})
def ficha_reporte(codigo: str) -> str:
    """Ficha de un boletín de la SBS: título, sector, último mes publicado, su URL y el patrón de URL."""
    f = catalogo.ficha(codigo)
    patron = f"{fuente.BASE}/{{AAAA}}/{{Mes}}/{f['codigo']}-{{mm}}{{AAAA}}.{f['extension']}"
    return json.dumps({**f, **fuente.ultimo_periodo(f["codigo"], f["extension"]), "patron_url": patron},
                      ensure_ascii=False)


@mcp.prompt
def comparar_entidades(tipo_entidad: str = "bancos") -> str:
    """Informe comparativo de bancos, financieras o cajas con los indicadores oficiales de la SBS."""
    return (f"Compara las entidades del tipo «{tipo_entidad}» con los boletines de la SBS del último mes publicado. "
            "Usa ranking para créditos y depósitos, e indicadores para morosidad, ROE y solvencia. Arma una tabla "
            "con las cinco entidades más grandes y termina con cinco viñetas de conclusiones. No calcules a mano: "
            "cada cifra debe venir de una herramienta y citar el código del boletín, el periodo y la URL.")


@mcp.prompt
def comparar_afp(fondo: str = "2") -> str:
    """Comparación de las AFP: comisiones, rentabilidad y valor cuota, con fuente oficial."""
    return (f"Compara las cuatro AFP para el fondo {fondo} con los datos de la SBS: afp_comisiones, afp_rentabilidad "
            "anualizada a 1, 5 y 10 años (nominal y real) y la variación del valor cuota del último mes publicado. "
            "Presenta una tabla y explica en tres viñetas qué conviene mirar al elegir AFP. Cita el código del "
            "boletín, el periodo y la URL de cada cifra, y aclara que es información, no asesoría financiera.")


def main():
    """El comando mcp-sbs-peru que crea `uv tool install`: el servidor por stdio, igual que `uv run server.py`."""
    mcp.run()


if __name__ == "__main__":
    main()
