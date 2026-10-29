# mcp-sbs-peru

Un servidor MCP para que Claude responda con las cifras oficiales de la **Superintendencia de Banca, Seguros y AFP
del Perú (SBS)**: morosidad y solvencia de bancos y cajas, participación de mercado, comisiones y rentabilidad de las
AFP, y ranking de aseguradoras. Cada respuesta cita el boletín, el periodo y la URL del Excel de la SBS, así que
cualquiera puede comprobarla.

> Ejemplos: «¿Qué banco tiene la menor morosidad?», «¿Qué AFP cobra menos comisión?», «¿Quién vende más SOAT?»,
> «ROE de las cajas municipales en agosto de 2026».

## ¿Sirve? El resultado en un gráfico

![Aciertos de Claude Haiku en 10 preguntas sobre cifras oficiales de la SBS: solo memoria 0 de 10, búsqueda web 2 de 10, MCP de la SBS 10 de 10](grafico.png)

Le hicimos a Claude (modelo Haiku) 10 preguntas con respuesta oficial conocida, sacada de los Excel de la SBS:

- **Sin herramientas**, solo con lo que aprendió al entrenarse, acertó **0 de 10**. Las 10 veces dijo que no sabía.
- **Buscando en internet** acertó **2 de 10**: las dos cifras de AFP que repiten las noticias.
- **Con este MCP** acertó **10 de 10**, y cada respuesta trae el link del Excel de la SBS de donde salió.

El detalle de cada pregunta y por qué falló cada modo está en [`informe.md`](informe.md).

## Instalar

Necesitan [uv](https://docs.astral.sh/uv/) y [Claude Code](https://claude.com/claude-code). Dos comandos, sin clonar
nada:

```bash
uv tool install git+https://github.com/rodnm/mcp-sbs-peru     # instala el comando mcp-sbs-peru
claude mcp add --scope user sbs -- mcp-sbs-peru               # lo conecta a Claude Code en todos sus proyectos
```

Abran `claude` en cualquier carpeta: `/mcp` debe mostrar `sbs` conectado. Si la terminal no encuentra el comando
`mcp-sbs-peru`, corran una vez `uv tool update-shell` y abran una terminal nueva. Los Excel que baja quedan en la caché de su
usuario (`%LOCALAPPDATA%\mcp-sbs-peru` en Windows, `~/.cache/mcp-sbs-peru` en Linux y macOS). Pueden cambiar la
carpeta con la variable `MCP_SBS_DATOS`.

| Para | Comando |
|---|---|
| Actualizar a lo último | `uv tool upgrade mcp-sbs-peru` y reiniciar Claude Code (los MCP arrancan con la sesión) |
| Fijar una versión | `uv tool install git+https://github.com/rodnm/mcp-sbs-peru@v0.1.0` (cambien el número para pasar a otra). Con una versión fijada, `upgrade` no la mueve: para volver a lo último, repitan el `uv tool install` sin `@...` |
| Desinstalar | `claude mcp remove --scope user sbs` y `uv tool uninstall mcp-sbs-peru` |

## Desde el código (para el curso o para colaborar)

```bash
git clone https://github.com/rodnm/mcp-sbs-peru
cd mcp-sbs-peru
uv run pytest -q -m "not live"     # pruebas sin internet: deben pasar todas
claude                             # acepten los servidores de .mcp.json (sbs y fetch)
```

Dentro del repositorio, `.mcp.json` ya conecta `sbs` (corriendo `uv run server.py`) y `fetch`. Para actualizar esta
copia: `git pull`.

## Qué trae

| Herramienta | Para qué |
|---|---|
| `indicadores` | Morosidad, ROE, ROA, solvencia, liquidez y eficiencia de bancos, financieras, cajas municipales, cajas rurales y empresas de créditos |
| `ranking` | Créditos, depósitos o patrimonio por entidad, con participación de mercado; para bancos, también por tipo de crédito |
| `afp_comisiones` | Comisión sobre el saldo, prima de seguro, aporte y descuento total de cada AFP |
| `afp_valor_cuota` | Valor cuota diario por AFP y fondo (0 a 3), con su variación |
| `afp_rentabilidad` | Rentabilidad nominal y real, acumulada o anualizada, a 1, 2, 3… años |
| `seguros_ranking` | Primas netas por aseguradora: total, por ramo o por riesgo (SOAT, vehículos, vida…) |
| `seguros_indicadores` | Solvencia, siniestralidad, ROE, liquidez y gestión de cada aseguradora |
| `listar_reportes`, `ultimo_periodo`, `reporte` | Encontrar y leer cualquier otro boletín de la SBS, fila por fila |

| Recurso o prompt | En Claude Code |
|---|---|
| `sbs://reporte/{codigo}` | `@sbs:sbs://reporte/B-2401`: ficha del boletín y su último mes publicado |
| `comparar_entidades` | `/mcp__sbs__comparar_entidades bancos` |
| `comparar_afp` | `/mcp__sbs__comparar_afp 2` |

## De dónde salen los datos

| Tema | Detalle |
|---|---|
| Fuente | Los boletines estadísticos que la SBS publica en `intranet2.sbs.gob.pe/estadistica/financiera/{año}/{Mes}/{CÓDIGO}-{mm}{año}.XLS`. Se descargan tal cual y Python hace las cuentas |
| Rezago | Cada boletín sale después de cerrar el mes: AFP unas 2 semanas, seguros 3, bancos y cajas 4 a 5. Sin `periodo`, las herramientas usan el último publicado |
| Unidades | Indicadores en %. Montos en miles de soles, como los muestra el Excel. En los rankings de seguros la celda guarda soles y el Excel muestra miles, así que el servidor divide entre 1000 |
| Cita | «Fuente: SBS», el título y código del boletín, el periodo y la URL del archivo. No encontramos una licencia publicada para estos datos |

### Límites que conviene saber

- **No incluye las tasas de interés por entidad de Retasas.** La SBS solo las publica en `www.sbs.gob.pe`, que les
  responde a los programas con un desafío anti-robots. Este servidor no intenta pasarlo. Lo más cercano que publica la
  SBS por entidad es el indicador «Ingresos financieros anualizados / activo productivo promedio»
  (`indicadores` con `indicador="rendimiento"`). Si necesitan Retasas, lo correcto es pedirle a la SBS un acceso
  abierto.
- **Uso respetuoso.** Un pedido por segundo como máximo, sumando todos los servidores que corran en la máquina (cada
  sesión de Claude Code levanta uno), y caché en `datos/`. Si la SBS responde una página web en vez
  de un Excel, el servidor se detiene y lo dice.
- **Información, no asesoría.** Las cifras son las publicadas por la SBS. Elegir AFP, banco o seguro es una decisión
  de cada uno.

## Pruebas y evaluación

```bash
uv run pytest -q                                  # todas; las marcadas live bajan los Excel reales de la SBS
uv run evaluar.py --modos memoria web mcp         # 10 preguntas a Claude (Haiku) sin herramientas, con web y con el MCP
```

`preguntas.csv` trae, para cada pregunta, la cifra oficial y la celda del Excel donde comprobarla. Los resultados y su
análisis están en [`informe.md`](informe.md).

## Origen

Proyecto de la sesión 04, «MCP: Claude conectado a tus datos», del curso *Data Science con Python*
([d2cml-ai/Data-Science-Python](https://github.com/d2cml-ai/Data-Science-Python)). El curso proponía un MCP del
BCRP; este repositorio lo lleva a la SBS. `evaluar.py` y el estilo de las pruebas vienen del proyecto del curso.

Autoría: Rodrigo Norabuena, en coautoría con Claude (Anthropic). El código se publica con licencia
[MIT](LICENSE). Los datos son de la SBS: cítenla como fuente.
