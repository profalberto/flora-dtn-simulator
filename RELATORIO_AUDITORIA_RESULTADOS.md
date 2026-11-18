# RELATORIO_AUDITORIA_RESULTADOS.md

## A. Diagnostico geral

- Versao identificada: 1.3.0 (commit 1be364e).
- Testes: 103/103 passando.
- Dados brutos: 450 execucoes (C1/C2/C3 x 5 protocolos x 30 sementes, 168h) em resultados/artigo/tabela6/.
- Tabelas agregadas: tabela5 (gateways), tabela6 (protocolos), tabela7 (estatistica), tabela8 (IDTU), tabela9 (densidade).
- IDTU: implementado mas os valores de C2/C3 sao 0 (bug: calculado na entrega ao gateway, que ocorre apos o trecho critico). Corrigido em v1.4.0 (commit 408bd1d) com denominador de embarcacoes expostas.
- SC: TED=0% por construcao (sem upload, sem relay) — isso e definicao, nao bug.
- Slp em C1: TED 62.7% (vs 98% em C2/C3) — investigar cobertura de gateway.

## B. Lista de arquivos que precisam ser lidos

- flora_dtn.py — motor, protocolos, metricas, bundles.
- flora_lora.py — camada fisica LoRa.
- flora_cenario.py — cenarios hidrologicos.
- flora_geometria.py — canais, escala, gateways.
- flora_analise.py — analise estatistica.
- dtn_simulador.py — CLI.
- artigo/artigo.txt — artigo LaTeX.
- resultados/artigo/*.csv — dados agregados.
- exemplos/ — execucao de demonstracao.

## C. Pendencias tecnicas

- IDTU calculado na entrega ao gateway (tarde demais) — corrigido em v1.4.0.
- LPA P95, overhead detalhado, cobertura distintas — nao implementados.
- Protocolo NC (sem conectividade) — nao adicionado (SC e o proxy).
- Analise estatistica avancada (bootstrap, post-hoc) — nao implementada.
- Matriz 1080 nao executada.

## D. Pendencias metodologicas

- README com valores desatualizados (TED 96.2%, LPA 60.8 min).
- Artigo com generalizacoes e "Tabela ??".
- Limitacoes do artigo descrevem versao antiga.

## E. Pendencias experimentais

- Resultados existentes suficientes para Tabelas 5-7.
- IDTU precisa reexecucao apos correcao (v1.4.0).
- Densidade (Tabela 9) so rodou com densidade "media".

## F. Plano de correcao

1. Correcoes criticas: IDTU (feito), SC (definido), slp C1 (investigar).
2. Correcoes importantes: LPA P95, overhead detalhado, cobertura.
3. Melhorias: NC, bootstrap, post-hoc.
4. Preparacao para submissao: atualizar artigo com valores reais.

## G. Criterios para considerar o simulador pronto

- 102+ testes passando.
- IDTU > 0 em C2/C3 para flora.
- Tabelas 5-9 geradas com provenance.
- Artigo com valores consistentes com os dados.
- README atualizado.