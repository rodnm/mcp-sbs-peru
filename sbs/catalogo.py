"""Los boletines que este servidor conoce, con el título oficial copiado del propio Excel.

Lo que va entre paréntesis es una aclaración nuestra. La SBS publica cientos de boletines; aquí están los que usan
las herramientas y algunos más útiles. La herramienta `reporte` acepta cualquier otro código con el mismo formato
(por ejemplo B-2315 o FP-1354).
"""
import re
import unicodedata

from fastmcp.exceptions import ToolError

# codigo: (sector, título oficial)
REPORTES = {
    "B-2201": ("bancos", "Balance General por Empresa Bancaria"),
    "B-2332": ("bancos", "Ranking de Créditos, Depósitos y Patrimonio (bancos)"),
    "B-2333": ("bancos", "Ranking de Créditos Directos por Tipo de Crédito"),
    "B-2334": ("bancos", "Créditos Directos según Tipo de Crédito y Situación"),
    "B-2340": ("bancos", "Ratios de Liquidez en Moneda Nacional y Moneda Extranjera por Empresa Bancaria"),
    "B-2362": ("bancos", "Morosidad según tipo y modalidad de crédito por Empresa Bancaria"),
    "B-2401": ("bancos", "Indicadores Financieros por Empresa Bancaria"),
    "B-2402": ("bancos", "Requerimiento de Patrimonio Efectivo y Ratio de Capital Global por Empresa Bancaria"),
    "B-3243": ("financieras", "Ranking de Créditos, Depósitos y Patrimonio (financieras)"),
    "B-3301": ("financieras", "Indicadores Financieros por Empresa Financiera"),
    "C-1205": ("cajas municipales", "Ranking de Créditos, Depósitos y Patrimonio de las Cajas Municipales"),
    "C-1301": ("cajas municipales", "Indicadores Financieros por Caja Municipal"),
    "C-2205": ("cajas rurales", "Ranking de Créditos, Depósitos y Patrimonio de las Cajas Rurales"),
    "C-2301": ("cajas rurales", "Indicadores Financieros por Caja Rural de Ahorro y Crédito"),
    "C-4301": ("empresas de creditos", "Indicadores Financieros por Empresa de Créditos"),
    "FP-1201": ("afp", "Número de Afiliados Activos por AFP, Sexo y Edad Actual"),
    "FP-1232": ("afp", "Esquema de Comisión sobre Saldo Administrado (comisión, prima de seguro y tasa de aporte)"),
    "FP-1359": ("afp", "Valor Cuota Diario del Fondo de Pensiones por AFP (una hoja por fondo, del 0 al 3)"),
    "FP-1219-0": ("afp", "Rentabilidad Nominal y Real Acumulada del Fondo de Pensiones Tipo 0 por AFP (y anualizada)"),
    "FP-1220-1": ("afp", "Rentabilidad Nominal y Real Acumulada del Fondo de Pensiones Tipo 1 por AFP (y anualizada)"),
    "FP-1360": ("afp", "Rentabilidad Nominal y Real Acumulada del Fondo de Pensiones Tipo 2 por AFP (y anualizada)"),
    "FP-1220-2": ("afp", "Rentabilidad Nominal y Real Acumulada del Fondo de Pensiones Tipo 3 por AFP (y anualizada)"),
    "S-203": ("seguros", "Estado de Situación Financiera por Empresa de Seguros"),
    "S-302": ("seguros", "Indicadores por Empresas de Seguros"),
    "S-342": ("seguros", "Ranking de Primas de Seguros Netas por Ramos"),
    "S-343": ("seguros", "Ranking de Primas de Seguros Netas de los principales Riesgos de Ramos Generales y "
                         "Accidentes y Enfermedades"),
    "S-344": ("seguros", "Ranking de Primas de Seguros Netas de los principales Riesgos de Ramos de Vida"),
}
EXTENSIONES = {"SF-2101": "ZIP"}                       # el resto son .XLS (aunque por dentro sean .xlsx)
ESCALAS = {"S-342": 0.001, "S-343": 0.001, "S-344": 0.001}   # celdas en soles que el Excel muestra en miles

# tipo de entidad -> (boletín de indicadores, boletín de ranking)
TIPOS = {
    "bancos": ("B-2401", "B-2332"),
    "financieras": ("B-3301", "B-3243"),
    "cajas municipales": ("C-1301", "C-1205"),
    "cajas rurales": ("C-2301", "C-2205"),
    "empresas de creditos": ("C-4301", None),
}
_ALIAS_TIPO = {"banca": "bancos", "banco": "bancos", "cmac": "cajas municipales", "caja municipal": "cajas municipales",
               "crac": "cajas rurales", "caja rural": "cajas rurales", "edpyme": "empresas de creditos",
               "edpymes": "empresas de creditos", "financiera": "financieras"}
RENTABILIDAD = {0: "FP-1219-0", 1: "FP-1220-1", 2: "FP-1360", 3: "FP-1220-2"}

_CODIGO = re.compile(r"[A-Z]{1,3}-\d{3,6}(-\d)?")


def sin_tildes(s):
    return unicodedata.normalize("NFD", str(s).lower()).encode("ascii", "ignore").decode().strip()


def validar_codigo(codigo):
    codigo = str(codigo).strip().upper()
    if not _CODIGO.fullmatch(codigo):
        raise ToolError(f"El código de boletín {codigo!r} no es válido: tiene la forma B-2401, C-1301, FP-1232 "
                        "o S-302. Búsquenlo con listar_reportes.")
    return codigo


def ficha(codigo):
    codigo = validar_codigo(codigo)
    sector, titulo = REPORTES.get(codigo, (None, None))
    return {"codigo": codigo, "sector": sector, "titulo": titulo, "extension": EXTENSIONES.get(codigo, "XLS")}


def buscar(sector=None, texto=None):
    salida = []
    for codigo, (sec, titulo) in REPORTES.items():
        if sector and sin_tildes(sector).rstrip("s") not in sec:
            continue
        if texto and not all(p in sin_tildes(f"{codigo} {titulo}") for p in sin_tildes(texto).split()):
            continue
        salida.append({"codigo": codigo, "sector": sec, "titulo": titulo})
    return salida


def tipo_entidad(texto):
    t = sin_tildes(texto)
    t = _ALIAS_TIPO.get(t, t)
    if t in TIPOS:
        return t
    opciones = [k for k in TIPOS if k.startswith(t) or t.startswith(k)]
    if len(opciones) == 1:
        return opciones[0]
    raise ToolError(f"Tipo de entidad {texto!r} no reconocido. Usen uno de: {', '.join(TIPOS)}.")
