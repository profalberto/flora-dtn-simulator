# RELATÓRIO 1.2.0 — FLoRA-DTN

## A. Alterações implementadas

- `flora_dtn.py`: IDTU por bundle (km crítico por cenário, t_chegada_km_critico por embarcação, idtu_soma/idtu_n/serie_idtu em Metricas, idtu_media/idtu_n no resumo, proveniencia no JSON).
- `flora_dtn.py`: JSON com `resultados_simulados` e `cenarios_ilustrativos` (proveniencia).
- `flora_cenario.py`: campo `fonte` em `CenarioHidrologico` e nas 3 instâncias.
- `flora_analise.py`: `ic95_diferenca_pareada`, `gerar_diferencas`, `analise_estatistica_diferencas.csv`.
- `dtn_simulador.py`: modo `analisar` gera o CSV de diferenças; subcomando `artigo` com `--densidades`.
- `scripts/gerar_tabelas_artigo.py`: Tabela 8 (IDTU) e Tabela 9 (densidade), pastas separadas.
- `flora_versao.py`, `CITATION.cff`: versão 1.2.0.

## B. Problemas corrigidos

- IDTU não era calculado; agora é por bundle entregue, com agregação e série temporal.
- JSON não separava simulado de ilustrativo; agora tem seções com proveniencia.
- Cenários sem fonte declarada; campo `fonte` adicionado.
- IC da diferença entre pares não existia; função e CSV adicionados.
- Densidade de frota não variava; `densidade_frota` + `--densidades`.
- Tabela 8 (IDTU) e Tabela 9 (densidade) não existiam; geradas.

## C. Testes

- Total: 102 (85 modelo + 17 fumaça).
- Aprovados: 102. Reprovados: 0.
- Novos testes adicionados nesta versão: nenhum além dos já existentes (a suíte permanece 102/102).

## D. Resultados comparativos

Não foi executada a matriz completa (1080 runs). Os resultados anteriores (168h×30) permanecem em `resultados/artigo/`. As novas métricas (IDTU) aparecerão nas próximas execuções.

## E. Limitações remanescentes

- Bloco 7 (correções no .tex do artigo): não há arquivo .tex no repositório; as correções devem ser aplicadas no manuscrito externo.
- LPA P95, overhead detalhado e distinção de cobertura não implementados.
- Protocolo NC (sem conectividade) não adicionado (SC preservado).
- Análise estatística avançada (bootstrap 10k, post-hoc) não implementada.
- Matriz 1080 não executada.

## F. Conclusão científica

A versão 1.2.0 adiciona IDTU, proveniência no JSON e fonte dos cenários, atendendo aos requisitos do parecer para rastreabilidade. As afirmações sobre resultados simulados vs. ilustrativos agora são separáveis no JSON.

## G. Instruções de execução

```bash
pip install -r requirements.txt
python -m pytest tests -q
python dtn_simulador.py --version
python dtn_simulador.py rodar -c C3 -p flora -H 168
python dtn_simulador.py analisar -e resultados
python dtn_simulador.py artigo --sementes 30 --horizonte 168 --densidades muito_baixa,media,alta
```