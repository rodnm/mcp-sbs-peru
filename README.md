# mcp-sbs-peru

Un servidor MCP para que Claude responda con las cifras oficiales de la **Superintendencia de Banca, Seguros y AFP
del Perú (SBS)**: morosidad y solvencia de bancos y cajas, participación de mercado, comisiones y rentabilidad de las
AFP, y ranking de aseguradoras. Cada respuesta cita el boletín, el periodo y la URL del Excel de la SBS, así que
cualquiera puede comprobarla.

> Ejemplos: «¿Qué banco tiene la menor morosidad?», «¿Qué AFP cobra menos comisión?», «¿Quién vende más SOAT?»,
> «ROE de las cajas municipales en agosto de 2026».

## Uso rápido

Necesitan [uv](https://docs.astral.sh/uv/) y [Claude Code](https://claude.com/claude-code).

```bash
git clone <url-de-este-repositorio> mcp-sbs-peru
cd mcp-sbs-peru
uv run pytest -q -m "not live"     # pruebas sin internet: deben pasar todas
claude                             # acepten los servidores de .mcp.json (sbs y fetch)
```

Dentro de Claude Code, `/mcp` debe mostrar `sbs` conectado. Para usarlo desde otro proyecto:

```bash
claude mcp add sbs -- uv run --directory /ruta/a/mcp-sbs-peru server.py
```

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
- **Uso respetuoso.** Un pedido por segundo como máximo y caché en `datos/`. Si la SBS responde una página web en vez
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

Autoría: Rodrigo Norabuena, en coautoría con Claude (Anthropic).
