# CHANGELOG

## 1.3.0 (2026-11-12)

- Adicionados protocolos estendidos: `oficial`, `slp_moveis`, `satelite`, `flora_perigo`.
- `ProtocoloDTN` ganha `upload_gateway` e `usa_gateways_moveis`.
- `ConfiguracaoDTN` ganha `densidade_frota`, `delta_dec_h`, `tau_valid_h`, `utilidade_legada`.
- IDTU rigoroso: denominador apenas embarcações expostas; categorias informado a tempo/tarde/nunca; lead distance e antecedência.
- Cenários C1/C2/C3 ganham campo `fonte`; S26 (seca 2026) adicionado com guarda de CSV.
- Novas classes de embarcação: NAVIO_OCEANICO, COMBOIO, REGIONAL.
- `flora_analise` ganha `ic95_diferenca_pareada` e `gerar_diferencas`.
- `validar_consistencia` compara CSV e JSON.
- `--dry-run` em todos os subcomandos.
- Script `gerar_tabelas_artigo.py` gera Tabelas 5-9.
- Script `gerar_figuras_artigo.py` gera figuras 4-9.
- Versão bump 1.2.0 → 1.3.0.

## 1.2.0 (2026-11-11)

- IDTU por execução, Tabelas 8 e 9, JSON com `resultados_simulados`/`cenarios_ilustrativos`, fonte dos cenários, IC da diferença, densidade de frota.

## 1.1.1 (2026-11-11)

- Correções de bugs: COR_FUNDO duplicado, inserir prioridade, _blocos, _atualizar_km, README.

## 1.1.0 (2026-11-10)

- Versão inicial com logging, comparar --paralelo, analisar, exportação completa.