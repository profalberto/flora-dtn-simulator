# FLoRA-DTN — Delay-tolerant networking simulator with LoRa

Simulator for the FLoRA experiment (Fluxo LoRa) on sharing hydrographic
information between vessels in the Amazon river corridor between Manaus and
Itacoatiara (UFAM, Brazil). It compares the utility-based FLoRA protocol with
epidemic flooding, spray-and-wait, SLP (plain LoRaWAN) and a conventional
system (SC).

> **Warning.** Generated charts are simulation output and are **not safe for
> navigation**. Bathymetry comes from synthetic cross-sections calibrated for
> the experiment, not from hydrographic surveys.

This is a condensed English guide. The complete reference — every CLI flag,
map layer, scenario parameter and output field — is in
[README.md](README.md) (Portuguese).

## Repository

- Code and example results: <https://github.com/profalberto/flora-dtn-simulator>
- Statistical example: [docs/analise_estatistica.md](docs/analise_estatistica.md)

```bash
git clone https://github.com/profalberto/flora-dtn-simulator.git
cd flora-dtn-simulator
pip install -r requirements.txt
python dtn_simulador.py --version
```

`exemplos/` contains a 2 h C2 run for all five protocols, in the three separate
files plus the complete JSON. It lets you try `analisar` without running the
simulator:

```bash
python dtn_simulador.py analisar -e exemplos
```

## What is new in 1.1.0

- `--version` prints version and commit; the banner appears in every mode.
- `comparar --paralelo` distributes the five protocols across processes.
- `rodar` writes a **single JSON with the complete simulation** (also available
  from the GUI *Exportar* menu); `analisar` reads that file directly.
- `analisar` aggregates runs with mean, 95% CI, Shapiro-Wilk, ANOVA/Friedman
  and Holm correction.
- Per-run logging to `logs/`.
- pytest smoke tests, MIT license, `CITATION.cff` and rewritten documentation.

## Requirements

- Python 3.10+ (tested on 3.13)
- `numpy`, `Pillow`, `pygame-ce`, `scipy` (see `requirements.txt`)
- `pytest` for the full test suite (`requirements-dev.txt`)

The map uses local tiles in `mapa_tiles/` and `mapa_tiles_satelite/`. Without
them the simulator still runs, but the basemap is unavailable. `dados_osm/`
holds the real river axis used by the geometry.

## Quick start

```bash
python dtn_simulador.py                     # pygame interface
python dtn_simulador.py --version           # version + commit
python dtn_simulador.py rodar -c C2 -H 6    # headless, writes results
python dtn_simulador.py comparar -H 6       # five protocols, comparison table
python dtn_simulador.py analisar -e resultados
python dtn_simulador.py carta -c C3 -o cartas/mapa.png
```

Windows launchers avoid nested-quote problems in PowerShell:

```powershell
.\executar.bat --version
powershell -ExecutionPolicy Bypass -File .\executar.ps1 --version
```

`rodar`, `carta`, `comparar` and `analisar` are headless: they do not start
pygame and work on a server.

## Modes

| Mode | Purpose |
| --- | --- |
| `gui` (default) | Interactive pygame map, fleet panel and menus. |
| `rodar` | One headless run; writes metrics, fleet, config and the complete JSON. |
| `comparar` | Runs the five protocols with the same seed and prints a comparison table. |
| `analisar` | Aggregates `*_metricas.csv` / `*_simulacao.json` files and applies statistics. |
| `carta` | Renders a nautical chart, with or without a simulation. |

## Outputs

Every run writes:

| File | Content |
| --- | --- |
| `<base>_metricas.csv` | time series of aggregate metrics |
| `<base>_frota.csv` | final state of each vessel |
| `<base>_config.json` | full configuration, enough to reproduce the run |
| `<base>_simulacao.json` | **single file** with summary, config, scenario, fleet, supernodes, series and raw samples |
| `logs/flora_<date>_<pid>.log` | run log |

`--sem-completo` disables the complete JSON in `rodar`. `analisar` uses the CSV
and ignores the matching JSON when both are in the same folder, so one run is
never counted twice.

### Complete JSON schema

| Key | Content |
| --- | --- |
| `formato`, `formato_versao` | format identifier for future readers |
| `software` | simulator name, version and commit |
| `resumo` | every aggregate metric of the run |
| `configuracao` | the full `ConfiguracaoDTN`, field by field |
| `cenario` | code, name, final river level and active obstacles |
| `frota` | one entry per vessel: position, risk, buffer, transmissions, energy |
| `supernos` | fixed and mobile gateways with position, range and drained bundles |
| `series` | TED and LPA, hour by hour |
| `amostras` | raw latencies, bundles per category, TCI and coverage per bundle |

## Statistical analysis

`analisar` groups runs by protocol and reports, for each metric, `n`, mean,
standard deviation, 95% confidence interval and the Shapiro-Wilk p-value. It
then tests the protocol effect:

- **Friedman** when runs are paired by `(scenario, seed, horizon)`;
- **ANOVA** when runs are independent;
- **Holm** correction over the family of metrics.

Filters: `--cenario`, `--horizonte`, `--confianca` and `--metricas`.

The worked example in [docs/analise_estatistica.md](docs/analise_estatistica.md)
uses 25 runs (5 protocols × 5 seeds, C2, 2 h). It is a demonstration of the
pipeline, not the full paper experiment. Note that SLP and SC currently share
the same forwarding implementation (no vessel-to-vessel relay), so their
numbers coincide.

## Tests

```bash
python tests/test_simulador.py            # 85 model tests, no extra dependencies
python -m pytest tests -q                 # 101 tests (model + smoke)
python -m pytest tests/test_fumaca.py -q  # smoke only
```

The smoke suite covers `--version`, headless runs and logs, `comparar
--paralelo`, the complete JSON, `analisar` with Friedman/Holm, the no-git commit
fallback and module imports.

## Layout

| File | Responsibility |
| --- | --- |
| `flora_geometria.py` | channels, physical scale, geodesy, distance to the river axis, gateway coverage |
| `flora_cenario.py` | C1/C2/C3 scenarios, bathymetry, river level, draft risk |
| `flora_lora.py` | LoRa physical layer: airtime, energy, duty cycle |
| `flora_dtn.py` | bundles, protocols, fixed/mobile supernodes, fleet, metrics, engine |
| `flora_mapa.py` | tile mosaic, bathymetry colours, nautical chart |
| `flora_tiles.py` | XYZ tile map, Web Mercator, memory/disk cache |
| `flora_ui.py` | pygame interface and menus |
| `flora_analise.py` | CSV/JSON reader, CI, Shapiro-Wilk, ANOVA/Friedman, Holm |
| `flora_log.py` | per-run file logging |
| `flora_versao.py` | version and commit resolution |
| `dtn_simulador.py` | CLI entry point |

## Reproducibility

The same seed, scenario, protocol and horizon produce identical results. The
parallel mode was checked against the sequential one and writes byte-identical
CSVs. At startup the simulator resolves the commit in this order:
`FLORA_COMMIT`, `git rev-parse --short HEAD`, a `COMMIT` file, then `sem-git`.

Versioning rule: a new feature bumps the minor, a fix bumps the patch, and an
incompatible CLI/CSV change bumps the major.

## License and citation

MIT — see [LICENSE](LICENSE). Citation metadata is in [CITATION.cff](CITATION.cff).

Author: António Alberto (ICET/UFAM) — <profalbertosena@gmail.com>.
