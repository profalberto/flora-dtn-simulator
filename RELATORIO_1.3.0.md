# RELATÓRIO 1.3.0 — FLoRA-DTN

## Achados confirmados

| Achado | Status | Observação |
| --- | --- | --- |
| A1 SC e SLP idênticos | Confirmado | Corrigido: sc agora não faz upload (upload_gateway=False); slp sem gateways móveis. |
| A2 seletividade FLoRA | Confirmado | Corrigido: prioridade aplicada ao destino; --utilidade-legada preserva antigo. |
| A3 utilidade vs IDTU | Parcialmente | Utilidade ainda usa distância ao superno; flora_perigo adicionado com objetivo IDTU. |
| A4 frota 15 vs 14 | Confirmado | DENSIDADES_FROTA["media"]=14; padrão mantém 15 (densidade_frota=None). |
| A5 calado máximo 2,5 m | Confirmado | Novas classes NAVIO_OCEANICO, COMBOIO, REGIONAL adicionadas. |
| A6 gateway móvel = satélite | Confirmado | Documentado; slp_moveis e satelite adicionados como baselines. |
| A7 carga vs cota | Confirmado | Teste de carga mínima pendente. |
| A8 CAR = 100% | Confirmado | CAR satura em C1 (sem zona de risco). |
| A9 RELATORIO_1.2.0 | Confirmado | IDTU e densidade implementados nesta versão. |
| A10 README vs artigo | Confirmado | Valores do README estão desatualizados. |
| A11 limitações do artigo | Confirmado | README/limitações devem ser atualizados. |

## Blocos concluídos

- Bloco 1 (IDTU): concluído.
- Bloco 2 (Tabela 8): concluído (script).
- Bloco 3 (separação simulado/ilustrativo): concluído.
- Bloco 4 (fonte cenários): concluído.
- Bloco 5 (IC diferença): concluído.
- Bloco 6 (densidade): concluído (código; execução pendente).
- Bloco 7 (artigo .tex): não aplicável (sem .tex no repositório).

## Tarefas T1-T11

- T1 (baselines): parcialmente (protocolos adicionados; oficial bulletin implementado).
- T2 (seletividade): concluído (--utilidade-legada).
- T3 (flora_perigo): concluído (código).
- T4 (IDTU rigoroso): concluído.
- T5 (calibração rádio): parcialmente (densidade e novas classes; trace CSV pendente).
- T6 (frota realista): parcialmente (classes adicionadas; S26 com guarda).
- T7 (logística): não implementado (módulo flora_logistica.py pendente).
- T8 (tempo de resposta): não implementado.
- T9 (fatorial): parcialmente (script gera tabelas; matriz não executada).
- T10 (validação interna): parcialmente (testes existentes).
- T11 (documentação): CHANGELOG e RELATÓRIO criados; README pendente de atualização de limitações.

## Testes

- Total: 102. Aprovados: 102. Reprovados: 0.

## Limitações remanescentes

- Módulo logístico (T7) e tempo de resposta (T8) não implementados.
- Matriz 1080 não executada.
- Validação física não realizada.

## Instruções

```bash
pip install -r requirements.txt
python -m pytest tests -q
python dtn_simulador.py --version
```