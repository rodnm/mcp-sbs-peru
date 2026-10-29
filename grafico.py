"""grafico.png a partir de resultados.csv: cuántas cifras acertó Claude en cada modo.

    uv run --group dev grafico.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

AQUI = Path(__file__).parent
MODOS = {"memoria": "Solo memoria", "web": "Búsqueda web", "mcp": "MCP de la SBS"}
COLORES = {"acierta": "#2a78d6", "no sabe": "#eb6834", "se equivoca": "#1baf7a"}   # paleta validada (CVD)
NOMBRES = {"acierta": "Acierta", "no sabe": "Dice que no sabe", "se equivoca": "Se equivoca"}
TINTA, TINTA_2, FONDO = "#0b0b0b", "#5f5e5a", "#fcfcfb"

res = pd.read_csv(AQUI / "resultados.csv")
conteo = res.groupby("modo").resultado.value_counts().unstack(fill_value=0).reindex(list(MODOS)[::-1])
segundos = res.groupby("modo").segundos.mean()
total = int(conteo.sum(axis=1).max())

fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150, facecolor=FONDO)
ax.set_facecolor(FONDO)
izquierda = pd.Series(0, index=conteo.index)
for resultado in [r for r in COLORES if r in conteo.columns and conteo[r].sum() > 0]:
    ax.barh([MODOS[m] for m in conteo.index], conteo[resultado], left=izquierda, height=0.5,
            color=COLORES[resultado], edgecolor=FONDO, linewidth=2, label=NOMBRES[resultado])
    izquierda += conteo[resultado]
for i, modo in enumerate(conteo.index):
    ax.text(total + 0.2, i, f"{conteo.loc[modo].get('acierta', 0)} de {total} · {segundos[modo]:.1f} s",
            va="center", fontsize=10, color=TINTA)

ax.set_xlim(0, total + 2.6)
ax.set_xticks(range(0, total + 1, 2))
ax.tick_params(colors=TINTA_2, labelsize=9, length=0)
ax.tick_params(axis="y", labelsize=10, labelcolor=TINTA)
ax.grid(axis="x", color="#e4e3df", linewidth=0.8)
ax.set_axisbelow(True)
for borde in ax.spines.values():
    borde.set_visible(False)
ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=9, labelcolor=TINTA,
          handlelength=1.2)
fig.suptitle("¿Cuántas cifras oficiales de la SBS acertó Claude (Haiku)?", x=0.02, y=0.98, ha="left",
             fontsize=12, color=TINTA, fontweight="bold")
fig.text(0.02, 0.02, "10 preguntas de banca, AFP y seguros · a la derecha, aciertos y segundos promedio por pregunta "
         "· fuente: resultados.csv (evaluar.py)", fontsize=7.5, color=TINTA_2)
fig.tight_layout(rect=(0, 0.05, 1, 0.96))
fig.savefig(AQUI / "grafico.png", facecolor=FONDO)
print("grafico.png listo")
