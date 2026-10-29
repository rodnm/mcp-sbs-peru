"""Pruebas sin red de sbs/fuente.py: URLs, formatos, caché, bloqueos y el último periodo publicado.

    uv run pytest -q test_fuente.py

Un servidor falso (httpx.MockTransport) hace de intranet2, así que corren igual sin internet.
"""
import io
import time
import zipfile
from datetime import date

import httpx
import openpyxl
import pytest
from fastmcp.exceptions import ToolError

from sbs import fuente

BIFF = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504
INCAPSULA = (b'<html>\n<head>\n<META NAME="robots" CONTENT="noindex,nofollow">\n'
             b'<script src="/_Incapsula_Resource?SWJIYLWA=x">\n</script>\n<body>\n</body></html>')


def _xlsx(filas):
    libro = openpyxl.Workbook()
    for fila in filas:
        libro.active.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


@pytest.fixture(autouse=True)
def aislado(monkeypatch, tmp_path):
    monkeypatch.setattr(fuente, "DATOS", tmp_path)
    monkeypatch.setattr(fuente, "PAUSA", 0)
    fuente.olvidar()


def _servidor(monkeypatch, responder):
    """Cambia el cliente HTTP por uno falso; devuelve la lista de pedidos que recibió."""
    pedidos = []

    def manejar(pedido):
        pedidos.append(pedido)
        return responder(pedido)

    monkeypatch.setattr(fuente, "CLIENTE", httpx.Client(transport=httpx.MockTransport(manejar)))
    return pedidos


def test_url_usa_setiembre_y_el_codigo_de_mes():
    assert fuente.url("B-2201", "2026-09") == \
        "https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Setiembre/B-2201-se2026.XLS"
    assert fuente.url("SF-2101", "2026-1", "ZIP") == \
        "https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Enero/SF-2101-en2026.ZIP"


@pytest.mark.parametrize("periodo", ["2026", "setiembre", "2026-13", "26-09"])
def test_periodo_mal_escrito_da_un_error_claro(periodo):
    with pytest.raises(ToolError, match="AAAA-MM"):
        fuente.url("B-2201", periodo)


def test_formato_se_decide_por_los_primeros_bytes():
    assert fuente.formato(_xlsx([["a"]])) == "xlsx"
    assert fuente.formato(BIFF) == "xls"
    zipeado = io.BytesIO()
    with zipfile.ZipFile(zipeado, "w") as z:
        z.writestr("SF-2101.xls", BIFF)
    assert fuente.formato(zipeado.getvalue()) == "zip"
    with pytest.raises(ToolError, match="no entregó"):
        fuente.formato(INCAPSULA)


def test_leer_libro_devuelve_cada_hoja_sin_encabezados():
    hojas = fuente.leer_libro(_xlsx([["Banco", "Morosidad"], ["BCP", 3.1]]))
    tabla = next(iter(hojas.values()))
    assert tabla.iloc[1, 0] == "BCP" and tabla.iloc[1, 1] == 3.1


def test_la_pagina_de_incapsula_se_rechaza_sin_reintentar_ni_guardar(monkeypatch, tmp_path):
    pedidos = _servidor(monkeypatch, lambda p: httpx.Response(200, content=INCAPSULA,
                                                             headers={"Content-Type": "text/html"}))
    with pytest.raises(ToolError, match="no entregó"):
        fuente.descargar("B-2201", "2026-09")
    assert len(pedidos) == 1
    assert list(tmp_path.iterdir()) == []


def test_un_mes_sin_publicar_lo_dice(monkeypatch):
    _servidor(monkeypatch, lambda p: httpx.Response(404))
    with pytest.raises(ToolError, match="aún no publica B-2201 de 2026-10"):
        fuente.descargar("B-2201", "2026-10")


def test_la_descarga_queda_en_cache_y_se_revalida(monkeypatch):
    contenido = _xlsx([["x"]])
    fecha = "Wed, 28 Oct 2026 10:00:00 GMT"

    def responder(pedido):
        if pedido.headers.get("If-Modified-Since") == fecha:
            return httpx.Response(304)
        return httpx.Response(200, content=contenido, headers={"Last-Modified": fecha})

    pedidos = _servidor(monkeypatch, responder)
    primero = fuente.descargar("B-2201", "2026-09")
    assert primero.contenido == contenido and primero.actualizado == fecha
    assert primero.url.endswith("/2026/Setiembre/B-2201-se2026.XLS")

    fuente.descargar("B-2201", "2026-09")            # en la misma sesión: ni siquiera pregunta
    assert len(pedidos) == 1

    fuente.olvidar()                                  # otra sesión: revalida con If-Modified-Since
    tercero = fuente.descargar("B-2201", "2026-09")
    assert len(pedidos) == 2 and pedidos[1].headers["If-Modified-Since"] == fecha
    assert tercero.contenido == contenido


def test_ultimo_periodo_retrocede_hasta_encontrar_el_archivo(monkeypatch):
    def responder(pedido):
        if "/2026/Setiembre/" in str(pedido.url):
            return httpx.Response(200, headers={"Last-Modified": "Tue, 27 Oct 2026 20:00:00 GMT",
                                                "Content-Type": "application/vnd.ms-excel"})
        return httpx.Response(404)

    pedidos = _servidor(monkeypatch, responder)
    r = fuente.ultimo_periodo("B-2201", hoy=date(2026, 10, 28))
    assert r["periodo"] == "2026-09"
    assert r["actualizado"] == "Tue, 27 Oct 2026 20:00:00 GMT"
    assert [p.method for p in pedidos] == ["HEAD", "HEAD"]


def test_ultimo_periodo_se_rinde_con_un_error_claro(monkeypatch):
    _servidor(monkeypatch, lambda p: httpx.Response(404))
    with pytest.raises(ToolError, match="B-9999"):
        fuente.ultimo_periodo("B-9999", hoy=date(2026, 10, 28))


def test_ultimo_periodo_no_confunde_un_error_con_un_mes_sin_publicar(monkeypatch):
    estado = {"codigo": 503}
    _servidor(monkeypatch, lambda p: httpx.Response(estado["codigo"]) if "/Octubre/" in str(p.url)
              else httpx.Response(200, headers={"Content-Type": "application/vnd.ms-excel"}))
    with pytest.raises(ToolError, match="503"):
        fuente.ultimo_periodo("B-2201", hoy=date(2026, 10, 28))
    estado["codigo"] = 200                                # el error no quedó guardado como respuesta
    assert fuente.ultimo_periodo("B-2201", hoy=date(2026, 10, 28))["periodo"] == "2026-10"


def test_un_zip_roto_da_un_error_claro():
    with pytest.raises(ToolError, match="dañado"):
        fuente.formato(b"PK\x03\x04 cortado a la mitad")


def test_una_cache_danada_se_vuelve_a_bajar_completa(monkeypatch, tmp_path):
    (tmp_path / "B-2201-se2026.XLS").write_bytes(b"PK\x03\x04 cortado")
    (tmp_path / "B-2201-se2026.XLS.fecha").write_text("Wed, 28 Oct 2026 10:00:00 GMT")
    bueno = _xlsx([["ok"]])
    pedidos = _servidor(monkeypatch, lambda p: httpx.Response(200, content=bueno))
    assert fuente.descargar("B-2201", "2026-09").contenido == bueno
    assert "If-Modified-Since" not in pedidos[0].headers


def test_una_descarga_sin_fecha_borra_la_fecha_vieja(monkeypatch, tmp_path):
    respuestas = [httpx.Response(200, content=BIFF, headers={"Last-Modified": "Wed, 28 Oct 2026 10:00:00 GMT"}),
                  httpx.Response(200, content=BIFF + b"v2")]
    _servidor(monkeypatch, lambda p: respuestas.pop(0))
    fuente.descargar("C-1101", "2026-08")
    fuente.olvidar()
    fuente.descargar("C-1101", "2026-08")
    assert not (tmp_path / "C-1101-ag2026.XLS.fecha").exists()
    assert (tmp_path / "C-1101-ag2026.XLS").read_bytes() == BIFF + b"v2"


def test_si_la_cache_no_se_puede_guardar_igual_responde_y_no_deja_temporales(monkeypatch, tmp_path):
    _servidor(monkeypatch, lambda p: httpx.Response(200, content=BIFF))

    def disco_ocupado(*args):
        raise PermissionError("archivo abierto por otro proceso")

    monkeypatch.setattr(fuente.os, "replace", disco_ocupado)
    assert fuente.descargar("C-1101", "2026-08").contenido == BIFF
    assert list(tmp_path.iterdir()) == []


def test_en_paralelo_los_pedidos_empiezan_separados_pero_no_se_esperan(monkeypatch):
    import threading
    monkeypatch.setattr(fuente, "PAUSA", 0.2)
    inicios = []

    def lento(pedido):
        inicios.append(time.monotonic())
        time.sleep(0.5)
        return httpx.Response(200, content=BIFF)

    _servidor(monkeypatch, lento)
    hilos = [threading.Thread(target=fuente.descargar, args=("C-1101", p)) for p in ("2026-07", "2026-08")]
    inicio = time.monotonic()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert abs(inicios[1] - inicios[0]) >= 0.18          # nunca dos pedidos a la vez sin pausa
    assert time.monotonic() - inicio < 1.0               # pero el segundo no espera a que termine el primero


def test_entre_pedidos_hay_una_pausa(monkeypatch):
    monkeypatch.setattr(fuente, "PAUSA", 0.3)
    _servidor(monkeypatch, lambda p: httpx.Response(200, content=BIFF))
    inicio = time.monotonic()
    fuente.descargar("C-1101", "2026-08")
    fuente.descargar("C-1101", "2026-07")
    assert time.monotonic() - inicio >= 0.25
