"""El contrato del servidor: si estas pruebas pasan, Claude Code y evaluar.py pueden usarlo.

    uv run pytest -q                    # todas (las marcadas live bajan los Excel reales de la SBS a datos/)
    uv run pytest -q -m "not live"      # solo las que no usan internet

Llaman al servidor en memoria, igual que lo haría Claude Code. Las cifras fijadas son las que publicó la SBS en sus
boletines de agosto (banca) y setiembre (AFP y seguros) de 2026.
"""
import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from server import mcp


async def _con_cliente(f):
    async with Client(mcp) as c:
        return await f(c)


def llamar(herramienta, **args):
    return asyncio.run(_con_cliente(lambda c: c.call_tool(herramienta, args))).data


def _valores(indicador):
    return {v["entidad"]: v["valor"] for v in indicador["valores"]}


def test_diez_herramientas_un_recurso_y_dos_prompts():
    async def contar(c):
        return ({t.name for t in await c.list_tools()}, len(await c.list_resource_templates()),
                len(await c.list_prompts()))
    herramientas, plantillas, prompts = asyncio.run(_con_cliente(contar))
    assert {"listar_reportes", "ultimo_periodo", "indicadores", "ranking", "afp_comisiones", "afp_valor_cuota",
            "afp_rentabilidad", "seguros_ranking", "seguros_indicadores", "reporte"} <= herramientas
    assert plantillas >= 1 and prompts >= 2


def test_listar_reportes_por_sector():
    codigos = [r["codigo"] for r in llamar("listar_reportes", sector="afp")]
    assert "FP-1232" in codigos and all(c.startswith("FP-") for c in codigos)


def test_un_tipo_de_entidad_desconocido_dice_cuales_hay():
    with pytest.raises(ToolError, match="cajas municipales"):
        llamar("indicadores", tipo_entidad="cooperativas", indicador="morosidad")


@pytest.mark.parametrize("codigo", ["../B-2201", "B-２４０１"])   # el segundo usa dígitos de ancho completo
def test_un_codigo_raro_no_llega_a_la_url(codigo):
    with pytest.raises(ToolError, match="código"):
        llamar("reporte", codigo=codigo, periodo="2026-08")


@pytest.mark.live
def test_morosidad_de_los_bancos():
    r = llamar("indicadores", tipo_entidad="bancos", indicador="morosidad", periodo="2026-08")
    assert r["codigo"] == "B-2401" and r["fuente"].endswith("/2026/Agosto/B-2401-ag2026.XLS")
    ind = r["indicadores"][0]
    assert ind["indicador"] == "Créditos Atrasados (criterio SBS) / Créditos Directos"
    assert _valores(ind)["B. BBVA Perú"] == pytest.approx(2.72)
    assert ind["total"]["valor"] == pytest.approx(2.82)


@pytest.mark.live
def test_sin_indicador_devuelve_el_menu():
    r = llamar("indicadores", tipo_entidad="cajas municipales", periodo="2026-08")
    assert "CMAC Arequipa" in r["entidades"]
    assert {"seccion": "RENTABILIDAD", "indicador": "Utilidad Neta Anualizada sobre Patrimonio Promedio (%)"} \
        in r["indicadores_disponibles"]


@pytest.mark.live
def test_roe_encuentra_el_nombre_de_bancos_y_de_cajas():
    # los bancos escriben "Utilidad Neta Anualizada / Patrimonio Promedio"; las cajas, "... sobre ... (%)"
    bancos = llamar("indicadores", tipo_entidad="bancos", indicador="roe", periodo="2026-08")
    cajas = llamar("indicadores", tipo_entidad="cmac", indicador="roe", periodo="2026-08")
    assert [i["indicador"] for i in bancos["indicadores"]] == ["Utilidad Neta Anualizada / Patrimonio Promedio"]
    assert [i["indicador"] for i in cajas["indicadores"]] == ["Utilidad Neta Anualizada sobre Patrimonio Promedio (%)"]


@pytest.mark.live
def test_ranking_de_creditos_y_por_tipo_de_credito():
    r = llamar("ranking", tipo_entidad="bancos", concepto="créditos", periodo="2026-08")
    primero = r["ranking"][0]
    assert primero["entidad"] == "B. de Crédito del Perú" and r["unidad"] == "miles de soles"
    assert primero["monto"] == pytest.approx(136646654.665)
    assert primero["participacion_pct"] == pytest.approx(34.178108)
    micro = llamar("ranking", tipo_entidad="bancos", concepto="microempresas", periodo="2026-08")
    assert micro["codigo"] == "B-2333" and micro["bloque"] == "Créditos a Microempresas"


@pytest.mark.live
def test_comisiones_de_las_afp():
    r = llamar("afp_comisiones", periodo="2026-09")
    por_afp = {f["afp"]: f for f in r["afp"]}
    assert por_afp["Integra"]["comision_sobre_saldo_pct"] == pytest.approx(0.78)
    assert por_afp["Habitat"]["descuento_total_pct"] == pytest.approx(11.37)


@pytest.mark.live
def test_valor_cuota_diario():
    r = llamar("afp_valor_cuota", fondo=0, desde="2026-09-01", hasta="2026-09-03")
    assert [d["fecha"] for d in r["datos"]] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert r["datos"][0]["Habitat"] == pytest.approx(16.267671)
    assert r["fuentes"][0].endswith("/2026/Setiembre/FP-1359-se2026.XLS")


@pytest.mark.live
def test_rentabilidad_del_fondo_2():
    r = llamar("afp_rentabilidad", fondo=2, tipo="acumulada", periodo="2026-09")
    habitat = next(x for x in r["rentabilidad"] if x["afp"] == "Habitat" and x["plazo"] == "1 año")
    assert habitat["nominal_pct"] == pytest.approx(18.8747) and habitat["real_pct"] == pytest.approx(13.7027)


@pytest.mark.live
def test_ranking_de_seguros_en_miles_de_soles():
    r = llamar("seguros_ranking", periodo="2026-09")
    assert r["ranking"][0]["entidad"] == "Rímac" and r["unidad"] == "miles de soles"
    assert r["ranking"][0]["monto"] == pytest.approx(5139080.56764)
    soat = llamar("seguros_ranking", ramo="soat", periodo="2026-09")
    assert soat["codigo"] == "S-343" and soat["bloque"] == "SOAT"


@pytest.mark.live
def test_roe_de_las_aseguradoras():
    r = llamar("seguros_indicadores", indicador="roe", periodo="2026-09")
    assert r["indicadores"][0]["indicador"] == "ROE" and "Rímac" in _valores(r["indicadores"][0])


@pytest.mark.live
def test_reporte_generico_filtra_filas():
    r = llamar("reporte", codigo="B-2201", periodo="2026-08", filtro="disponible")
    assert r["filas"] and all("DISPONIBLE" in " ".join(map(str, f["celdas"].values())).upper() for f in r["filas"])
