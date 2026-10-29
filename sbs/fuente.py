"""Los archivos de la SBS: dónde están, cómo bajarlos sin abusar del servidor y cómo leerlos.

La SBS publica sus boletines en intranet2.sbs.gob.pe/estadistica/financiera/{año}/{Mes}/{CODIGO}-{mm}{año}.XLS.
Las carpetas no se pueden listar (responden 403): las URLs se arman y el último mes publicado se busca con HEAD,
retrocediendo mes a mes. www.sbs.gob.pe les pide un desafío de JavaScript a los programas; este módulo no lo usa
ni intenta pasarlo: si la SBS responde una página web en vez de un archivo, se detiene y lo dice.
"""
import contextlib
import io
import os
import re
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
from fastmcp.exceptions import ToolError

BASE = "https://intranet2.sbs.gob.pe/estadistica/financiera"
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Setiembre", "Octubre",
         "Noviembre", "Diciembre"]
CODIGOS_MES = ["en", "fe", "ma", "ab", "my", "jn", "jl", "ag", "se", "oc", "no", "di"]
FIRMA_BIFF = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # Excel 97-2003 (.xls de verdad)
FIRMA_ZIP = b"PK\x03\x04"                           # .xlsx o .zip


def carpeta_datos(raiz=Path(__file__).parent.parent):
    """Dónde va la caché de Excel: MCP_SBS_DATOS si está definida; datos/ del repositorio si se corre desde un clon
    (git la ignora); y si está instalado con `uv tool install`, la carpeta de caché del usuario, no el paquete."""
    if os.environ.get("MCP_SBS_DATOS"):                # "~/..." y rutas relativas quedan fijas al arrancar
        return Path(os.environ["MCP_SBS_DATOS"]).expanduser().resolve()
    if (raiz / "pyproject.toml").exists():
        return raiz / "datos"
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "mcp-sbs-peru"


DATOS = carpeta_datos()
PAUSA = 1.0                                         # segundos mínimos entre dos pedidos a la SBS
TURNOS = Path(tempfile.gettempdir()) / "mcp-sbs-peru.turno"   # compartido por todos los procesos de la máquina
CLIENTE = httpx.Client(headers={"User-Agent": "mcp-sbs-peru/0.1 (servidor MCP educativo, datos publicos)"},  # ASCII
                       timeout=60, follow_redirects=False)   # una redirección (a www, por ejemplo) no se sigue

_turno = threading.Lock()          # reparte turnos entre los hilos de este proceso; TURNOS, entre procesos
_ultimo_pedido = 0.0               # en segundos de reloj (time.time), comparables entre procesos
_validados = {}                    # url -> Archivo ya revisado en esta sesión
_ultimos = {}                      # (codigo, extension) -> último periodo encontrado en esta sesión


@dataclass(frozen=True)
class Archivo:
    contenido: bytes
    url: str
    actualizado: str | None        # cabecera Last-Modified de la SBS


def olvidar():
    """Borra la memoria de la sesión (no la caché en disco): lo siguiente vuelve a preguntarle a la SBS."""
    _validados.clear()
    _ultimos.clear()


def normalizar(periodo):
    """'2026-9' -> '2026-09'. Los boletines son mensuales: el periodo es siempre año y mes."""
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", str(periodo).strip())
    if not m or not 1 <= int(m[2]) <= 12:
        raise ToolError(f"Periodo {periodo!r} no válido: usen AAAA-MM, por ejemplo 2026-08.")
    return f"{m[1]}-{int(m[2]):02d}"


def url(codigo, periodo, extension="XLS"):
    anio, mes = map(int, normalizar(periodo).split("-"))
    return f"{BASE}/{anio}/{MESES[mes - 1]}/{codigo}-{CODIGOS_MES[mes - 1]}{anio}.{extension}"


def _bloqueo(direccion):
    return ToolError(f"La SBS no entregó el archivo {direccion}: respondió una página web en vez de un Excel "
                     "(su protección contra programas). No se reintenta; prueben más tarde o ábranlo en el navegador.")


def formato(contenido, direccion="el archivo"):
    """'xlsx', 'xls' o 'zip', según los primeros bytes: la extensión de la SBS no es confiable."""
    if contenido.startswith(FIRMA_BIFF):
        return "xls"
    if contenido.startswith(FIRMA_ZIP):
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                return "xlsx" if "[Content_Types].xml" in z.namelist() else "zip"
        except zipfile.BadZipFile:
            raise ToolError(f"El archivo {direccion} llegó dañado (ZIP incompleto); vuelvan a intentarlo.") from None
    raise _bloqueo(direccion)


def leer_libro(contenido):
    """Todas las hojas como tablas crudas (sin encabezados): cada parser sabe dónde empieza su tabla."""
    tipo = formato(contenido)
    if tipo == "zip":
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            hojas = [n for n in z.namelist() if n.lower().endswith((".xls", ".xlsx"))]
            if not hojas:
                raise ToolError("El ZIP de la SBS no trae ningún Excel.")
            return leer_libro(z.read(hojas[0]))
    return pd.read_excel(io.BytesIO(contenido), sheet_name=None, header=None, engine="calamine")  # .xls y .xlsx


@contextlib.contextmanager
def _candado(espera_maxima=5.0):
    """Exclusión entre procesos con un archivo creado en modo exclusivo (solo biblioteca estándar, Windows y Unix).

    Se tiene unos milisegundos. Si quedó de un proceso que murió, se rompe a los `espera_maxima` segundos. Si no se
    puede tomar en ese tiempo (PermissionError también se reintenta: Windows lo da mientras otro proceso lo borra) o
    el disco no deja crearlo, se sigue sin él; el lock de hilos sigue valiendo dentro del proceso.
    """
    ruta = TURNOS.with_name(TURNOS.name + ".lock")
    tomado, limite = False, time.time() + espera_maxima
    while not tomado and time.time() < limite:
        try:
            os.close(os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            tomado = True
        except (FileExistsError, PermissionError):
            with contextlib.suppress(OSError):
                if time.time() - ruta.stat().st_mtime > espera_maxima:
                    ruta.unlink()
                    continue
            time.sleep(0.005)
        except OSError:
            break
    try:
        yield
    finally:
        if tomado:
            with contextlib.suppress(OSError):
                ruta.unlink()


def _reservar_turno():
    """El próximo momento libre para pedirle algo a la SBS, a PAUSA del anterior de cualquier proceso de la máquina:
    Claude Code y evaluar.py levantan un servidor por sesión, y la pausa tiene que valer para todos juntos."""
    global _ultimo_pedido
    with _turno, _candado():
        try:
            anterior = float(TURNOS.read_text())
        except (OSError, ValueError):
            anterior = 0.0
        ahora = time.time()
        limite = ahora + 60 * PAUSA        # más adelante que esto solo pasa si el reloj se atrasó: no se espera
        turno = max([ahora] + [t + PAUSA for t in (anterior, _ultimo_pedido) if t <= limite])
        with contextlib.suppress(OSError):
            TURNOS.write_text(repr(turno))
        _ultimo_pedido = turno
    return turno


def _pedir(metodo, direccion, **kwargs):
    """Un pedido a la SBS. Los locks solo reparten turnos separados por PAUSA; la espera y el pedido van fuera de
    ellos, para que una respuesta lenta no deje colgadas las demás herramientas."""
    espera = _reservar_turno() - time.time()
    if espera > 0:
        time.sleep(espera)
    try:
        return CLIENTE.request(metodo, direccion, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"No se pudo conectar con la SBS ({direccion}): {e}") from e


def _escribir(ruta, datos):
    """Escritura atómica: si el proceso se corta a la mitad, queda el archivo anterior o ninguno, nunca uno roto.

    Devuelve False si no se pudo (disco lleno, archivo abierto en Windows): la caché ayuda, pero no es requisito.
    """
    try:
        descriptor, temporal = tempfile.mkstemp(dir=ruta.parent, prefix=ruta.name, suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as f:
            f.write(datos)
        os.replace(temporal, ruta)
        return True
    except OSError:
        Path(temporal).unlink(missing_ok=True)
        return False


def descargar(codigo, periodo, extension="XLS"):
    """Baja un boletín una sola vez: lo guarda en datos/ y después solo pregunta si cambió (If-Modified-Since)."""
    periodo = normalizar(periodo)
    direccion = url(codigo, periodo, extension)
    if direccion in _validados:
        return _validados[direccion]
    archivo = DATOS / direccion.rsplit("/", 1)[1]
    marca = archivo.with_name(archivo.name + ".fecha")
    cabeceras, guardado = {}, None
    if archivo.exists() and marca.exists():
        try:                                   # la fecha antes que el archivo: si otro proceso los reescribe en el
            fecha = marca.read_text()          # medio, a lo sumo se pide de nuevo; nunca bytes viejos con fecha nueva
            guardado = archivo.read_bytes()
            formato(guardado)                  # una caché dañada no se revalida: se vuelve a bajar completa
            cabeceras["If-Modified-Since"] = fecha
        except (OSError, ToolError):
            guardado = None

    r = _pedir("GET", direccion, headers=cabeceras)
    if r.status_code == 304 and cabeceras:
        resultado = Archivo(guardado, direccion, cabeceras["If-Modified-Since"])
    elif r.status_code == 404:
        raise ToolError(f"La SBS aún no publica {codigo} de {periodo} ({direccion}). "
                        "Prueben un mes anterior o pregunten con ultimo_periodo.")
    elif r.status_code != 200:
        raise ToolError(f"La SBS respondió {r.status_code} al pedir {direccion}.")
    else:
        formato(r.content, direccion)      # una página de bloqueo se rechaza antes de guardar nada
        with contextlib.suppress(OSError):
            DATOS.mkdir(parents=True, exist_ok=True)
            marca.unlink(missing_ok=True)      # sin fecha, la próxima vez se baja completo: nunca una fecha vieja
        actualizado = r.headers.get("Last-Modified")
        if _escribir(archivo, r.content) and actualizado:
            _escribir(marca, actualizado.encode("ascii"))
        resultado = Archivo(r.content, direccion, actualizado)
    _validados[direccion] = resultado
    return resultado


def ultimo_periodo(codigo, extension="XLS", hoy=None, meses=6):
    """El mes más reciente publicado: prueba con HEAD desde el mes actual hacia atrás, sin bajar archivos."""
    clave = (codigo, extension)
    if clave in _ultimos:
        return _ultimos[clave]
    hoy = hoy or date.today()
    anio, mes = hoy.year, hoy.month
    for _ in range(meses):
        periodo = f"{anio}-{mes:02d}"
        direccion = url(codigo, periodo, extension)
        r = _pedir("HEAD", direccion)
        if r.status_code == 200:
            if "html" in r.headers.get("Content-Type", ""):
                raise _bloqueo(direccion)
            _ultimos[clave] = {"codigo": codigo, "periodo": periodo,
                               "actualizado": r.headers.get("Last-Modified"), "url": direccion}
            return _ultimos[clave]
        if r.status_code != 404:               # intranet2 responde 404 a los meses sin publicar (visto el
            # 2026-10-28 con B-, C-, S- y FP-); cualquier otro estado es un problema que no se adivina
            raise ToolError(f"La SBS respondió {r.status_code} al buscar el último mes de {codigo} ({direccion}). "
                            "Prueben en unos minutos o pidan un periodo explícito.")
        anio, mes = (anio, mes - 1) if mes > 1 else (anio - 1, 12)
    raise ToolError(f"No encontré {codigo} publicado en los últimos {meses} meses. "
                    "Revisen el código con listar_reportes.")
