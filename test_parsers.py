"""Pruebas sin red de sbs/parsers.py con tablas pequeñas que copian la forma de los Excel de la SBS.

    uv run pytest -q test_parsers.py
"""
import pandas as pd

from sbs import parsers

n = None


def test_limpiar_quita_saltos_asteriscos_y_notas():
    assert parsers.limpiar("CMAC\n Arequipa") == "CMAC Arequipa"
    assert parsers.limpiar("B. Efectiva****") == "B. Efectiva"
    assert parsers.limpiar("CMAC Piura 1/") == "CMAC Piura"
    assert parsers.limpiar("Indice Combinado (%) (Plan de Cuentas desde Mar26) 7/ 8/") == \
        "Indice Combinado (%) (Plan de Cuentas desde Mar26)"
    assert parsers.limpiar("Ratio de Capital Global (al 31/07/2026)") == "Ratio de Capital Global (al 31/07/2026)"


def test_indicadores_con_dos_bloques_lado_a_lado():
    # como B-2401: la columna de etiquetas se repite a mitad de la hoja
    df = pd.DataFrame([
        ["Indicadores Financieros por Empresa Bancaria", n, n, "Indicadores Financieros por Empresa Bancaria", n, n],
        [n, "B. BBVA Perú", "B. Efectiva****", n, "CMAC\n Piura 1/", "Total Banca Múltiple"],
        ["SOLVENCIA", n, n, "SOLVENCIA", n, n],
        ["Ratio de Capital Global", 15.87, 21.37, "Ratio de Capital Global", 20.6, 17.12],
        ["CALIDAD DE ACTIVOS *", n, n, "CALIDAD DE ACTIVOS *", n, n],
        ["Créditos Atrasados (criterio SBS)* / Créditos Directos", 2.72, 3.4,
         "Créditos Atrasados (criterio SBS)* / Créditos Directos", 3.85, 2.82],
        ["Nota: La definición de los indicadores está en el glosario.", n, n, n, n, n],
    ])
    filas = parsers.indicadores_por_entidad(df)
    assert len(filas) == 8
    assert {"entidad": "B. Efectiva", "seccion": "CALIDAD DE ACTIVOS",
            "indicador": "Créditos Atrasados (criterio SBS) / Créditos Directos", "valor": 3.4} in filas
    assert {"entidad": "CMAC Piura", "seccion": "SOLVENCIA", "indicador": "Ratio de Capital Global",
            "valor": 20.6} in filas


def test_indicadores_con_secciones_en_otra_columna():
    # como S-302: secciones en la columna 0, indicadores en la 1 y filas sin datos que no son secciones
    df = pd.DataFrame([
        ["Indicadores por Empresas de Seguros 1/", n, n, n],
        ["Indicadores / Empresas", n, "Rímac", "Avla Perú 5/"],
        ["DE SOLVENCIA  (N° de veces)", n, n, n],
        [n, "Patrimonio Efectivo / Requerimientos Patrimoniales", n, n],
        [n, "Pasivo Total / Patrimonio Contable ", 0.69, 3.11],
        ["DE RENTABILIDAD  (%)", n, n, n],
        [n, "ROE", 21.5, -3.2],
    ])
    filas = parsers.indicadores_por_entidad(df)
    assert filas == [
        {"entidad": "Rímac", "seccion": "DE SOLVENCIA (N° de veces)", "indicador": "Pasivo Total / Patrimonio Contable",
         "valor": 0.69},
        {"entidad": "Avla Perú", "seccion": "DE SOLVENCIA (N° de veces)",
         "indicador": "Pasivo Total / Patrimonio Contable", "valor": 3.11},
        {"entidad": "Rímac", "seccion": "DE RENTABILIDAD (%)", "indicador": "ROE", "valor": 21.5},
        {"entidad": "Avla Perú", "seccion": "DE RENTABILIDAD (%)", "indicador": "ROE", "valor": -3.2},
    ]


def test_rankings_apilados_y_lado_a_lado():
    # como B-2333: dos bloques por fila; el título puede estar una columna antes o después de "Empresas"
    df = pd.DataFrame([
        ["Ranking de Créditos Directos por Tipo de Crédito", n, n, n, n, n, n, n, n, n, n],
        ["Créditos Corporativos", n, n, n, n, n, n, n, "Créditos a Medianas Empresas", n, n],
        ["Empresas", n, "Monto", "Participación", "Acumulado", n, "Empresas", n, n, "Monto", "Part."],
        [n, n, n, n, n, n, n, n, n, n, n],
        [1, n, "B. de Crédito del Perú", 43804277.375, 37.42, n, 1, n, "Interbank", 7315162.869, 36.9],
        [2.0, n, "B. BBVA Perú", 23141908.401, 19.77, n, n, n, n, n, n],
        ["Total", n, n, 117000000.0, 100.0, n, n, n, n, n, n],
    ])
    filas = parsers.rankings(df)
    assert filas[0] == {"bloque": "Créditos Corporativos", "puesto": 1, "entidad": "B. de Crédito del Perú",
                        "monto": 43804277.375, "participacion_pct": 37.42, "acumulado_pct": None}
    assert filas[1]["puesto"] == 2 and filas[1]["entidad"] == "B. BBVA Perú"
    assert filas[2] == {"bloque": "Créditos a Medianas Empresas", "puesto": 1, "entidad": "Interbank",
                        "monto": 7315162.869, "participacion_pct": 36.9, "acumulado_pct": None}
    assert len(filas) == 3


def test_tabla_desde_su_fila_de_encabezado():
    # como FP-1232: encabezado en la fila que empieza con "AFP" y notas al pie al final
    df = pd.DataFrame([
        ["Esquema de Comisión sobre Saldo Administrado", n, n],
        ["AFP", "Comisión sobre Saldo Administrado 1/", "Prima de Seguro 2/"],
        ["Habitat", 1.25, 1.37],
        ["Integra", 0.78, 1.37],
        ["1/ La comisión por saldo se cobra sobre el fondo.", n, n],
    ])
    assert parsers.tabla(df, "AFP") == [
        {"AFP": "Habitat", "Comisión sobre Saldo Administrado": 1.25, "Prima de Seguro": 1.37},
        {"AFP": "Integra", "Comisión sobre Saldo Administrado": 0.78, "Prima de Seguro": 1.37},
    ]
