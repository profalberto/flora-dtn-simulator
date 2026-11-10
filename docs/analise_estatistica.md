# Analise estatistica — exemplo reproduzivel

Este documento descreve a analise produzida pelo modo `analisar` e apresenta um
exemplo com **25 execucoes** do cenario **C2**, horizonte de **2 h** e **5
sementes** por protocolo. O objetivo e demonstrar o formato da saida e o
encadeamento dos testes; **nao e o experimento completo do artigo**.

## Como reproduzir

```bash
# 1. Gera as execucoes (os cinco protocolos, C2, 2 h)
python dtn_simulador.py comparar -c C2 -H 2 -s 20260826 -o resultados/amostra

# 2. Agrega e aplica os testes
python dtn_simulador.py analisar -e resultados/amostra -o docs -c C2 -H 2
```

O `comparar` executa sempre os cinco protocolos; para variar a semente, repita o
comando com `-s 20260827`, `-s 20260828` e assim por diante, usando a mesma
pasta de saida. O `analisar` reconhece cada arquivo `*_metricas.csv` como uma
execucao independente.

## Desenho da amostra

| Item | Valor |
| --- | --- |
| Cenario | C2 |
| Horizonte | 2 h |
| Passo de tempo | 10 s (padrao) |
| Sementes | 20260826 a 20260830 |
| Protocolos | epidemia, spray-and-wait, FLoRA, SLP, SC |
| Execucoes | 25 (5 por protocolo) |
| Blocos pareados | 5 (um por semente) |

As comparacoes usam **Friedman**, porque as cinco sementes formam blocos
pareados entre protocolos: a mesma semente produz o mesmo estado inicial e o
mesmo calendario de eventos. A hipotese nula e que os protocolos tem a mesma
distribuicao de desempenho dentro de cada bloco.

## Resultados

### TED — taxa de entrega

| Protocolo | n | Media | Desvio | IC 95% | Shapiro p |
| --- | ---: | ---: | ---: | ---: | ---: |
| epidemia | 5 | 85,51% | 6,69 | [77,20; 93,83] | 0,4289 |
| FLoRA | 5 | 71,59% | 6,27 | [63,80; 79,38] | 0,8648 |
| spray-and-wait | 5 | 54,00% | 8,63 | [43,27; 64,72] | 0,1210 |
| SLP | 5 | 51,01% | 10,92 | [37,46; 64,56] | 0,5185 |
| SC | 5 | 51,01% | 10,92 | [37,46; 64,56] | 0,5185 |

Friedman: estatistica = 19,191; **p = 0,000721**; p ajustado por Holm =
**0,002996**; blocos = 5.

### Overhead de copias

| Protocolo | n | Media | Desvio | IC 95% | Shapiro p |
| --- | ---: | ---: | ---: | ---: | ---: |
| epidemia | 5 | 7,95x | 0,55 | [7,26; 8,64] | 0,6476 |
| FLoRA | 5 | 2,28x | 0,31 | [1,90; 2,66] | 0,7059 |
| spray-and-wait | 5 | 1,35x | 0,04 | [1,30; 1,40] | 0,9226 |
| SLP | 5 | 1,00x | 0,00 | [1,00; 1,00] | n/a |
| SC | 5 | 1,00x | 0,00 | [1,00; 1,00] | n/a |

Friedman: estatistica = 20,000; **p = 0,000499**; p ajustado por Holm =
**0,002996**; blocos = 5.

### Transmissoes

| Protocolo | n | Media | Desvio | IC 95% | Shapiro p |
| --- | ---: | ---: | ---: | ---: | ---: |
| epidemia | 5 | 310,20 | 36,54 | [264,83; 355,57] | 0,4874 |
| FLoRA | 5 | 74,20 | 11,39 | [60,06; 88,34] | 0,7191 |
| spray-and-wait | 5 | 33,40 | 6,07 | [25,87; 40,93] | 0,8225 |
| SLP | 5 | 23,20 | 4,82 | [17,22; 29,18] | 0,7869 |
| SC | 5 | 23,20 | 4,82 | [17,22; 29,18] | 0,7869 |

Friedman: estatistica = 20,000; **p = 0,000499**; p ajustado por Holm =
**0,002996**; blocos = 5.

### Energia total

| Protocolo | n | Media | Desvio | IC 95% | Shapiro p |
| --- | ---: | ---: | ---: | ---: | ---: |
| epidemia | 5 | 5,84 J | 0,80 | [4,86; 6,83] | 0,3502 |
| FLoRA | 5 | 1,42 J | 0,29 | [1,06; 1,78] | 0,4851 |
| spray-and-wait | 5 | 0,52 J | 0,12 | [0,37; 0,68] | 0,4392 |
| SLP | 5 | 0,38 J | 0,10 | [0,26; 0,50] | 0,2364 |
| SC | 5 | 0,38 J | 0,10 | [0,26; 0,50] | 0,2364 |

Friedman: estatistica = 20,000; **p = 0,000499**; p ajustado por Holm =
**0,002996**; blocos = 5.

### LPA — latencia media

| Protocolo | n | Media | Desvio | IC 95% | Shapiro p |
| --- | ---: | ---: | ---: | ---: | ---: |
| epidemia | 5 | 5,27 min | 3,96 | [0,36; 10,19] | 0,0975 |
| FLoRA | 5 | 7,36 min | 4,45 | [1,83; 12,89] | 0,2398 |
| spray-and-wait | 5 | 4,67 min | 3,17 | [0,73; 8,61] | 0,0452 |
| SLP | 5 | 5,66 min | 4,01 | [0,68; 10,64] | 0,0549 |
| SC | 5 | 5,66 min | 4,01 | [0,68; 10,64] | 0,0549 |

Friedman: estatistica = 3,718; **p = 0,4456**; p ajustado por Holm =
**0,4456**; blocos = 5. Nao ha evidencia de diferenca entre protocolos na LPA
nesta amostra.

### CAR — razao de atualidade

Todos os protocolos ficaram em **100,00%** nas cinco sementes, sem variancia.
O Friedman nao pode ser calculado quando todos os blocos sao constantes; a
saida registra `n/a`. O resultado reflete o horizonte curto de 2 h e a
definicao de CAR usada no modelo, nao uma conclusao sobre o experimento longo.

## Leitura dos resultados

1. **TED.** A epidemia entrega mais (85,5%), seguida de FLoRA (71,6%). A
   diferenca entre protocolos e significativa (Friedman, p = 0,00072), mas o
   teste global nao indica **quais** pares diferem; o modo `analisar` nao faz
   post-hoc pareado.
2. **Custo.** A vantagem da epidemia vem com 7,95 copias por entrega, 310
   transmissoes e 5,84 J. FLoRA entrega 71,6% com 2,28 copias, 74 transmissoes
   e 1,42 J — cerca de um quarto da energia da epidemia por uma perda de
   ~14 pontos percentuais de TED.
3. **SLP e SC.** Os dois protocolos coincidem numericamente nesta amostra
   porque ambos tem `navega_entre_embarcacoes = False` e `decidir()` vazio no
   motor: sem relay entre embarcacoes, os dois dependem exclusivamente do
   contato direto com um superno. A diferenca entre eles e conceitual, nao
   operacional, no codigo atual. Isso deve ser corrigido ou explicitado antes
   de usar a comparacao em publicacao.
4. **LPA.** Sem diferenca significativa; os intervalos de confianca se
   sobrepoem bastante.
5. **Amostra pequena.** Cinco sementes e um unico cenario sustentam um teste
   de demonstracao, nao uma conclusao do artigo. Para o experimento completo,
   use os tres cenarios, o horizonte do artigo e um numero maior de sementes.

## Arquivos gerados

| Arquivo | Conteudo |
| --- | --- |
| `docs/analise_estatistica.csv` | uma linha por metrica e protocolo, com n, media, desvio, IC e p de Shapiro |
| `docs/analise_estatistica.json` | a mesma informacao em JSON, mais os testes, blocos e ajuste de Holm |

O CSV e o JSON sao gravados pelo proprio `analisar`; este documento apenas
resume e interpreta a saida.
