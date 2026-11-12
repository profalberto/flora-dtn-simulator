# FLoRA-DTN — Simulador de redes tolerantes a atraso com LoRa

**Portugues** | [English](README.en.md)

Simulador do experimento FLoRA (Fluxo LoRa) para compartilhamento de
informacoes hidrograficas entre embarcacoes na calha do Amazonas, entre Manaus
e Itacoatiara (UFAM). Compara o protocolo utilidade-baseado FLoRA com
inundacao (*epidemic*), *spray-and-wait*, SLP (LoRaWAN puro) e comunicacao
convencional (SC).

> **Aviso.** As cartas geradas sao de simulacao e **nao sao aptas para
> navegacao**. A batimetria vem de perfis transversais sinteticos calibrados
> para o experimento, nao de levantamentos hidrograficos.

## Repositorio

Codigo, documentacao e resultados de exemplo:
<https://github.com/profalberto/flora-dtn-simulator>.

```bash
git clone https://github.com/profalberto/flora-dtn-simulator.git
cd flora-dtn-simulator
pip install -r requirements.txt
python dtn_simulador.py --version
```

A pasta `exemplos/` traz uma execucao do cenario C2 com 2 h e semente
20260826 para os cinco protocolos, nos tres formatos separados e no JSON
completo. Serve para conferir os formatos e rodar o modo `analisar` sem
executar o simulador:

```bash
python dtn_simulador.py analisar -e exemplos
```

## Novidades da versao 1.4.0

* Politica de utilidade por mensagem (`--politica-utilidade mensagem`) implementando a Eq. (10) do artigo, com `--utilidade-legada` preservando o comportamento anterior;
* TTL configuravel por tipo de bundle (seguranca/rotina) e buffer finito por utilidade;
* IDTU rigoroso com denominador de embarcacoes expostas, lead distance e antecedencia;
* Novas classes de embarcacao (NAVIO_OCEANICO, COMBOIO, REGIONAL) e protocolos (oficial, slp_moveis, satelite, flora_perigo);
* Cenario S26 (seca 2026) com fonte declarada.

## Novidades da versao 1.1.0

* `--version` imprime a versao e o commit, e o banner de abertura aparece em
  todos os modos;
* `comparar --paralelo` distribui os cinco protocolos entre processos;
* `rodar` grava um **JSON unico com a simulacao completa** (menu Exportar na
  interface) e `analisar` le esse arquivo diretamente;
* o modo `analisar` agrega os CSV com media, IC95%, Shapiro-Wilk,
  ANOVA/Friedman e correcao de Holm;
* logging em arquivo por execucao, em `logs/`;
* testes de fumaca com pytest (`tests/test_fumaca.py`);
* `LICENSE` (MIT), `CITATION.cff` e esta documentacao revisada.

## Instalacao

```bash
pip install -r requirements.txt        # simulador e modo analisar
pip install -r requirements-dev.txt    # idem + pytest
```

## Versao e reprodutibilidade

Toda execucao abre com a versao e o commit que geraram o binario:

```text
FLoRA-DTN 1.1.0
Simulador DTN-LoRa da calha do Amazonas (UFAM)
commit sem-git | Python 3.13.7
```

O comando `python dtn_simulador.py --version` imprime a mesma identificacao e
sai. O hash e resolvido em cascata, sem quebrar quando a pasta nao e um clone
git:

1. variavel de ambiente `FLORA_COMMIT` (util em CI e em pacotes gerados);
2. `git rev-parse --short HEAD` na raiz do projeto;
3. arquivo `COMMIT` com uma linha (gerado no empacotamento);
4. `sem-git`.

A versao fica em `flora_versao.VERSAO`. Regra de incremento: funcionalidade
nova sobe o minor, correcao sobe o patch, mudanca incompativel de CLI ou de
CSV sobe o major.

## Uso

```bash
python dtn_simulador.py --version                                 # versao + commit
python dtn_simulador.py                                          # interface grafica
python dtn_simulador.py rodar -c C3 -p flora -H 168             # sem tela, grava CSV
python dtn_simulador.py carta -c C2 -o cartas/vazante.png       # carta sem simular
python dtn_simulador.py carta -c C3 --rodar 74 -o cartas/tc.png  # carta apos simular
python dtn_simulador.py comparar -c C3 -H 168                   # tabela dos 5 protocolos
python dtn_simulador.py comparar -c C3 -H 168 --paralelo        # em processos
python dtn_simulador.py analisar -e resultados                  # estatistica agregada
```

`rodar`, `carta`, `comparar` e `analisar` sao headless: nao inicializam o pygame
e funcionam em servidor. `rodar` grava, alem dos tres CSV/JSON separados, um
unico `<base>_simulacao.json` com a simulacao completa; `--sem-completo`
desliga esse arquivo. Ajuste os parametros do modelo com opcoes como
`--passo`, `--semente`, `--fator-alcance`, `--limiar-utilidade`,
`--fator-retencao`, `--sigma-d` e `--copias-spray`.

### Windows e PowerShell

O caminho do projeto tem espacos, entao use **um unico par de aspas** por
argumento. O erro `can't open file '...\"c:\...\dtn_simulador.py"'` acontece
quando se aninham aspas dentro de aspas:

```powershell
# ERRADO: as aspas duplas viram parte do nome do arquivo
& 'C:\...\python.exe' '"c:/Users/.../dtn_simulador.py"'

# CERTO: aspas simples fora, sem aspas dentro
& 'C:\...\python.exe' 'C:\Users\...\simulador\dtn_simulador.py' --version

# CERTO tambem: aspas duplas fora, sem aspas dentro
& 'C:\...\python.exe' "C:\Users\...\simulador\dtn_simulador.py" --version

# MAIS SIMPLES: estando na pasta do projeto
python dtn_simulador.py --version
```

Para nao depender da forma da chamada, o projeto inclui dois launchers que
resolvem o caminho a partir da propria localizacao:

```powershell
.\executar.bat --version
.\executar.bat rodar -c C3 -p flora -H 168
.\executar.ps1 comparar -c C3 -H 168 --paralelo
.\executar.ps1 analisar -e resultados
```

No PowerShell, se a politica de execucao bloquear o `.ps1`:

```powershell
powershell -ExecutionPolicy Bypass -File .\executar.ps1 --version
```

Para escolher outro interpretador, defina `FLORA_PYTHON` com o caminho do
`python.exe` antes de chamar o launcher.

A `carta` tem ainda as opcoes `--escala`, `--sem-legenda`, `--sem-metadados` e
`--base-satelite`, alem de um interruptor por camada da folha: `--sem-curvas`,
`--sem-sondagens`, `--sem-relevo` e `--sem-limites`.

A camada *Tinta de profundidade* vem desligada por padrao. Ela pinta a rampa de
risco de encalhe por cima do fundo, o que faz sentido sobre o satelite, onde a
cor de fundo nao diz nada sobre o leito, mas nao sobre a folha de carta, que ja
pinta a agua pela profundidade. Ligada por cima da carta, a segunda rampa, com
alfa ate 205, lava o gradiente e as curvas de cote. Para usa-la com a folha,
e um `--tinta-profundidade`.

### Logging em arquivo

Toda execucao grava um log proprio em `logs/`, com data, nivel, modulo e
mensagem:

```text
logs/flora_20261110_143012_18472.log
```

```text
2026-11-10 14:30:12 | INFO     | flora        | inicio: FLoRA-DTN 1.1.0 (commit sem-git)
2026-11-10 14:30:12 | INFO     | flora.rodar  | rodar: cenario=C3 protocolo=flora horizonte=168 semente=20260826 passo=10
2026-11-10 14:31:47 | INFO     | flora.rodar  | gravado: resultados/C3_flora_168h_s20260826_metricas.csv
```

| Opcao | Efeito |
| --- | --- |
| `--log-arquivo CAMINHO` | escolhe o arquivo (padrao: `logs/flora_<data>_<pid>.log`) |
| `--sem-log` | nao grava arquivo |
| `--log-console` | repete avisos e erros do log no terminal |
| `--verboso`, `-v` | grava tambem o progresso em nivel `DEBUG` |

O terminal continua a cargo dos `print`; o log nao duplica a tabela do modo
`comparar`. Se a pasta nao puder ser criada, a simulacao segue sem arquivo em
vez de abortar.

### Comparacao paralela

`comparar --paralelo` distribui os cinco protocolos entre processos do sistema
operacional, porque cada protocolo e uma simulacao independente e o gargalo e
CPU. O numero de processos e `--trabalhadores N` (padrao: ate cinco, limitado
ao numero de nucleos).

```bash
python dtn_simulador.py comparar -c C3 -H 168 --paralelo --trabalhadores 4 -o resultados
```

Cada processo recebe uma `ConfiguracaoDTN` picklavel e devolve o resumo, a
duracao e os arquivos gravados. As linhas de conclusao saem na ordem em que os
processos terminam, mas a tabela final e sempre impressa na ordem de
`PROTOCOLOS`, para que duas rodadas sejam comparaveis linha a linha. Se o
ambiente nao permitir processos (sandbox), o modo avisa e termina o que faltou
em sequencia, sem perder a rodada.

### Exportacao completa em um arquivo

Alem dos tres arquivos separados (`metricas.csv`, `frota.csv` e `config.json`),
cada execucao de `rodar` grava um **unico JSON autossuficiente**,
`<base>_simulacao.json`. Na interface, o mesmo arquivo sai pelo menu
**Exportar → Exportar simulacao completa (1 JSON)**. Use `--sem-completo` para
nao gera-lo no modo headless.

O JSON tem `formato` e `formato_versao` para leitura futura e as secoes:

| Secao | Conteudo |
| --- | --- |
| `software` | nome, versao e commit do simulador |
| `resumo` | todas as metricas agregadas da execucao |
| `configuracao` | a `ConfiguracaoDTN` completa, campo a campo |
| `cenario` | codigo, nome, nivel do rio e obstaculos ativos no fim |
| `frota` | estado final de cada embarcacao, uma entrada por no |
| `supernos` | gateways fixos e moveis, posicao, alcance e drenagem |
| `series` | TED e LPA hora a hora |
| `amostras` | latencias brutas, bundles por categoria, TCI e cobertura por bundle |

Por ser um arquivo so, ele pode ser copiado, versionado e analisado sem os CSV
auxiliares. O proprio modo `analisar` o le:

```bash
python dtn_simulador.py analisar -e resultados/C3_flora_168h_s20260826_simulacao.json
```

Quando a pasta tem o CSV e o JSON da mesma execucao, o `analisar` conta a
execucao **uma vez**, usando o CSV e ignorando o JSON correspondente.

### Analise estatistica

O modo `analisar` le os `*_metricas.csv` de uma pasta, de uma lista de arquivos
ou de globs e agrega por protocolo. As metricas padrao sao `ted_percentual`,
`ted_no_horizonte_percentual`, `lpa_minutos`, `car_percentual`, `tci_horas`,
`overhead_copias`, `transmissoes` e `energia_total_j`; use `--metricas` para
escolher outra lista separada por virgula.

```bash
python dtn_simulador.py analisar -e resultados -o resultados/analise
python dtn_simulador.py analisar -e resultados -c C3 -H 168 -o resultados/analise
```

Para as tabelas do artigo (5, 6 e 7), use:

```bash
python dtn_simulador.py artigo --sementes 30 --horizonte 168
```

O comando roda o comparativo para C1, C2 e C3, agrega e grava em
`resultados/artigo/` os arquivos `tabela5_gateways.csv/.tex`,
`tabela6_protocolos.csv/.tex` e `tabela7_estatistica.csv/.tex`. Use
`--sementes 3 --horizonte 2` para uma validacao rapida.

Se a pasta tiver mais de um cenario ou horizonte, o modo avisa e o relatorio
mistura regimes diferentes. Use `--cenario` e `--horizonte` para fixar o
regime que se quer comparar (por exemplo, C3 com 168 h), deixando apenas a
semente variar entre as repeticoes.

Para cada metrica o relatorio traz:

* **n, media, desvio, minimo e maximo** por protocolo;
* **IC95%** pela distribuicao t de Student, `media ± t * s / sqrt(n)`, que e o
  intervalo correto para amostras pequenas (o 1,96 normal subestimaria);
* **Shapiro-Wilk** para normalidade, com `p` por protocolo (omitido com menos
  de tres observacoes distintas);
* **Friedman** quando o mesmo bloco `(cenario, semente, horizonte)` foi medido
  em tres ou mais protocolos, isto e, medidas repetidas; **ANOVA de um fator**
  quando as amostras sao independentes; nenhum teste quando ha menos de dois
  protocolos com duas observacoes;
* **correcao de Holm** sobre todos os p-valores da mesma chamada. Testar oito
  metricas sem correcao infla o erro tipo I: com alfa de 5%, a chance de ao
  menos um falso positivo chega a 34%.

A saida vai para `resultados/analise/analise_estatistica.csv` (formato longo,
uma linha por metrica e protocolo) e `analise_estatistica.json` (com os grupos,
os testes e o p-valor ajustado), alem da tabela no terminal. O teste de
Friedman e preferido quando os blocos estao completos porque remove a
variabilidade entre sementes, que e justamente o que a comparacao entre
protocolos quer controlar.

Saída típica (comando `python dtn_simulador.py analisar -e exemplos`):

```text
FLoRA-DTN 1.1.0
Simulador DTN-LoRa da calha do Amazonas (UFAM)
commit 4c84ed7 | Python 3.13.7 | distancia_corredor_km=208.9
Analise de 5 execucoes | protocolos: epidemico, flora, sc, slp, spray | IC 95% | familia de 0 teste(s) com Holm

ted_percentual
protocolo        n      media     desvio                 IC95%   Shapiro p
epidemico        1      79.55       0.00                   n/a         n/a
flora            1      72.73       0.00                   n/a         n/a
sc               1      59.09       0.00                   n/a         n/a
slp              1      59.09       0.00                   n/a         n/a
spray            1      61.36       0.00                   n/a         n/a
  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)

ted_no_horizonte_percentual
protocolo        n      media     desvio                 IC95%   Shapiro p
epidemico        1      79.55       0.00                   n/a         n/a
flora            1      72.73       0.00                   n/a         n/a
sc               1      59.09       0.00                   n/a         n/a
slp              1      59.09       0.00                   n/a         n/a
spray            1      61.36       0.00                   n/a         n/a
  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)

lpa_minutos
protocolo        n      media     desvio                 IC95%   Shapiro p
epidemico        1       2.27       0.00                   n/a         n/a
flora            1       2.26       0.00                   n/a         n/a
sc               1       2.26       0.00                   n/a         n/a
slp              1       2.26       0.00                   n/a         n/a
spray            1       3.77       0.00                   n/a         n/a
  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)

car_percentual
protocolo        n      media     desvio                 IC95%   Shapiro p
epidemico        1     100.00       0.00                   n/a         n/a
flora            1     100.00       0.00                   n/a         n/a
sc               1     100.00       0.00                   n/a         n/a
slp              1     100.00       0.00                   n/a         n/a
spray            1     100.00       0.00                   n/a         n/a
  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)

overhead_copias
protocolo        n      media     desvio                 IC95%   Shapiro p
epidemico        1       7.20       0.00                   n/a         n/a
flora            1       1.81       0.00                   n/a         n/a
sc               1       1.00       0.00                   n/a         n/a
slp              1       1.00       0.00                   n/a         n/a
spray            1       1.41       0.00                   n/a         n/a
  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)

transmissoes
protocolo        n      media     desvio                 IC95%   Shapiro p
epidemico        1     252.00       0.00                   n/a         n/a
flora            1      58.00       0.00                   n/a         n/a
sc               1      26.00       0.00                   n/a         n/a
slp              1      26.00       0.00                   n/a         n/a
spray            1      38.00       0.00                   n/a         n/a
  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)

energia_total_j
protocolo        n      media     desvio                 IC95%   Shapiro p
epidemico        1       4.58       0.00                   n/a         n/a
flora            1       1.01       0.00                   n/a         n/a
sc               1       0.39       0.00                   n/a         n/a
slp              1       0.39       0.00                   n/a         n/a
spray            1       0.54       0.00                   n/a         n/a
  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)
  gravado: resultados/analise/analise_estatistica.csv
  gravado: resultados/analise/analise_estatistica.json

  aviso: sem dados suficientes para teste de hipotese (precisa de 2+ protocolos e 2+ execucoes por protocolo).
```

Arquivos gerados: `resultados/analise/analise_estatistica.csv` e `.json`.
### Interface grafica

Barra de menus com **Simulacao** (iniciar/pausar, passo unico, velocidade),
**Cenario** (C1/C2/C3), **Protocolo** (cinco protocolos), **Visao** (zoom),
**Camadas** (vinte e uma camadas ligaveis), **Frota**, **Exportar**,
**Carta Nautica** e **Ajuda**.

No canto direito da barra superior ficam **botoes** clicaveis, sempre
visiveis e sem passar por menu:

| Botao | Atalho | Efeito |
| --- | --- | --- |
| **-** | `-` | Um degrau mais devagar |
| **60** | | Indicador do ritmo pedido em passos por segundo real |
| **+** | `+` | Um degrau mais rapido |
| **Iniciar** / **Parar** | `Espaco` | Liga e congela a simulacao |
| **Passo** | `->` | Executa um unico passo de 10 s |
| **Reiniciar** | `R` | Zera o tempo com a mesma semente |

O botao principal muda de rotulo e de cor: verde para **Iniciar**, vermelho para
**Parar**. Iniciar e parar sao as acoes mais frequentes da interface, e o
menudropdown exigia dois cliques so para abrir.

A velocidade tambem ganhou botao, com o valor pedido entre os dois, porque
ajustar o ritmo e comum demais para exigir a abertura do menu *Simulacao*. Os
degraus sao 10, 30, 60, 120, 240, 480, 960 e 1920 passos por segundo real, e o
numero entre os botoes mostra o degrau selecionado, nao o que a maquina
consegue entregar: o ritmo real medido aparece no painel como *Ritmo real*. Nos
extremos o botao fica apagado e o aviso diz que ja esta no limite. O aviso da
mudanca e dado em segundos simulados por segundo real, que continua legivel nos
10 passos/s do piso, onde a leitura em horas arredondava para zero.

Clicar no titulo de um menu abre ou fecha aquele menu; clicar em outro titulo
troca direto para ele. `Esc` fecha o dropdown aberto e, se ja estiver fechado,
limpa a selecao.

Atalhos: `Espaco` iniciar/pausar | `->` passo unico | `R` reiniciar |
`C` carta | `Ctrl+S` salvar carta | `1`-`5` protocolo | `+` `-` `0` zoom |
`Esc` limpar selecao | `ESC` fechar menu.

O menu *Carta Nautica* gera a carta a partir do estado corrente da simulacao e
salva em PNG. As camadas controladas no menu valem tanto para a carta quanto
para o mapa.

O menu *Exportar* grava metricas, frota e configuracao separadamente, ou a
simulacao inteira em **Exportar simulacao completa (1 JSON)**, que e o arquivo
recomendado para analise posterior.

### Gateways de internet: fixos nas cidades e moveis nos navios

A entrega so fecha quando um no entrega a um gateway com acesso a internet. A
simulacao tem os dois tipos, porque a geografia do Amazonas exige os dois.

**Fixos, na cidade.** Dois terminais de terra, cada um ancorado na coordenada
real da cidade, e nao em um quilometro digitado a mao: `ancorar_cidades()`
projeta o ponto da cidade sobre o eixo do canal e devolve o quilometro
resultante. O desvio de cada cidade ao eixo e menor que 1 m.

| Cidade | Coordenada | Canal | km |
| --- | --- | --- | --- |
| Manaus | 3.1190 S, 60.0217 W | Principal | 0,0 |
| Itacoatiara | 3.1338 S, 58.4386 W | Principal | 208,9 |

**O canal de varzea do Careiro foi retirado do modelo.** Ele existia como um
segundo rio, com Careiro da Varzea e Autazes como terminais. A retirada tem
motivo medido, e nao estetico: o percurso do Careiro nao existe no OpenStreetMap
com fidelidade util. Ele so aparece com tolerancia de juncao de 6 km entre
trechos, e vem com nove vaos de mais de 5 km, o maior de 13,6 km. Um vao e uma
reta que o dado nao mediu, atravessando a mata, que e o oposto do que a
geometria real veio resolver. Ver `baixar_osm.selecionar_eixo`.

A funcao `listar_gateways()` em `flora_dtn.py` e a fonte unica de verdade sobre
os gateways do modelo: devolve os fixos (Manaus e Itacoatiara), os moveis (um
por embarcacao PRINCIPAL) e os cinco municipios excluidos, com coordenadas e
motivo. O motor a chama em `__init__` e o `exportar_simulacao` a grava no JSON.

**Municipios que ficam de fora, e por que.** A tese cita telecomunicacao em
Urucurituba, Silves, Itapiranga, Careiro da Varzea e Autazes, mas o criterio para
entrar no corredor e ter posicao real sobre o canal modelado. Os cinco ficam
registrados em `CIDADES_FORA_DO_CORREDOR`, com coordenada e motivo, em vez de
sumirem do codigo:

| Municipio | Coordenada | Motivo da exclusao |
| --- | --- | --- |
| Urucurituba | 3.1308 S, 58.1550 W | 31 km a jusante de Itacoatiara, fora do trecho modelado |
| Careiro da Varzea | 3.2208 S, 59.8258 W | no canal de Careiro, retirado do modelo |
| Autazes | 3.5801 S, 59.1306 W | no canal de Careiro, retirado do modelo |
| Silves | 2.8389 S, 58.2092 W | no rio Itacoatiara, a montante do corredor |
| Itapiranga | 2.7489 S, 58.0220 W | no rio Madeira, cerca de 340 km de Manaus |

O intervalo de longitude, de 60,10 W a 58,35 W, e a decisao de manter
Itacoatiara como ultima cidade sao a mesma escolha. Incluir Urucurituba daria
um corredor de 242 km, o que mudaria o comprimento modelado e exigiria reancorar
o obstaculo do cenario C3.

**Moveis, a bordo.** Cada embarcacao do tipo `PRINCIPAL` carrega um terminal de
backhaul que viaja com o casco. Sao quatro, com alcance de 15 km e cota de
subida propria.

Duas consequencias importam para o resultado:

1. **O terminal movel e lento, e e para isso que serve.** A cota de 20 bundles
   por hora e reposta com o tempo, um continuo, e nao liberada em rajada: com
   passos de 10 s, cada passo rende cerca de 0,055 bundle. Uma leitura quase
   nunca sobe no mesmo passo em que chegou. O que nao couber fica a bordo da
   embarcacao e pode ser servido no passo seguinte, ou mais adiante por outro
   terminal, e isso e fila de subida, nao perda de leitura. No mapa, o losango
   do gateway movel so fica cheio quando ha cota livre.
2. **A cobertura fixa nao cobre a rota, e nao pode cobrir.** No canal principal
   estao so Manaus e Itacoatiara, nas duas pontas. Com alcances de 8 km, os dois
   terminais fixos cobrem **7,7%** do canal principal e deixam um vao continuo
   de **192,9 km** entre os dois. Se substissemos os fixos
   por faixas ao longo de todo o percurso, o transporte store-carry-forward
   deixaria de ser necessario e os cinco protocolos colapsariam em LoRaWAN
   comum: a comparacao perderia sentido. Por isso as posicoes ficam esparsas de
   proposito, e nao por acaso.

A medicao de cobertura fixa ignora os moveis, que estao em lugar diferente a
cada passo; para o que eles acrescentam, o painel traz *Cobertura instantanea*,
a fracao da frota com ao menos um gateway em alcance em cada passo.

O efeito dos moveis, medido no cenario C3 com 168 h (semente 20260826):

| | TED | LPA | Cobertura instantanea | Transmissoes |
| --- | --- | --- | --- | --- |
| Com terminais moveis | 96,2% | 60,8 min | 70,4% | 10 306 |
| So terminais fixos | 91,8% | 101,5 min | 25,4% | 6 542 |

Ou seja, os moveis sobem a taxa de entrega em 4,4 pontos, cortam a latencia de
entrega em 40% e quase dobram a cobertura instantanea, porque a leitura encontra
um terminal antes de precisar de repasses longos. Eles reduzem o numero de
transmissoes, e nao o aumentam: com so os fixos nas pontas, a rede retransmite
mais vezes para emendar o vao de 164 km. Para rerodar a contraprutela, use
`tipos_gateway_movel=()` na configuracao; o teste
`test_desligar_gateways_moveis_preserva_o_reexperimento` faz exatamente isso.

### Status de coleta de cada embarcacao

**Clique em uma embarcacao** no mapa (ou em sua linha na lista *Frota* do
painel) para abrir uma ficha flutuante com o status de coleta daquela
embarcacao. A embarcacao selecionada ganha um anel pulsante, e o clique no vazio
ou `Esc` limpa a selecao.

A ficha mostra posicao e sentido de navegacao, calado contra profundidade local,
margem sob a quilha com a classe de risco, e entao a coleta propriamente dita:

* **coletas geradas** desde o inicio da simulacao;
* **a bordo agora**, em quantidade e em porcentagem do buffer, com destaque
  quando o buffer passa de metade;
* a quebra por tipo de leitura: **rotina**, **seguranca periodica** e
  **alerta de risco**, esta ultima em vermelho quando ha alerta a bordo;
* a idade da leitura mais antiga a bordo, que e o que limita a entrega tardia;
* quantas leituras a embarcacao ja entregou a um superno de internet, e se a
  informacao do proprio onboard ja chegou a tempo.

A ficha e rerasterizada so quando o texto muda, entao acompanhar a coleta de uma
embarcacao enquanto a simulacao corre nao custa tempo por quadro.

A lista *Frota* do painel rola com a roda do mouse sobre o painel, porque a
frota tem mais nos do que cabem na altura util. Acima da lista aparece o
intervalo visivel, por exemplo `4-13/15`.

### Zoom e navegacao

O fundo e um **mapa de tiles** (*slippy map*): a area visivel e montada a partir
de imagens de 256x256 px do nivel de zoom correspondente, como num mapa comum. O
zoom da visao vai de **1x a 6x** e cada dobra troca o nivel de tiles (1x usa
z10, 2x usa z11, 4x usa z12), de modo que aproximar mostra mais detalhe em vez
de esticar a mesma imagem.

| Gesto | Efeito |
| --- | --- |
| Roda do mouse | Aproxima/afasta ancorado no cursor |
| Botao direito | Afasta |
| Arrastar com botao esquerdo | Move a visao (pan) |
| Roda sobre o painel | Rola a lista de frota |
| `+` / `-` | Aproxima/afasta ancorado no centro |
| `0` | Reenquadra o mapa inteiro |

Arrastar e clicar sao desambiguados pelo andamento do cursor: abaixo de 4 px o
gesto e um clique e vale como selecao de embarcacao, acima disso e um arrasto.

O pan funciona em qualquer zoom, inclusive em **1x**. `Visao.limitar` deixa meia
tela de folga (`MARGEM_PAN = 0.5`) em volta do mundo, entao o mapa pode sair do
enquadramento como num mapa de verdade; sem essa folga o zoom 1 ocupava a janela
inteira e o mapa parecia travado. Pan so dentro da area do mapa; a barra de
menus e o painel lateral nao sao arrastaveis. A partir de 1,05x surge um
**minimapa** com o retangulo do viewport, e acima de 1,1x aparecem as marcas de
quilometro do canal principal.

O estilo padrao e o satelite **Esri World Imagery**. No menu Camadas, *Mapa de
ruas (OSM)* troca pelo **OpenStreetMap** e *Mapa online (tiles detalhados)*
liga/desliga a rede. Com o mapa online ligado, um tile que falte e baixado em
segundo plano (sem travar o quadro) e guardado em `mapa_tiles_satelite/` ou
`mapa_tiles/`; desligado, o simulador usa apenas o que ja esta em disco e
continua rodando sem rede. Os tiles locais vao ate z10, entao no modo offline os
zooms maiores ampliam esse tile; com rede, z11 e acima sao baixados sob demanda.
O credito do provedor e desenhado no canto inferior esquerdo do mapa, como as
licencas das imagens exigem.

O mosaico visivel e cacheado por (camada, nivel de zoom, faixa de tiles, versao
do cache): parado, o fundo nao e remontado; ao arrastar, so a faixa que muda de
tiles e recomposta. A folha de carta continua sendo montada numa base de
**2000x1200** (`RES_BASE = 2`), e e o fundo de reserva quando nao ha tiles.

### Camadas

As vinte e uma camadas, na ordem de composicao: **carta nautica**, satelite,
batimetria, rotas, **efeitos de rota**, **fluxo da rota**, waypoints, obstaculos,
supernos, contatos, frota, **marcas de km**, **minimapa**, malha da frota,
nomes, risco de calado, contorno da rota, **curvas de cote**, **sondagens**,
**limites do canal** e **relevo sombreado**.

A janela abre com o **satelite** ligado: a foto e o fundo padrao, e a *carta
nautica* e o fundo alternativo, nao uma camada empilhada por cima. Ligar uma
desliga a outra, e sem os tiles em disco o simulador cai para a folha de carta
em vez de mostrar um retangulo de uma cor so.

No menu Camadas ficam ainda dois controles do fundo, que nao entram na conta das
vinte e uma camadas porque nao sao sobreposicoes: **Mapa online (tiles
detalhados)** libera o download dos tiles que faltam e **Mapa de ruas (OSM)**
troca o satelite pelo mapa de ruas do OpenStreetMap. A atribuicao do provedor
aparece no proprio mapa.

A *carta nautica* substitui o preenchimento do rio: terra ocre, agua em rampa de
profundidade, linhas de cote e numeros de sondagem. As quatro ultimas camadas
sao as partes dela que se ligam e desligam separadamente.

`efeitos de rota` e a faixa navegavel com borda escura e eixo creme, em quatro
passes; `fluxo da rota` sao tracos claros que correm **a jusante** e mostram o
sentido da corrente. Ambos podem ser desligados para deixar o mapa mais limpo.
O rio e desenhado para ler tanto sobre a foto escura quanto sobre a carta clara,
entao o que separa a faixa navegavel do resto e a borda e o eixo, e nao brilho.

Na camada *supernos*, fixo e movel sao desenhados de forma diferente: o gateway
de terra e um **quadrado verde cheio** na cidade, e o terminal a bordo e um
**losango laranja** que viaja com a embarcacao que o carrega. O losango fica
vazado e apagado enquanto o terminal nao tem cota de subida livre, de modo que o
gargalo de backhaul fica visivel no mapa sem precisar ler numero nenhum.

### Icones das embarcacoes

Cada no da frota e desenhado como uma silhueta orientada pelo rumo real, com
proporcoes proprias por tipo:

| Tipo | Comp. x beam (px em 1x) | Cor |
| --- | --- | --- |
| `PRINCIPAL` (navio/balsa de recreio) | 26 x 15 | azul |
| `LANCHA` (lancha rapida) | 19 x 11 | magenta |
| `RIBEIRINHO` (barco ribeirinho) | 15 x 13 | cinza |

O casco gira com a tangente do canal e inverte quando o no desce o rio. A proa
usa a posicao na polilinha do canal, o que mantem o rumo correto mesmo quando o
deslocamento ao longo do canal e pequeno em relacao ao deslocamento lateral.

## Desempenho

Medido em `flora_ui.py` com 1000x644 de mapa, cenario C2, arrastando 1,5 px por
quadro para invalidar os caches como um pan real:

| Zoom | Custo por quadro | FPS |
| --- | --- | --- |
| 1,0x | 14,3 ms | 70 |
| 2,0x | 15,4 ms | 65 |
| 4,0x | 10,7 ms | 94 |
| 6,0x | 10,0 ms | 100 |

As principais medidas: cache da malha de distancias ao eixo em
`flora_cenario.py` (197 ms para 0,3 ms por chamada de profundidade), leito, halo
e fluxo compostos numa unica superficie alpha e um unico blit, recorte do fundo
cacheado por quadro e mosaico de tiles cacheado por nivel e faixa. No zoom 1 a
area visivel cobre mais tiles e e o caso mais caro; os zooms maiores recortam
uma faixa menor da imagem.

A carta nautica entra com um custo proprio: ~340 ms para reconstruir a folha de
2000x1200, sendo ~150 ms da malha de distancias, ~100 ms do relevo e ~60 ms das
curvas de cote. Ela e cacheada por faixa de 6 h simuladas, entao esse custo
aparece a cada 6 h do modelo e nao a cada quadro. Se o custo incomodar, as
camadas `relevo` e `curvas` podem ser desligadas sem afetar agua e costa.

A velocidade de simulacao e limitada por tempo (`ORCAMENTO_PASSOS = 0,005` s por
quadro) em vez de passos fixos. Um passo de FLoRA custa cerca de 4,5 ms e o
desenho cerca de 7 ms, entao o orcamento mantem a interface em 60 fps mesmo com a
simulacao rodando; quando a maquina nao alcanca a vazao pedida, o painel mostra
`Ritmo real`, a vazao efetivamente medida, em vez de travar. Rodando a 480
passos/s pedidos, a simulacao entrega cerca de 12 h simuladas por segundo real.

A grade de distancias ao eixo e cacheada por resolucao e o resultado e
bit-identico ao calculo direto, o que mantem a reprodutibilidade dos
experimentos.

## Carta nautica

A carta e desenhada a partir da batimetria do proprio simulador, e nao de uma
imagem estatica. A agua do modelo e reprojetada no espaco do desenho e
colorida por rampa de profundidade; a linha de costa sai da secao transversal
dos canais, e as curvas de cote sao as isolinhas de 2, 5, 10, 20 e 30 m, com os
valores pares em traco reforcado.

**Por que a linha de costa nao vem de um limiar de altura.** A primeira versao
separava terra e agua por profundidade, como se faz num levantamento batimetrico
de verdade, e nao podia funcionar. O modelo nao tem topografia: o perfil
transversal de cada canal termina em 0,4 m no leito principal e 0,3 m no canal de
varzea, e esse valor se repete identico por todo o resto do quadro, porque a
floresta de varzea e um plano. Como a profundidade e `perfil + nivel do rio` e o
nivel oscila 0,35 m por dia, qualquer limiar entre 0,4 e 0,8 m classificava a
varzea inteira como agua rasante no pico da mare e como terra na vazante.
Medido no C3, a fracao de agua no quadro saltava de 19% para 100% conforme a
hora, e a carta piscava.

Por isso a agua vem do canal: uma celula e agua quando esta dentro da secao
transversal que o modelo descreve, e terra quando esta fora. A faixa e uma
propriedade da geometria, e o nivel do rio entra so na cor, que e o que ele de
fato informa. Medido agora, o trecho de agua do quadro e 21,2% em C1, C2 e C3,
com variacao de 0,01 ponto percentual ao longo de 168 h de simulacao.

Os niveis de cote sao esparsos de proposito. O gradiente transversal e tao forte
que curvas como 1, 2 e 3 m ficariam a poucos pixels uma da outra e a carta sairia
riscada de preto em vez de legivel.

| Onde | Funcao ou opcao |
| --- | --- |
| Folha completa, com titulo, legenda e margens | `desenhar_folha_carta(cenario, t_h, (largura, altura))` |
| Mapa, sem folha | `CartaNautica(OpcoesCarta(...)).render(...)` |
| Profundidade e faixa de agua na grade | `flora_cenario.grade_leito(cenario, t_h, nx, ny)` |
| Regra da faixa de agua | `flora_cenario.mascara_agua(indice, dists)` |
| Partes desligaveis | `OpcoesCarta(curvas=..., sondagens=..., relevo=..., limites_canal=...)` |
| Legenda e caixa do titulo | `_desenhar_legenda`, `_desenhar_caixa_titulo` |

O relevo sombreado em terra e **ilustrativo**: e um campo deterministico para dar
planura ao fundo ocre, nao uma medicao de relevo, e a legenda diz isso. Curvas,
sondagens, faixa de agua e cor da agua vem todos do modelo.

O comando `carta` exporta a folha em PNG, e `--carta` liga a mesma coisa na
execucao em lote. A base da tela e cacheada por faixa de 6 h simuladas, entao o
custo de ~350 ms por reconstrucao aparece a cada 6 h do modelo e nao a cada
quadro.

## Cenarios hidrologicos

| Codigo | Nome | Descricao |
| --- | --- | --- |
| C1 | Normal | Nivel de referencia, sem obstaculos mapeados. |
| C2 | Vazante | Nivel 8 m abaixo da referencia; 12 baixios sazonais expostos. |
| C3 | Terra Caida | Desmoronamento no km 170 no dia 3; o leito passa de 15 m a 2,5 m. |

O risco de cada embarcacao e a margem sob quilha (profundidade local menos o
calado): **critico** abaixo de 0,5 m, **atencao** abaixo de 1,5 m. Como o leito
residual de C3 fica em 2,5 m, so as embarcacoes `PRINCIPAL` (calado 2,5 m)
entram em zona de risco no km 170.

O obstaculo do C3 continua no km 170 porque foi ai que a tese o colocou. Vale a
ressalva, ja que o percurso mudou de escala e de origem: o trecho modelado vai
de Manaus a Itacoatiara e mede **208,9 km** no eixo real do OpenStreetMap,
contra os 180 km do spline antigo. O km 170 e, portanto, 81% do modelo, e o
texto do trabalho fala em cerca de 270 km, que e 1,29 vez o modelo. Os 12
baixios do C2 estao entre 12 e 155 km e continuam dentro do canal.

O valor de 270 km merece conferences antes de virar numero no texto. A distancia
geodesica direta entre as duas cidades e 175,8 km, e o eixo medido da 208,9 km.
A diferenca para 270 km pode ser o percurso ate Urucurituba e a jusante, que o
modelo nao inclui, ou um trecho de aguas diferentes. Nao e um numero que se
corrige por ajuste fino do mapa: e uma definicao de corredor que precisa ser
feita.

> **Nota.** O corredor modelado mede 208,9 km. O artigo cita 270 km; a
> diferença corresponde ao trecho até Urucurituba e a jusante, que o modelo
> não inclui.

## Metricas

`TED` (taxa de entrega), `LPA` (latencia percentil de atraso), `CAR` (cobertura
autoral de rota), `TCI` (tempo de convergencia da informacao), `overhead` de
copias, saltos medios, airtime, energia, duty cycle, retransmissoes suprimidas e
uploads redundantes. As metricas de gateway entram na mesma serie:
`cobertura_gateway_percentual` (soma dos alcances fixos sobre o canal
principal), `maior_vao_gateway_km` (o maior trecho sem terminal fixo),
`cobertura_instantanea_media` (media da fracao da frota com gateway em
alcance) e `gateways_moveis` (quantos terminais a bordo). Os CSV ficam em
`resultados/`.

## Saidas

* `<base>_metricas.csv` — serie temporal das metricas;
* `<base>_frota.csv` — estado por embarcacao;
* `<base>_config.json` — configuracao completa, para reproduzir o experimento;
* `<base>_simulacao.json` — **um arquivo unico** com resumo, configuracao,
  frota, supernos, series e amostras brutas;
* `logs/flora_<data>_<pid>.log` — log da execucao;
* `resultados/analise/analise_estatistica.csv` e `.json` — agregado do modo
  `analisar`;
* `cartas/*.png` — cartas nauticas;
* `exemplos/` — execucao C2 de 2 h para os cinco protocolos, versionada como
  referencia de formato (nao e saida de uma execucao recente).

A semente fixada torna cada execucao reproduzivel: mesma semente, mesmo
cenario, mesmo protocolo e mesmo horizonte produzem resultados identicos. O
modo paralelo foi verificado contra o sequencial e grava CSV byte-identicos.

## Validacao rapida

Para testar o simulador sem rodar 168 h, use `--dry-run`:

```bash
python dtn_simulador.py rodar --dry-run
python dtn_simulador.py comparar --dry-run
python dtn_simulador.py analisar --dry-run
```

O dry-run usa horizonte de 0,1 h, semente 20260826, nao grava CSV nem JSON
e nao cria arquivo de log; apenas imprime o resumo na tela. Funciona em todos
os subcomandos, inclusive `gui`, `carta` e `artigo`.

## Testes

```bash
python tests/test_simulador.py            # suite principal, sem dependencias extras
python -m pytest tests -q                 # principal + fumaca
python -m pytest tests/test_fumaca.py -q  # so a fumaca
```

`tests/test_simulador.py` valida o modelo: geometria, batimetria, LoRa,
invariantes do motor, reprodutibilidade, carta e interface. Roda sozinho
(85 testes) e tambem sob pytest.

`tests/test_fumaca.py` valida os caminhos de entrada em poucos segundos:
`--version`, `rodar` com log, `comparar --paralelo`, `analisar` com Friedman e
Holm, a degradacao do commit sem git e a importacao dos modulos. Ele roda o
horizonte minimo de proposito; nao repete a validacao fisica.

## Estrutura

| Arquivo | Responsabilidade |
| --- | --- |
| `flora_geometria.py` | Canais, escala fisica, conversoes geodesicas, distancias ao eixo, ancoragem das cidades e cobertura de gateway. |
| `flora_cenario.py` | Cenarios C1/C2/C3, batimetria, nivel do rio, risco de calado. |
| `flora_lora.py` | Camada fisica LoRa: airtime, energia, duty cycle. |
| `flora_dtn.py` | Bundles, protocolos, supernos fixos e moveis, frota, metricas e motor. |
| `flora_mapa.py` | Mosaico de tiles, batimetria em cor, carta nautica e folha com legenda. |
| `flora_tiles.py` | Mapa de tiles XYZ: projecao Web Mercator, cache em memoria/disco e download sob demanda. |
| `flora_ui.py` | Interface pygame. |
| `flora_versao.py` | Versao e resolucao do commit (`FLORA_COMMIT`, git, `COMMIT`, fallback). |
| `flora_log.py` | Logging em arquivo por execucao. |
| `flora_analise.py` | Leitura dos CSV de metricas, IC95%, Shapiro-Wilk, ANOVA/Friedman e Holm. |
| `dtn_simulador.py` | Ponto de entrada (gui, rodar, carta, comparar, analisar). |
| `executar.bat` / `executar.ps1` | Launchers para Windows, sem aspas aninhadas. |
| `tests/test_simulador.py` | Suite principal do modelo. |
| `tests/test_fumaca.py` | Testes de fumaca da CLI, do log e da analise. |
| `exemplos/` | Saidas de referencia do cenario C2 (2 h, cinco protocolos). |

`flora_geometria.py`, `flora_cenario.py`, `flora_lora.py`, `flora_dtn.py`,
`flora_mapa.py` e `flora_tiles.py` **nao importam pygame**: a geometria avaliada
no experimento e a mesma exibida na tela e na carta.

## Base cartografica

Os tiles de satelite ficam em `mapa_tiles_satelite/` (`z_x_y.jpg`) e os do mapa
de ruas em `mapa_tiles/` (`z_x_y.png`). Os conjuntos locais vao ate z10 e sao o
caminho **off-line**: sem rede, o mapa usa esses arquivos e amplia os niveis que
nao existem em disco. Com *Mapa online* ligado, `flora_tiles.py` baixa sob
demanda os tiles que faltam, em segundo plano, e os grava nas mesmas pastas;
assim a segunda visita ao mesmo lugar ja nao depende da rede. Sem tiles
utilizaveis, a carta e o mapa caem num fundo procedural neutro e nenhuma outra
camada e afetada.

O mosaico cobre 3 colunas por 4 linhas, cerca de 1536x1024 px, e enquadra
aproximadamente as latitudes 2.4602 S a 3.8643 S e as longitudes 60.1172 W a
58.0078 W. A geografia do corredor foi auditada contra ele.

O satelite **nao** fornece o eixo dos canais. A tentativa de extrair o rio por
segmentacao de luminancia foi abandonada: os centros urbanos tem luma alto e
sao classificados como agua, as mascaras por limiar devolvem 3 a 5% de pixels de
agua, e o rastreamento dinamico salta entre lagoas e areas escuras em vez de
seguir o leito.

### O eixo do rio vem do OpenStreetMap

O que substituiu os marcos e a geometria do proprio rio, extraida da Overpass
API. `baixar_osm.py` monta um grafo dos extremos das vias terminais de 2 km,
acha o menor caminho entre as pontas com Dijkstra, costura os trechos e
ancora as extremidades nas coordenadas exatas de Manaus e Itacoatiara. O
resultado vai para `dados_osm/eixo_rio.json` e e lido por `flora_osm.py` no
inicio do programa; `flora_geometria.py` so usa a spline Catmull-Rom se o
arquivo nao existir, o que mantem o simulador rodando sem rede.

Duas consequencias aparecem nos numeros e vale a pena saber de onde vem cada um:

* **O corredor passou de 202 para 208,9 km.** O eixo antigo tinha 67 pontos
  tambem, mas interpolados: razao reta/percurso de 0,998, ou seja, uma linha
  reta desenhada com 67 vertezes. O eixo do OSM da 0,841, com o rio descendo
  32 km em latitude entre as duas cidades. O comprimento maior e o honesto.
* **A mascara de agua passou a acompanhar o leito.** A agua vem do eixo real,
  entao a faixa nao precisa ser desenhada a mao ao redor de uma reta.

### A escala da carta e a mesma nos dois eixos

O canvas e a janela geografica tinham aspectos diferentes: 1000x600 px para
194,5 km de longitude por 121,6 km de latitude. Isso dava 194,5 m/px em X contra
202,7 m/px em Y, e o modelo media quase tudo em pixels, entao a diferenca de
4,2% aparecia em todo comprimento, alcance e raio. O canal media 211,2 km
contra os 209,0 km que o GeoJSON tem.

`ALTURA_TELA_BASE` passou a ser derivada do aspecto da janela, e nao mais um
numero escolhido a mao. O canvas virou 1000x625 com 194,6 m/px nas duas
direcoes, e o canal mede 208,9 km contra 209,0 km do dado, erro de 0,04%. Os
testes `test_a_carta_e_isotropica`, `test_comprimento_do_canal_bate_com_o_dado`
e `test_projecao_faz_ida_e_volta` travam esse ponto.

A ODbL 1.0 exige credito no derivado, entao `flora_osm.credito_carta()` escreve
`Geometria do rio: (c) OpenStreetMap contributors, ODbL 1.0, via Overpass API` no
rodape de toda carta exportada, e o `json` gravado em `dados_osm/` traz
`attribution` e `license` com o mesmo texto.

## Estado atual

Rodando `python tests/test_simulador.py`, a suíte dá **85/85**; com
`python -m pytest tests -q`, **102/102** (85 do modelo + 17 de fumaca). Vale
registrar o que ainda nao esta resolvido, porque sao questoes de tese e nao de
codigo:

* **O numero de gateways.** Com o canal do Careiro fora, sobraram dois terminais
  fixos, Manaus e Itacoatiara, nas pontas do corredor. A discussao anterior
  tratava de cinco. Os municipios de Urucurituba, Silves e Itapiranga seguem em
  `CIDADES_FORA_DO_CORREDOR` com o motivo de cada exclusao. A decisao de quantos
  gateways usar e do argumento, e nao do mapa.
* **Os 270 km do texto.** O modelo mede 208,9 km. Se o artigo citar 270 km, ou o
  corredor vai ate Urucurituba, ou os 270 km sao outra unidade de percurso, e
  isso precisa ser resolvido antes de virar numero na comparacao.

## Licenca e citacao

O codigo do simulador e distribuido sob a **licenca MIT** (ver `LICENSE`),
copyright 2026 Antonio Alberto (ICET/UFAM). A licenca MIT cobre o codigo, nao
substitui as licencas dos dados de terceiros:

* geometria do rio: © OpenStreetMap contributors, **ODbL 1.0**, via Overpass API;
* tiles de satelite: © Esri e provedores associados;
* tiles de ruas: © OpenStreetMap contributors, **ODbL 1.0**.

O arquivo `CITATION.cff` (Citation File Format 1.2.0) descreve a versao 1.1.0
e permite que GitHub, Zenodo e gerenciadores de referencia gerem a citacao
automaticamente. Para citar em texto:

> ALBERTO, Antonio. **FLoRA-DTN: Simulador de Rede Cooperativa Oportunistica
> para Transporte Fluvial na Amazonia**. Versao 1.1.0. Manaus: UFAM/ICET, 2026.

Ao publicar resultados, informe tambem a semente, o cenario, o horizonte e o
commit impresso no banner: e o conjunto que torna a execucao reproduzivel.

