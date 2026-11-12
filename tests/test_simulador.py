"""
Testes do simulador FLoRA-DTN.

Rodaveis de dois jeitos, sem dependencia extra:

    python tests/test_simulador.py
    pytest tests

Cobrem a geometria e a escala fisica, a batimetria dos tres cenarios, a camada
LoRa, as invariantes do motor, a reprodutibilidade e a geracao da carta
nautica. Os horizontes sao curtos de proposito: os testes validam invariantes,
nao o desempenho.
"""

from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import numpy as np
from PIL import Image
import flora_cenario as fc

import flora_dtn as fd
import flora_geometria as fg
import flora_lora as fl
import flora_osm
import flora_tiles


# ---------------------------------------------------------------------------
# 1. GEOMETRIA E ESCALA
# ---------------------------------------------------------------------------
def test_conversao_geografica_e_invertivel():
    for lat in (-2.7, -3.1, -3.6):
        for lon in (-60.0, -59.2, -58.4):
            x, y = fg.geo_para_mundo(lat, lon)
            lat2, lon2 = fg.mundo_para_geo(float(x), float(y))
            assert abs(lat - lat2) < 1e-9
            assert abs(lon - lon2) < 1e-9


def test_bbox_dentro_do_canvas():
    for lat, lon in ((fg.LAT_TOP, fg.LONG_LEFT), (fg.LAT_BOTTOM, fg.LONG_RIGHT)):
        x, y = fg.geo_para_mundo(lat, lon)
        assert 0 <= x <= fg.LARGURA_SIMULACAO_BASE + 1e-9
        assert fg.ALTURA_MENU_SUP <= y <= fg.ALTURA_MENU_SUP + fg.ALTURA_TELA_BASE + 1e-9


def test_escala_fisica_plausivel():
    # a janela tem 194,5 km por 1000 px, e a altura do canvas e derivada dela
    assert 0.15 < fg.KM_POR_PX < 0.25


def test_a_carta_e_isotropica():
    """
    Um km por pixel em X tem de ser o mesmo que em Y.

    Com o canvas em 1000x600 e a janela em 194,5 x 121,6 km, as escalas ficavam
    194,5 e 202,7 m/px: 4,2% de diferenca, e todo o modelo media distancia em
    pixels. O canal dava 211,2 km contra os 209,0 km do dado. A altura do canvas
    passou a ser derivada do aspecto da janela, entao o teste trava aqui.
    """
    assert abs(fg.KM_POR_PX_X - fg.KM_POR_PX_Y) / fg.KM_POR_PX < 0.01


def test_comprimento_do_canal_bate_com_o_dado():
    """
    A polilinha do modelo mede o mesmo que a polilinha do arquivo.

    E o teste que fecha a conta da projecao. O comprimento em km vem de uma soma
    de distancias euclidianas em pixels vezes a escala; se a escala ou a
    conversao de coordenadas estivessem erradas, aqui apareceria a diferenca.
    """
    import json
    with open(os.path.join(RAIZ, "dados_osm", "eixo_rio.json"), encoding="utf-8") as fh:
        gj = json.load(fh)
    coords = [f["geometry"]["coordinates"] for f in gj["features"]
              if f["properties"].get("canal") == "principal"][0]
    pontos = [(la, lo) for lo, la in coords]
    medido = sum(fg.distancia_haversine_km(*pontos[i], *pontos[i + 1])
                 for i in range(len(pontos) - 1))
    modelo = fg.CANAL_PRINCIPAL.comprimento_km
    assert abs(modelo - medido) / medido < 0.01, \
        f"modelo {modelo:.2f} km contra dado {medido:.2f} km"


def test_projecao_faz_ida_e_volta():
    """geo_para_mundo e mundo_para_geo sao inversas, sem deriva."""
    for lat, lon in ((-3.119, -60.022), (-3.35, -58.44), (-3.0, -59.5)):
        la, lo = fg.mundo_para_geo(*fg.geo_para_mundo(lat, lon))
        assert abs(la - lat) < 1e-9
        assert abs(lo - lon) < 1e-9


def test_corredor_cabe_no_canvas():
    """O eixo inteiro tem de cair dentro do quadro, nas duas pontas."""
    c = fg.CANAL_PRINCIPAL
    xs, ys = c.pontos_mundo[:, 0], c.pontos_mundo[:, 1]
    assert xs.min() > 0 and xs.max() < fg.LARGURA_SIMULACAO_BASE
    assert ys.min() >= fg.ALTURA_MENU_SUP
    assert ys.max() < fg.ALTURA_MENU_SUP + fg.ALTURA_TELA_BASE


# ---------------------------------------------------------------------------
# EIXO REAL DO OPENSTREETMAP
# ---------------------------------------------------------------------------
def test_eixo_real_esta_carregado():
    """
    O simulador tem de usar a geometria do OSM, nao o spline dos marcos.

    Este e o teste que impede a regressao central do projeto. Sem o cache, ou
    com o cache ignorado, o canal volta a ser uma spline por quatro marcos, e o
    resultado e uma linha reta com razao reta/percurso de 0,998: bonito e falso.
    """
    assert fg.GEOMETRIA_DO_OSM, "o cache do OSM existe mas nao foi usado"
    assert fg._EIXO_OSM is not None
    assert fg._EIXO_OSM.shape[0] >= 8


def test_eixo_do_osm_tem_meandros_de_verdade():
    """
    O eixo precisa se desviar da linha reta, e nao so bater nas duas cidades.

    Este e o teste que mede o defeito corrigido. O spline dos marcos dava razao
    reta/percurso de 0,998, ou seja, 0,2% de desvio: na carta, uma reta. O eixo
    do OSM da 0,841, e uma linha reta com 0,999 de razao nao pode passar aqui.
    """
    canal = fg.CANAL_PRINCIPAL
    pts = canal.pontos_geo
    reta = fg.distancia_haversine_km(*pts[0], *pts[-1])
    razao = reta / canal.comprimento_km
    assert 0.6 < razao < 0.97, f"razao reta/percurso {razao:.3f} nao tem meandro"


def test_eixo_nao_sai_do_corredor():
    """
    O rio pode ser sinuoso, mas nao pode fazer arco largo fora da faixa.

    Meandro e desvio lateral sao coisas diferentes: o Amazonas serpenteia dentro
    do vale, e um arco de 100 km cortando a floresta seria outro rio. O teste
    mede a distancia maxima de cada ponto a reta entre as pontas, que e como o
    desvio se manifesta quando o corredor e comprido e estreito.
    """
    pts = fg.CANAL_PRINCIPAL.pontos_geo
    (la0, lo0), (la1, lo1) = pts[0], pts[-1]
    maximo = 0.0
    for lat, lon in pts:
        # ponto projetado na reta entre as duas pontas, por parametrizacao
        t = 0.0
        melhor = float("inf")
        for k in range(201):
            u = k / 200.0
            plat = la0 + (la1 - la0) * u
            plon = lo0 + (lo1 - lo0) * u
            d = fg.distancia_haversine_km(lat, lon, plat, plon)
            if d < melhor:
                melhor, t = d, u
        maximo = max(maximo, melhor)
    assert maximo < 40.0, f"desvio lateral de {maximo:.1f} km da linha Manaus-Itacoatiara"


def test_pontas_do_eixo_estao_nas_cidades():
    """Manaus e Itacoatiara sao as duas pontas do eixo, nas coordenadas reais."""
    canal = fg.CANAL_PRINCIPAL
    for chave, nome in fg.SUPERNOS_CIDADE:
        lat, lon = fg.COORDENADAS_ROTA_NAVEGACAO[chave]
        d = fg.distancia_haversine_km(*canal.pontos_geo[0], lat, lon)
        d_fim = fg.distancia_haversine_km(*canal.pontos_geo[-1], lat, lon)
        assert min(d, d_fim) < 0.5, f"{nome} a {min(d, d_fim):.2f} km da ponta do eixo"


def test_cache_ausente_cai_para_o_spline_sem_quebrar():
    """
    Sem o arquivo do OSM o programa precisa abrir, so que com o eixo antigo.

    O fallback importa: o cache e gerado por rede, e quem rodar o codigo em uma
    maquina sem `dados_osm/eixo_rio.json` nao pode receber um traceback.
    """
    inexistente = os.path.join(RAIZ, "dados_osm", "nao_existe.json")
    assert flora_osm.carregar_eixo("principal", inexistente) is None
    # e um cache sem a linha pedida tambem, em vez de devolver um eixo vazio
    assert flora_osm.carregar_eixo("careiro") is None


def test_cache_invalido_avisa_e_devolve_none(tmp_path=None):
    """Cache corrompido passa em silencio? Nao: avisa e devolve None."""
    import tempfile
    with tempfile.TemporaryDirectory() as pasta:
        ruim = os.path.join(pasta, "ruim.json")
        with open(ruim, "w", encoding="utf-8") as fh:
            fh.write("{isto nao e json")
        assert flora_osm.carregar_eixo("principal", ruim) is None
        curto = os.path.join(pasta, "curto.json")
        with open(curto, "w", encoding="utf-8") as fh:
            fh.write('{"features": [{"properties": {"canal": "principal"},'
                     ' "geometry": {"type": "LineString",'
                     ' "coordinates": [[-60.0, -3.1], [-59.9, -3.1]]}}]}')
        assert flora_osm.carregar_eixo("principal", curto) is None


def test_atribuicao_da_odbl_e_oferecida():
    """A ODbL exige credito no derivado, entao o texto tem de existir."""
    if flora_osm.tem_cache():
        credito = flora_osm.credito_carta()
        assert "OpenStreetMap" in credito
        assert "ODbL" in credito


def test_modelo_tem_um_canal_so():
    """
    O canal de varzea do Careiro foi retirado do modelo.

    O motivo esta em `baixar_osm.selecionar_eixo`: o percurso do Careiro nao
    existe no OSM com fidelidade util, e um vao e uma reta que o dado nao mediu.
    O teste existe para a retirada nao voltar por acidente, e para as cidades
    que perderam o canal ficarem registradas com o motivo.
    """
    assert len(fg.CANAIS) == 1
    assert fg.ROTAS_DISPONIVEIS == [fg.CANAL_PRINCIPAL_NOME]
    assert not hasattr(fg, "CANAL_CAREIRO")
    fora = {c["cidade"] for c in fg.CIDADES_FORA_DO_CORREDOR}
    assert "Careiro da Varzea" in fora
    assert "Autazes" in fora
    chaves = {c for c, _n in fg.SUPERNOS_CIDADE}
    assert chaves == {"Manaus", "Itacoatiara"}


def test_distancia_ao_eixo_no_ponto_do_eixo():
    # `posicao_em` interpola dentro do trecho, e nao no vertice mais proximo;
    # a formula de distancia tem cancelamento numerico nessa escala, entao o
    # criterio e de milimetros (1e-6 km) para cima, nao de exatidao de bit
    p = fg.CANAL_PRINCIPAL.posicao_em(50.0, 0.0)[0]
    assert fg.CANAL_PRINCIPAL.distancia_ao_eixo_km(p) < 1e-4


def test_distancia_ao_eixo_cresce_com_o_desvio():
    canal = fg.CANAL_PRINCIPAL
    dist = [canal.distancia_ao_eixo_km(canal.posicao_em(90.0, d)[0]) for d in (0.0, 1.0, 3.0, 6.0)]
    assert dist == sorted(dist)
    assert abs(dist[0]) < 1e-6
    assert dist[-1] > 3.0


def test_posicao_em_interpola_dentro_do_trecho():
    """
    O km entre dois vertices tem de cair no meio do trecho, e nao no vertice.

    Com `searchsorted` do lado esquerdo, `posicao_em` escolhia o vertice *final*
    do trecho e o casco ficava preso nele ate o km cruzar o vertice seguinte.
    Nos trechos longos do eixo do OSM isso era um salto de quilometros, que
    aparecia como tremor na tela.
    """
    canal = fg.CANAL_PRINCIPAL
    km = float(canal.km_acumulado[20])
    i = canal.indice_no_km(km)
    km_i, km_j = canal.km_acumulado[i], canal.km_acumulado[i + 1]
    meio = (km_i + km_j) / 2.0
    p = canal.posicao_em(meio, 0.0)[0]
    a, b = canal.pontos_mundo[i], canal.pontos_mundo[i + 1]
    esperado = a + (b - a) * ((meio - km_i) / (km_j - km_i))
    assert np.allclose(p, esperado, atol=1e-6), (
        f"km {meio:.3f} nao interpolou entre os vertices {i} e {i + 1}")
    assert np.linalg.norm(p - a) > 1e-3 and np.linalg.norm(p - b) > 1e-3, \
        "a posicao ficou presa em um dos vertices do trecho"


def test_distancia_em_lote_bate_com_ponto_a_ponto():
    canal = fg.CANAL_PRINCIPAL
    pts = np.column_stack([np.linspace(0, 1000, 40), np.linspace(40, 640, 40)])
    lote = canal.distancias_ao_eixo_km(pts)
    unit = np.array([canal.distancia_ao_eixo_km(p) for p in pts])
    assert np.allclose(lote, unit, atol=1e-9)
    assert len(lote) == 40


def test_lote_vazio_nao_falha():
    assert len(fg.CANAL_PRINCIPAL.distancias_ao_eixo_km([])) == 0


# ---------------------------------------------------------------------------
# 2. CENARIOS E BATIMETRIA
# ---------------------------------------------------------------------------
def test_c1_e_nivel_de_referencia():
    c = fc.obter_cenario("C1")
    assert c.nivel_rio_m(0.0) == 0.0
    assert c.obstaculos_ativos(0.0) == []


def test_c2_rebaixa_o_rio():
    c = fc.obter_cenario("C2")
    assert c.nivel_rio_m(0.0) < 0.0
    p = fg.geo_para_mundo(-3.2, -58.9)
    # a rebaixamento afunda menos a calha, mas nunca a torna negativa
    assert c.profundidade_m(p, 0.0) >= 0.0
    assert c.profundidade_m(p, 0.0) < fc.obter_cenario("C1").profundidade_m(p, 0.0)


def test_c2_expoe_baixios_e_c1_nao():
    assert len(fc.obter_cenario("C2").obstaculos_ativos(0.0)) == 12
    assert fc.obter_cenario("C1").obstaculos_ativos(0.0) == []


def test_c3_terra_caida_so_ativa_depois_de_72h():
    c = fc.obter_cenario("C3")
    assert c.obstaculos_ativos(71.0) == []
    assert len(c.obstaculos_ativos(73.0)) == 1


def test_c3_reduz_o_leito_sobre_a_terra_caida():
    c = fc.obter_cenario("C3")
    obst = c.obstaculos[0]
    antes = c.profundidade_m(obst.posicao_px, 71.0)
    depois = c.profundidade_m(obst.posicao_px, 73.0)
    assert antes > 25.0, f"antes da queda o leito devia ser fundo, veio {antes:.1f} m"
    # no nucleo da depressao resta a profundidade residual do desmoronamento
    assert abs(depois - obst.profundidade_residual_m) < 1.0
    assert 0.0 < depois < 6.0


def test_grade_bate_com_ponto_a_ponto():
    c = fc.obter_cenario("C3")
    prof, lats, lons = fc.grade_profundidade(c, 73.0, 40, 30)
    assert prof.shape == (30, 40)
    for iy in (0, 15, 29):
        for ix in (0, 20, 39):
            p = fg.geo_para_mundo(float(lats[iy]), float(lons[ix]))
            assert abs(prof[iy, ix] - c.profundidade_m(p, 73.0)) < 1e-9


def _grade_sem_cache(cenario, t_h, nx, ny):
    """Replica a grade resolvendo a distancia em cada celula, sem cache."""
    lons = np.linspace(fg.LONG_LEFT, fg.LONG_RIGHT, nx)
    lats = np.linspace(fg.LAT_TOP, fg.LAT_BOTTOM, ny)
    ml, mt = np.meshgrid(lons, lats)
    x = (ml - fg.LONG_LEFT) / (fg.LONG_RIGHT - fg.LONG_LEFT) * fg.LARGURA_SIMULACAO_BASE
    y = fg.ALTURA_MENU_SUP + (mt - fg.LAT_TOP) / (fg.LAT_BOTTOM - fg.LAT_TOP) * fg.ALTURA_TELA_BASE
    return cenario.profundidades_m(np.column_stack([x.ravel(), y.ravel()]), t_h).reshape(ny, nx)


def test_grade_distancias_e_cacheada():
    fc._CACHE_DISTANCIAS.clear()
    a = fc.grade_distancias(130, 78)
    b = fc.grade_distancias(130, 78)
    assert a is b, "a segunda chamada devia reaproveitar a malha"
    assert len(fc._CACHE_DISTANCIAS) == 1
    # resolucoes diferentes nao podem colidir
    fc.grade_distancias(100, 60)
    assert len(fc._CACHE_DISTANCIAS) == 2
    assert a is not fc.grade_distancias(100, 60)


def test_grade_com_cache_bate_com_a_versao_lenta():
    """O atalho de desempenho nao pode alterar nenhum valor de batimetria."""
    for codigo in ("C1", "C2", "C3"):
        c = fc.obter_cenario(codigo)
        for t_h in (0.0, 12.0, 71.0, 73.0, 100.0, 168.0):
            rapido, _, _ = fc.grade_profundidade(c, t_h, 90, 54)
            lento = _grade_sem_cache(c, t_h, 90, 54)
            assert np.array_equal(rapido, lento), (
                f"{codigo} em t={t_h}h divergiu do calculo sem cache")


def test_grade_distancias_malha_somente_leitura():
    """A malha e compartilhada entre chamadas, logo nao pode ser mutavel."""
    posicoes, indice, dists = fc.grade_distancias(60, 40)
    assert not posicoes.flags.writeable
    assert not indice.flags.writeable
    assert not dists.flags.writeable
    assert indice.shape == dists.shape == (40 * 60,)
    assert posicoes.shape == (40 * 60, 2)


def test_profundidades_em_lote_batem_ponto_a_ponto():
    c = fc.obter_cenario("C2")
    pts = np.column_stack([np.linspace(0, 1000, 25), np.linspace(40, 640, 25)])
    lote = c.profundidades_m(pts, 0.0)
    unit = np.array([c.profundidade_m(p, 0.0) for p in pts])
    assert np.allclose(lote, unit, atol=1e-9)


def test_classificacao_de_risco():
    assert fc.classificar_margem(0.2) == fc.RISCO_CRITICO
    assert fc.classificar_margem(1.0) == fc.RISCO_ATENCAO
    assert fc.classificar_margem(4.0) == fc.RISCO_SEGURO


# ---------------------------------------------------------------------------
# 3. CAMADA LORA
# ---------------------------------------------------------------------------
def test_airtime_cresce_com_a_carga_util():
    p = fl.ParametrosLora(sf=7, banda_hz=125000, taxa_bits_s=781)
    airtimes = [p.airtime_ms(n) for n in (8, 32, 66, 200)]
    assert airtimes == sorted(airtimes)
    assert airtimes[0] > 0.0


def test_airtime_confere_com_a_referencia_do_spreadsheet():
    # SF7, 125 kHz, payload de 66 B: 123,1 ms medidos na calculadora oficial
    # da Malha-LoRa (mesma referencia usada em meshtastic.org).
    p = fl.ParametrosLora(sf=7, banda_hz=125000, taxa_bits_s=781,
                         codificacao="4/5", preamble=8, cr_crc=True)
    assert 0.115 < p.airtime_ms(66) / 1000.0 < 0.135


def test_airtime_sobe_com_o_spreading_factor():
    payload = 66
    airtimes = [fl.ParametrosLora(sf=sf, banda_hz=125000, taxa_bits_s=781).airtime_ms(payload)
                for sf in (7, 9, 12)]
    assert airtimes == sorted(airtimes)


def test_limite_de_duty_cycle_e_respeitado():
    p = fl.ParametrosLora()
    assert 0.0 < p.limite_duty_cycle <= 0.01
    carga = fl.TAMANHO_CABECALHO_BP_B + fl.TAMANHO_CARGA_UTIL_B
    # a propria implementacao ja limita a taxa; aqui confere-se que o teto
    # declarado de quadros por hora corresponde ao duty cycle permitido
    assert p.frames_por_hora(carga) * (p.airtime_por_segundo(carga)) \
        <= p.limite_duty_cycle * 3600.0 + 1e-6


def test_energia_de_tx_cresce_com_o_airtime():
    p = fl.ParametrosLora()
    curto = p.energia_tx_joule(p.airtime_por_segundo(10))
    longo = p.energia_tx_joule(p.airtime_por_segundo(100))
    assert 0.0 < curto < longo


# ---------------------------------------------------------------------------
# 4. MOTOR DTN
# ---------------------------------------------------------------------------
def _rodar(protocolo: str = "flora", cenario: str = "C1", horas: float = 3.0, semente: int = 7, **cfg_kw):
    cfg = fd.ConfiguracaoDTN(cenario=cenario, protocolo=protocolo,
                             horizonte_h=horas, semente=semente, **cfg_kw)
    cfg.validar()
    return fd.MotorDTN(cfg).executar()


# ---------------------------------------------------------------------------
# Gateways: fixos nas cidades, moveis nas embarcacoes grandes
# ---------------------------------------------------------------------------
def test_gateways_fixos_ficam_nas_cidades():
    """Cada gateway fixo tem de nascer em cima do marco da cidade."""
    ancorados = fg.ancorar_cidades()
    assert len(ancorados) == len(fg.SUPERNOS_CIDADE)
    for chave, nome, canal, km, desvio in ancorados:
        assert desvio < 0.05, f"{nome} a {desvio:.2f} km do eixo do canal"
        assert 0.0 <= km <= canal.comprimento_km
    # o modelo tem um canal so, o leito principal do Amazonas
    for chave in ("Manaus", "Itacoatiara"):
        canal = {c: k for c, _n, k, _km, _d in ancorados}[chave]
        assert canal is fg.CANAL_PRINCIPAL


def test_cidades_do_corredor_usam_coordenada_real():
    """
    Todo gateway fixo nasce na coordenada da cidade, e nao num ponto inventado.

    E o teste que impede a regressao que motivou a correcao: as tabelas antigas
    traziam valores de gabarito que colocavam Urucurituba a 114 km do rio e
    Autazes a 85 km. Cada par usado por `SUPERNOS_CIDADE` e conferido contra a
    coordenada registrada em `CIDADES_FORA_DO_CORREDOR` e as tabelas de marcos.
    """
    for chave, nome in fg.SUPERNOS_CIDADE:
        assert chave in fg.WAYPOINTS, f"{nome} sem marco geografico"
        lat, lon = fg.mundo_para_geo(*fg.WAYPOINTS[chave])
        tabelado = fg.COORDENADAS_ROTA_NAVEGACAO[chave]
        # ida e volta: converter o waypoint e reconverter precisa devolver a
        # coordenada tabelada, o que so acontece se a geometria for coerente
        assert abs(lat - tabelado[0]) < 1e-9, f"{nome}: lat {lat} != {tabelado[0]}"
        assert abs(lon - tabelado[1]) < 1e-9, f"{nome}: lon {lon} != {tabelado[1]}"


def test_cidades_fora_do_corredor_nao_viram_gateway():
    """
    Os municipios fora do corredor ficam registrados e fora da lista de gateways.

    A lista de cidades e um cadastro, nao uma garantia de cobertura: Urucurituba,
    Silves e Itapiranga tem telecomunicacao na tese, mas nenhuma delas cai sobre
    um canal modelado, entao nenhuma pode virar gateway sem deslocar o rio.
    """
    dentro = {chave for chave, _nome in fg.SUPERNOS_CIDADE}
    fora = {f["cidade"] for f in fg.CIDADES_FORA_DO_CORREDOR}
    assert {"Urucurituba", "Silves", "Itapiranga"} <= fora
    assert not (fora & dentro)
    for ficha in fg.CIDADES_FORA_DO_CORREDOR:
        nome = ficha["cidade"]
        assert -61.0 < ficha["lon"] < -58.0, f"{nome} com longitude implausivel"
        assert -4.5 < ficha["lat"] < -2.0, f"{nome} com latitude implausivel"
        assert str(ficha["motivo"]).strip(), f"{nome} sem motivo registrado"


def test_gateways_fixos_estao_no_ponto_da_cidade():
    """A posicao do gateway e a do waypoint, nao um km digitado a mao."""
    ancorados = {c: (canal, km) for c, _n, canal, km, _d in fg.ancorar_cidades()}
    for sn in fd.construir_supernos(8.0):
        canal, km = ancorados[sn.chave]
        assert sn.canal is canal
        assert abs(sn.km_canal - km) < 1e-9
        d = float(np.linalg.norm(np.asarray(sn.pos) - fg.WAYPOINTS[sn.chave]))
        assert d < 0.5, f"{sn.chave} fora do waypoint"


def test_cobertura_de_gateway_ignora_os_moveis():
    """A cobertura fixa nao pode depender de onde um terminal movel esta."""
    fixos = fd.construir_supernos(8.0)
    cfg = fd.ConfiguracaoDTN()
    frota = [fd.Embarcacao(i, "PRINCIPAL", fg.CANAL_PRINCIPAL, __import__("random").Random(1))
             for i in range(4)]
    moveis = fd.construir_supernos_moveis(frota, cfg)
    cov_a, vao_a = fg.cobertura_gateways(8.0, fixos)
    cov_b, vao_b = fg.cobertura_gateways(8.0, fixos + moveis)
    assert cov_a == cov_b and vao_a == vao_b
    assert 0.0 < cov_a < 1.0, "a rota nao pode ficar nem sem cobertura nem totalmente coberta"


def test_gateways_fixos_sao_dois_e_moveis_sao_quatro() -> None:
    info = fd.listar_gateways()
    assert len(info["fixos"]) == 2
    assert {g["nome"] for g in info["fixos"]} == {"Porto de Manaus", "Terminal Itacoatiara"}
    assert len(info["moveis"]) == 4
    assert len(info["municipios_excluidos"]) == 5
    excluidos = {g["nome"] for g in info["municipios_excluidos"]}
    assert excluidos == {"Urucurituba", "Careiro da Varzea", "Autazes",
                        "Silves", "Itapiranga"}
    cfg = fd.ConfiguracaoDTN()
    rng = __import__("random").Random(3)
    no = fd.Embarcacao(0, "PRINCIPAL", fg.CANAL_PRINCIPAL, rng)
    sn = fd.construir_supernos_moveis([no], cfg)[0]
    assert sn.movel and sn.anfitriao is no
    assert abs(sn.km_canal - no.km_atual) < 1e-9
    no.km_atual += 7.5
    sn.sincronizar()
    assert abs(sn.km_canal - no.km_atual) < 1e-9
    assert np.allclose(np.asarray(sn.pos), np.asarray(no.pos))


def test_bundle_de_seguranca_expulsa_rotineiro_antigo() -> None:
    rng = __import__("random").Random(7)
    no = fd.Embarcacao(0, "PRINCIPAL", fg.CANAL_PRINCIPAL, rng)
    limite = 1
    rotineiro = fd.Bundle(bid="r1", categoria=fd.CAT_ROTINA, origem=0,
                          t_criacao_s=0.0, carga={})
    seguranca = fd.Bundle(bid="s1", categoria=fd.CAT_SEGURANCA, origem=0,
                          t_criacao_s=10.0, carga={})
    assert no.inserir(rotineiro, 0.0, limite) is True
    assert "r1" in no.buffer
    # Buffer cheio: o bundle de seguranca (prioridade maior) expulsa o rotineiro.
    assert no.inserir(seguranca, 10.0, limite) is True
    assert "s1" in no.buffer
    assert "r1" not in no.buffer

    # O inverso nao acontece: um rotineiro nao expulsa um de seguranca.
    no2 = fd.Embarcacao(1, "PRINCIPAL", fg.CANAL_PRINCIPAL, rng)
    seg = fd.Bundle(bid="s2", categoria=fd.CAT_SEGURANCA, origem=1,
                    t_criacao_s=0.0, carga={})
    rot = fd.Bundle(bid="r2", categoria=fd.CAT_ROTINA, origem=1,
                    t_criacao_s=10.0, carga={})
    assert no2.inserir(seg, 0.0, limite) is True
    assert no2.inserir(rot, 10.0, limite) is False
    assert "s2" in no2.buffer
    assert "r2" not in no2.buffer
    cfg = fd.ConfiguracaoDTN()
    rng = __import__("random").Random(4)
    frota = [fd.Embarcacao(i, t, fg.CANAL_PRINCIPAL, rng)
             for i, t in enumerate(["PRINCIPAL", "LANCHA", "RIBEIRINHO", "PRINCIPAL"])]
    moveis = fd.construir_supernos_moveis(frota, cfg)
    assert len(moveis) == 2
    assert {sn.anfitriao.tipo for sn in moveis} == {"PRINCIPAL"}


def test_gateway_movel_respeita_a_cota_de_subida():
    """Um terminal lento nao pode drenar mais do que a taxa configurada."""
    cfg = fd.ConfiguracaoDTN(bundles_por_hora_gateway_movel=6.0, horizonte_h=1.0)
    m = fd.MotorDTN(cfg)
    for _ in range(int(3600.0 / cfg.passo_s)):
        m.passo()
    for sn in m.supernos_moveis:
        assert sn.pacotes_drenados <= 6, \
            f"{sn.chave} drenou {sn.pacotes_drenados} em 1 h, cota era 6"


def test_cota_ilimitada_deixa_o_gateway_movel_subir_tudo():
    cfg = fd.ConfiguracaoDTN(bundles_por_hora_gateway_movel=1e6, horizonte_h=1.0)
    m = fd.MotorDTN(cfg)
    m.passo()
    assert any(sn.pacotes_drenados > 0 for sn in m.supernos_moveis)


def test_desligar_gateways_moveis_preserva_o_reexperimento():
    r_sem = _rodar("flora", "C3", 3.0, tipos_gateway_movel=()).resumo()
    assert r_sem["gateways_moveis"] == 0
    assert r_sem["super_nos"] == len(fg.SUPERNOS_CIDADE)
    r_com = _rodar("flora", "C3", 3.0).resumo()
    assert r_com["gateways_moveis"] == 4
    assert r_com["entregues_total"] > r_sem["entregues_total"]


def test_gateway_movel_melhora_a_chegada_da_informacao():
    """Com terminal a bordo, menos leitura fica retida no corredor sem cobertura."""
    r_sem = _rodar("flora", "C3", 12.0, tipos_gateway_movel=())
    r_com = _rodar("flora", "C3", 12.0)
    assert r_com.resumo()["cobertura_instantanea_media"] > \
        r_sem.resumo()["cobertura_instantanea_media"]
    assert r_com.resumo()["ted_no_horizonte_percentual"] >= \
        r_sem.resumo()["ted_no_horizonte_percentual"]


def test_configuracao_rejeita_gateway_invalido():
    for kwargs in ({"alcance_gateway_fixo_km": 0.0},
                   {"bundles_por_hora_gateway_movel": -1.0},
                   {"tipos_gateway_movel": ("TREM",)}):
        try:
            fd.ConfiguracaoDTN(**kwargs).validar()
        except ValueError:
            continue
        raise AssertionError(f"deveria ter rejeitado {kwargs}")


def test_configuracao_rejeita_entradas_invalidas():
    for kwargs in ({"protocolo": "inexistente"}, {"cenario": "C9"},
                   {"passo_s": 0.0}, {"fator_alcance": 0.0}):
        try:
            fd.ConfiguracaoDTN(**kwargs).validar()
        except (ValueError, KeyError):
            continue
        raise AssertionError(f"deveria ter rejeitado {kwargs}")


def test_todos_os_protocolos_rodam():
    for p in ("epidemico", "spray", "flora", "slp", "sc"):
        r = _rodar(p).resumo()
        assert r["tempo_simulado_h"] > 0.0
        assert r["frota"] == 15


def test_invariantes_do_motor():
    r = _rodar("flora", "C3", horas=4.0).resumo()
    assert 0.0 <= r["ted_percentual"] <= 100.0
    assert 0.0 <= r["ted_no_horizonte_percentual"] <= 100.0
    assert r["overhead_copias"] >= 1.0
    assert r["entregues_total"] <= r["bundles_criados"]
    assert r["frames_tx"] == r["transmissoes"]
    assert r["energia_total_j"] > 0.0
    assert r["frota"] == 15
    # 2 cidades ancoradas + um terminal movel por embarcacao (4)
    assert r["gateways_moveis"] == 4
    assert r["super_nos"] == 6


def test_baselines_nao_repassam_entre_embarcacoes():
    # slp faz upload direto, sem relay: overhead 1.0
    r = _rodar("slp", horas=3.0).resumo()
    assert r["overhead_copias"] == 1.0, "slp deveria ter overhead 1.0"
    # sc nao faz upload nem relay: nenhuma entrega
    r2 = _rodar("sc", horas=3.0).resumo()
    assert r2["entregues_total"] == 0, "sc nao deve entregar bundles"


def test_epidemico_supera_flora_em_overhead():
    epi = _rodar("epidemico", "C3", 6.0).resumo()
    flo = _rodar("flora", "C3", 6.0).resumo()
    assert flo["overhead_copias"] < epi["overhead_copias"]


def test_utilidade_mensagem_monotona_e_prioridade() -> None:
    cfg = fd.ConfiguracaoDTN()
    ctx = fd.ContextoRoteamento(fd.construir_supernos(8.0), 0.0)
    rng = __import__("random").Random(1)
    no = fd.Embarcacao(0, "PRINCIPAL", fg.CANAL_PRINCIPAL, rng)
    bd_seg = fd.Bundle(bid="b1", categoria=fd.CAT_SEGURANCA, origem=0,
                       t_criacao_s=0.0, carga={"km": no.km_atual})
    bd_rot = fd.Bundle(bid="b2", categoria=fd.CAT_ROTINA, origem=0,
                       t_criacao_s=0.0, carga={"km": no.km_atual})
    u_seg = fd.utilidade_mensagem(bd_seg, 0.0, no, ctx, cfg)
    u_rot = fd.utilidade_mensagem(bd_rot, 0.0, no, ctx, cfg)
    assert abs(u_seg / u_rot - 10.0) < 1e-9, "omega=10 deve dar 10x"

    bd_velho = fd.Bundle(bid="b3", categoria=fd.CAT_ROTINA, origem=0,
                          t_criacao_s=-3600.0, carga={"km": no.km_atual})
    assert fd.utilidade_mensagem(bd_velho, 0.0, no, ctx, cfg) < u_rot

    bd_longe = fd.Bundle(bid="b4", categoria=fd.CAT_ROTINA, origem=0,
                          t_criacao_s=0.0, carga={"km": no.km_atual + 50.0})
    assert fd.utilidade_mensagem(bd_longe, 0.0, no, ctx, cfg) < u_rot


def test_reprodutibilidade():
    a = _rodar("flora", "C3", 4.0).resumo()
    b = _rodar("flora", "C3", 4.0).resumo()
    assert a == b


def test_semente_diferente_altera_a_trajetoria():
    a = _rodar("flora", "C1", 2.0, semente=1).resumo()
    b = _rodar("flora", "C1", 2.0, semente=2).resumo()
    assert a["transmissoes"] != b["transmissoes"] or a["encontros"] != b["encontros"]


def test_terra_caida_marca_risco_por_calado():
    motor = _rodar("flora", "C3", 3.0)
    motor.executar(76.0)
    classes = {no.classe_risco for no in motor.frota}
    assert classes <= {fc.RISCO_SEGURO, fc.RISCO_ATENCAO, fc.RISCO_CRITICO}
    # a margem sob quilha e coerente com a profundidade local
    for no in motor.frota:
        assert no.margem_sob_quilha_m == no.profundidade_m - no.calado_m


def test_exportacao_gera_arquivos(tmp_dir=None):
    import tempfile

    pasta = tmp_dir or tempfile.mkdtemp(prefix="flora_test_")
    base = os.path.join(pasta, "teste")
    arquivos = fd.MotorDTN(fd.ConfiguracaoDTN(protocolo="flora", horizonte_h=1.0,
                                             semente=3)).executar().exportar_tudo(base)
    assert len(arquivos) == 3
    for a in arquivos:
        assert os.path.exists(a) and os.path.getsize(a) > 0


# ---------------------------------------------------------------------------
# 4. EXPORTACAO (teste extra)
# ---------------------------------------------------------------------------
def test_exportar_simulacao_gera_um_json_completo(tmp_dir=None):
    import json
    import tempfile

    pasta = tmp_dir or tempfile.mkdtemp(prefix="flora_completo_")
    caminho = os.path.join(pasta, "simulacao.json")
    motor = fd.MotorDTN(fd.ConfiguracaoDTN(protocolo="flora", horizonte_h=1.0,
                                           semente=3)).executar()
    devolvido = motor.exportar_simulacao(caminho)
    assert devolvido == caminho
    with open(caminho, encoding="utf-8") as fh:
        dados = json.load(fh)
    assert dados["formato"] == "flora-dtn-simulacao"
    assert dados["software"]["versao"]
    assert dados["resumo"]["protocolo"] == "flora"
    assert dados["configuracao"]["semente"] == 3
    assert len(dados["frota"]) == len(motor.frota)
    assert dados["series"]["ted"]
    assert dados["supernos"]
    assert isinstance(dados["amostras"]["latencias_s"], list)


# ---------------------------------------------------------------------------
# 5. CARTA NAUTICA
# ---------------------------------------------------------------------------
def test_folha_de_carta_tem_terra_agua_curvas_e_sondagens():
    """
    A folha precisa trazer as camadas que a distinguem de um preenchimento.

    Sao cinco afirmacoes independentes: existe terra, existe agua, a agua muda de
    cor com a profundidade, existe linha de costa e existem curvas de cote. Sem
    elas a carta pode parecer correta numa miniatura e estar vazia de conteudo.
    """
    from flora_mapa import (
        COR_COSTA,
        COR_CURVA,
        COR_CURVA_MESTRA,
        COR_TERRA_OCRE_CLARO,
        COR_TERRA_OCRE_SOMBRA,
        desenhar_folha_carta,
    )

    w, h = 640, 400
    img = np.asarray(desenhar_folha_carta(fc.obter_cenario("C3"), 0.0, (w, h)))
    total = w * h

    def perto(cor, tol=10):
        return (np.abs(img.astype(int) - np.array(cor)).max(axis=-1) <= tol).sum()

    # A terra e ocre com relevo sombreado, entao o pixel fica entre os dois
    # extremos da rampa e raramente bate com um deles. O teste mede a fracao de
    # pixels com tom de terra, e nao a contagem exata de duas cores.
    r, g, b = img[..., 0].astype(int), img[..., 1].astype(int), img[..., 2].astype(int)
    terra = (r > g) & (g > b) & (r - b > 30) & (r < 250)
    assert terra.mean() > 0.25, f"quase sem terra: {100 * terra.mean():.1f}%"
    assert perto(COR_TERRA_OCRE_SOMBRA) > 0, "sem o extremo escuro do relevo"
    assert perto(COR_TERRA_OCRE_CLARO) > 0, "sem o extremo claro do relevo"
    # agua e a regiao em que o azul domina o vermelho, que so acontece no
    # gradiente de profundidade da carta
    agua = img[..., 2].astype(int) > img[..., 0].astype(int) + 25
    assert 0.02 * total < agua.sum() < 0.75 * total, (
        f"fracao de agua implausivel: {100 * agua.mean():.1f}%")
    assert perto(COR_COSTA) > 200, "sem linha de costa"
    assert perto(COR_CURVA) + perto(COR_CURVA_MESTRA) > 300, "sem curvas de cote"

    # A cor da agua precisa acompanhar a profundidade, e nao ser chapada. A
    # verificacao roda sobre o gradiente sem curvas nem sondagens: essas camadas
    # sobrescrevem boa parte dos pixels de agua, e a correlacao passaria a medir
    # a densidade de traco em vez da paleta.
    lisa = np.asarray(desenhar_folha_carta(
        fc.obter_cenario("C3"), 0.0, (w, h), curvas=False, sondagens=False,
        limites_canal=False))
    g, agua_grade, _la, _lo = fc.grade_leito(fc.obter_cenario("C3"), 0.0, 260, 156)
    prof = np.asarray(
        Image.fromarray(g.astype(np.float32), "F").resize((w, h), Image.BICUBIC),
        dtype=np.float32)
    dentro = (lisa[..., 2].astype(int) > lisa[..., 0].astype(int) + 25) & \
        _reamostrar(agua_grade, (w, h))
    assert dentro.sum() > 1000
    cor_azul = lisa[..., 2][dentro].astype(float)
    prof_dentro = prof[dentro].astype(float)
    # a paleta vai de claro no raso a escuro no fundo, entao a correlacao e negativa
    assert np.corrcoef(prof_dentro, cor_azul)[0, 1] < -0.9, (
        "a cor da agua nao acompanha a profundidade")


def _reamostrar(mascara: np.ndarray, tamanho) -> np.ndarray:
    """Reamostra uma mascara booleana no mesmo espaco do raster, como a carta faz."""
    return np.asarray(
        Image.fromarray((mascara * 255).astype(np.uint8), "L").resize(
            tuple(tamanho), Image.BILINEAR),
        dtype=np.float32) >= 128.0


def test_folha_de_carta_tem_a_mesma_linha_de_costa_em_todo_o_ciclo():
    """
    A faixa de agua nao pode depender da hora do dia.

    O modelo nao tem topografia fora do leito: o perfil transversal termina em
    0,4 m e esse valor se repete por todo o quadro. Como a profundidade e
    `perfil + nivel do rio` e o nivel oscila 0,35 m por dia, uma linha de costa
    por limiar de profundidade classificava a varzea inteira como agua no pico da
    mare: medido no cenario C3, a fracao de agua saltava de 19% para 100% conforme
    a hora, e a carta piscava. A agua vem da secao transversal do canal, entao
    nao tem por que mudar.
    """
    from flora_mapa import desenhar_folha_carta

    c = fc.obter_cenario("C3")
    w, h = 500, 300
    # 3 h de passo cobrem um ciclo da mare diaria com folga
    areas = []
    for t_h in np.arange(0.0, 24.0, 3.0):
        img = np.asarray(desenhar_folha_carta(c, float(t_h), (w, h))).astype(int)
        agua = img[..., 2] > img[..., 0] + 25
        areas.append(float(agua.mean()))
    menor, maior = min(areas), max(areas)
    assert maior < 0.45, f"agua demais em algum instante: {100 * maior:.1f}%"
    assert maior - menor < 0.02, (
        f"a linha de costa variou com a mare: de {100 * menor:.1f}% a "
        f"{100 * maior:.1f}%")


def test_folha_de_carta_e_deterministica():
    """Duas folhas iguais do mesmo instante sao byte a byte iguais."""
    from flora_mapa import desenhar_folha_carta

    c = fc.obter_cenario("C2")
    a = np.asarray(desenhar_folha_carta(c, 40.0, (420, 260)))
    b = np.asarray(desenhar_folha_carta(c, 40.0, (420, 260)))
    assert (a == b).all()


def test_faixa_de_agua_segue_o_canal_e_nao_a_profundidade():
    """
    A mascara de agua tem de ter a largura do perfil transversal do canal.

    E o teste que fixa a correcao do limiar de profundidade: como o modelo nao
    tem topografia fora do leito, a profundidade nao separa terra de agua. O que
    separa e a distancia ate o eixo, comparada com o semi-eixo do perfil.
    """
    from flora_cenario import mascara_agua

    c = fc.obter_cenario("C3")
    _p, agua, _la, _lo = fc.grade_leito(c, 0.0, 260, 156)
    _pos, indice, dists = fc.grade_distancias(agua.shape[1], agua.shape[0])
    esperado = mascara_agua(indice, dists)
    assert (esperado == agua.reshape(-1)).all(), "a mascara nao bate com a grade"
    # nenhuma celula marcada como agua esta alem do semi-eixo do seu canal
    limite = np.array([fc.SEMI_EIXO_CANAL_KM[nome] for nome in fg.CANAIS])
    dentro = agua.reshape(-1)
    assert dists[dentro].max() <= limite[indice[dentro]].max() + 0.15
    # e a faixa nao e tao larga que a várzea toda vire rio
    assert 0.03 < agua.mean() < 0.45, f"faixa de agua implausivel: {100 * agua.mean():.1f}%"


def test_camadas_da_folha_mudam_o_raster():
    """Cada camada da folha tem de mudar a imagem quando ligada e desligada."""
    from flora_mapa import desenhar_folha_carta

    c = fc.obter_cenario("C3")
    cheio = np.asarray(desenhar_folha_carta(c, 0.0, (420, 260)))
    for camada in ("curvas", "sondagens", "relevo", "limites_canal"):
        kwargs = {camada: False}
        vazio = np.asarray(desenhar_folha_carta(c, 0.0, (420, 260), **kwargs))
        assert not (cheio == vazio).all(), f"desligar {camada} nao mudou nada"


def test_carta_gera_imagem_nao_degenerada():
    from flora_mapa import CartaNautica, OpcoesCarta

    img = CartaNautica(OpcoesCarta(escala=1.0, nx=60, ny=40)).render(
        fc.obter_cenario("C2"), 0.0)
    assert img.width > 500 and img.height > 300
    cores = np.asarray(img.convert("RGB")).reshape(-1, 3)
    assert len(np.unique(cores, axis=0)) > 50, "carta saiu com poucas cores"


def test_carta_com_simulacao_inclui_frota_e_supernos():
    from flora_mapa import CartaNautica, OpcoesCarta

    motor = _rodar("flora", "C1", 2.0)
    img = CartaNautica(OpcoesCarta(escala=1.0, nx=60, ny=40)).render(
        motor.cenario, motor.t_s / 3600.0, motor=motor)
    assert img.width > 500
    arr = np.asarray(img.convert("RGB"))
    # o verde dos supernos precisa aparecer em algum lugar da carta
    verde = (np.abs(arr.astype(int) - np.array((40, 220, 110))).max(axis=-1) <= 2).sum()
    assert verde > 0, "supernos nao foram desenhados"


def test_cor_batimetria_mapeia_profundiade_para_risco():
    from flora_mapa import cor_batimetria

    raso = cor_batimetria(np.array([[0.2]]))[0, 0]
    fundo = cor_batimetria(np.array([[32.5]]))[0, 0]
    assert raso[3] < fundo[3], "agua rasa deveria ser mais transparente"
    # o raso tende ao vermelho e o fundo ao azul
    assert raso[0] > raso[2]
    assert fundo[2] > fundo[0]


# ---------------------------------------------------------------------------
# 6. PONTO DE ENTRADA
# ---------------------------------------------------------------------------
def test_cli_carta_gera_png(tmp_dir=None):
    import tempfile

    import dtn_simulador as cli

    pasta = tmp_dir or tempfile.mkdtemp(prefix="flora_cli_")
    destino = os.path.join(pasta, "carta.png")
    codigo = cli.main(["carta", "-c", "C2", "-o", destino, "--escala", "0.8"])
    assert codigo == 0
    assert os.path.exists(destino) and os.path.getsize(destino) > 1000


def test_cli_rodar_gera_csv(tmp_dir=None):
    import tempfile

    import dtn_simulador as cli

    pasta = tmp_dir or tempfile.mkdtemp(prefix="flora_cli_")
    codigo = cli.main(["rodar", "-c", "C1", "-p", "slp", "-H", "1", "-o", pasta])
    assert codigo == 0
    csvs = [f for f in os.listdir(pasta) if f.endswith(".csv")]
    assert csvs, "nenhum CSV gerado"


def test_cli_ajustes_opcionais_nao_sobrescrevem_padroes():
    import dtn_simulador as cli

    args = cli.construir_parser().parse_args(["rodar", "--limiar-utilidade", "0.9"])
    cfg = cli.construir_cfg(args)
    assert cfg.limiar_utilidade == 0.9
    padrao = fd.ConfiguracaoDTN()
    assert cfg.fator_retencao == padrao.fator_retencao
    assert cfg.utilidade_sigma_d_km == padrao.utilidade_sigma_d_km


# ---------------------------------------------------------------------------
# 7. DESENHO DA FROTA (precisa de pygame; pulado se faltar)
# ---------------------------------------------------------------------------
def _app_de_teste():
    """Aplicacao da interface em modo sem janela, ou None se pygame faltar."""
    try:
        import pygame
    except ImportError:
        return None
    if not pygame.get_init():
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1280, 900))
    import flora_ui

    return flora_ui.Aplicacao(fd.ConfiguracaoDTN(cenario="C2"))


def test_desenho_nao_acelera_a_frota():
    """
    O desenho tem de andar tanto quanto o modelo andou.

    Este e o teste que impede a interpolacao de virar invencao. Suavizar a posicao
    e tentador, mas um filtro sobre pixels deixa o casco atrasado em relacao ao
    modelo e, se o filtro nao convergir, o casco anda mais rapido que a
    simulacao. A comparacao e sobre o avanco em quilometros, e nao sobre a soma
    dos deslocamentos em pixels, porque a soma conta duas vezes a volta no fim do
    canal e nao diz nada sobre o erro.
    """
    app = _app_de_teste()
    if app is None:
        return
    app.rodando = True
    app.indice_velocidade = 3
    no = app.motor.frota[0]
    km_ini = no.km_atual
    for _ in range(200):
        app._avancar(1.0 / 60.0)
        app._suavizar_frota()
    andou = abs(no.km_atual - km_ini)
    desenhou = abs(no._km_desenho - km_ini)
    assert andou > 0.5, "a frota andou demais pouco para o teste valer"
    assert abs(desenhou - andou) / andou < 0.05, \
        f"o desenho andou {desenhou:.3f} km e o modelo {andou:.3f} km"


def test_desenho_espalha_o_salto_do_passo():
    """
    O tremor era o casco dando um salto e parando; agora ele desliza.

    O caso que produz tremor e o ritmo baixo: a 10 passos/s o modelo so avanca a
    cada seis quadros de 60 Hz. Sem suavizacao o casco fica parado e salta o
    passo inteiro de uma vez; com a extrapolacao pela velocidade o mesmo avanco
    se distribui por todos os quadros, entao o pico cai mesmo que a media nao
    mude. (A 120 passos/s o modelo avanca em todo quadro e nao ha salto a
    suavizar: por isso o teste usa o degrau mais lento.)
    """
    app = _app_de_teste()
    if app is None:
        return
    app.rodando = True
    app.indice_velocidade = 0
    no = app.motor.frota[0]
    picos = []
    for suavizar in (False, True):
        # no ramo "sem" o desenho usa a posicao do modelo, como antes de existir
        # a suavizacao; limpar o cache garante que ele nao reaproveite um quadro
        for outro in app.motor.frota:
            outro._pos_desenho_cache = None
        if suavizar:
            app._suavizar_frota()
        anterior = app._pos_desenho(no).copy()
        km_anterior = no.km_atual
        passos = []
        for _ in range(200):
            app._avancar(1.0 / 60.0)
            if suavizar:
                app._suavizar_frota()
            atual = app._pos_desenho(no)
            # a volta no fim do canal e um teleporte legitimo do modelo, e nao
            # tremor: os dois lados da comparacao devem ignorar o mesmo quadro
            if abs(no.km_atual - km_anterior) < 4.0:
                passos.append(float(np.linalg.norm(atual - anterior)))
            anterior = atual.copy()
            km_anterior = no.km_atual
        picos.append(max(passos))
    sem, com = picos
    assert sem > 0.05, f"o passo do modelo pequeno demais para medir: {sem:.3f} px"
    assert com < sem * 0.5, f"o pico por quadro nao caiu: {sem:.2f} -> {com:.2f} px"


def test_posicao_desenhada_fica_no_eixo():
    """A posicao suavizada tem de sair do canal, e nao de uma reta entre pontos."""
    app = _app_de_teste()
    if app is None:
        return
    app.rodando = True
    app.indice_velocidade = 3
    no = app.motor.frota[0]
    for _ in range(60):
        app._avancar(1.0 / 60.0)
        app._suavizar_frota()
        pos = app._pos_desenho(no)
        d = fg.distancia_mundo_km(pos, no.canal.posicao_em(
            no._km_desenho, no.offset_faixa_km)[0])
        assert d < 0.01, f"posicao desenhada a {d:.3f} km do eixo"


def test_velocidade_da_embarcacao_em_nos():
    """A interface fala em nos: 1 no = 1,852 km/h, e os perfis seguem a regra."""
    no = fd.Embarcacao(tipo="LANCHA", km_atual=10.0, offset_faixa_km=0.0,
                       velocidade_km_h=18.52)
    assert abs(no.velocidade_nos - 10.0) < 1e-9
    for perfil in fd.PERFIS_EMBARCACAO.values():
        assert abs(perfil.velocidade_min_nos
                   - perfil.velocidade_min_kmh / fd.KM_POR_NO) < 1e-12
        assert perfil.velocidade_min_nos <= perfil.velocidade_max_nos


def test_fundo_padrao_e_o_satelite():
    """
    A janela tem de abrir na foto de satelite, e nao na folha de carta.

    Este e o teste da falha reportada: com a folha de carta como padrao, a tela
    media 0,9% de verde contra os 58% da foto, e o simulador abria num desenho
    esquematico que o usuario leu como "o mapa nao carregou". A base e o fundo
    unico da cena, entao ela e a unica flag que o default tem de acertar.
    """
    app = _app_de_teste()
    if app is None:
        return
    assert app.camadas.base_satelite, "o simulador nao abre no satelite"
    assert not app.camadas.base_carta, "a carta e um fundo alternativo, nao empilhada"


def test_satelite_sem_tiles_cai_para_a_carta():
    """
    Sem os tiles em disco, o fundo tem de virar carta, e nao um retangulo verde.

    O ramo de satelite monta a imagem de fundo antes de descobrir se o recorte
    do mosaico existe; sem o fallback, a tela virava um retangulo de uma cor so.
    """
    app = _app_de_teste()
    if app is None:
        return
    app.camadas.base_carta = False
    app.camadas.base_satelite = True
    app._base_chave = None
    app.mosaico.disponivel = lambda: False
    img = app._construir_base()
    buf = np.frombuffer(img.get_buffer(), dtype=np.uint8)
    cores = np.unique(buf.reshape(img.get_height(), img.get_width(), 3)[:, :, :3]
                      .reshape(-1, 3), axis=0)
    assert len(cores) > 50, f"fundo sem tiles virou bloco liso: {len(cores)} cores"


def test_marcos_de_km_desenham_no_zoom():
    """
    Os marcos de quilometragem tem de pintar sem estourar em zoom acima de 1.

    `posicao_em` devolve (posicao, tangente, perpendicular); o marco desempacotava
    o ponto e passava so o primeiro componente para a projecao, que passou a ler
    um escalar como se fosse um ponto e derrubou a janela inteira. O teste e
    chamado com zoom alto porque em zoom 1 os marcos nem entram no desenho, e
    por isso o caminho ficava sem cobertura nenhuma.
    """
    app = _app_de_teste()
    if app is None:
        return
    canal = next(iter(fg.CANAIS.values())) if hasattr(fg, "CANAIS") else None
    if canal is None:
        import flora_ui
        canal = next(iter(flora_ui.CANAIS.values()))
    app.visao.zoom = 2.0
    for km in range(20, int(canal.comprimento_km), 20):
        pos = canal.posicao_em(float(km), 0.0)[0]
        assert len(pos) >= 2, f"km {km}: posicao_em devolveu {type(pos)}"
        sx, sy = app.visao.para_tela(pos)
        assert isinstance(sx, int) and isinstance(sy, int)
    app._desenhar_marcos_canal(canal)


def test_icone_da_embarcacao_fica_centralizado():
    """
    O casco tem de ocupar o meio da superficie, e nao o canto superior esquerdo.

    O desenho e feito em supersampling: a geometria normalizada passa por
    `poly`, que centraliza em cx + x*comp, e por `p`, que aplica o fator 4.
    Faltar a `poly` deixa pontos entre -2 e 2 px, o casco inteiro no canto, e o
    que aparece na tela e a sombra so. O bbox e medido contra o centro esperado,
    que e a unica coisa que distingue as duas hipoteses.
    """
    app = _app_de_teste()
    if app is None:
        return
    import pygame
    for tipo in ("PRINCIPAL", "LANCHA", "RIBEIRINHO"):
        surf = app._superficie_icone(tipo, (70, 130, 180))
        w, h = surf.get_size()
        alfa = pygame.surfarray.pixels_alpha(surf)
        ocupado = alfa > 12
        xs = ocupado.any(axis=0).nonzero()[0]
        ys = ocupado.any(axis=1).nonzero()[0]
        assert len(xs), f"{tipo}: icone sem pixels visiveis"
        cx_medido, cy_medido = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
        assert abs(cx_medido - w / 2) < 3, (
            f"{tipo}: casco a {cx_medido:.0f}px do centro x (esperado {w / 2:.0f})")
        assert abs(cy_medido - h / 2) < 3, (
            f"{tipo}: casco a {cy_medido:.0f}px do centro y (esperado {h / 2:.0f})")
        assert ocupado.mean() > 0.06, f"{tipo}: icone quase vazio ({ocupado.mean():.1%})"


# ---------------------------------------------------------------------------
# 7a-bis. MAPA DE FUNDO POR TILES (SLIPPY MAP)
# ---------------------------------------------------------------------------
def test_projecao_de_tiles_faz_ida_e_volta():
    """A projecao Web Mercator dos tiles tem de ser invertivel."""
    for lat in (-2.6, -3.1, -3.7):
        for lon in (-60.1, -59.2, -58.35):
            for z in (10, 12, 15):
                gx, gy = flora_tiles.geo_para_px(lat, lon, z)
                lat2, lon2 = flora_tiles.px_para_geo(gx, gy, z)
                assert abs(lat - lat2) < 1e-9
                assert abs(lon - lon2) < 1e-9


def test_zoom_de_tiles_acompanha_a_visao():
    """O nivel de tile sobe um degrau a cada dobra da visao."""
    z1 = flora_tiles.zoom_para_escala(
        1.0, fg.LARGURA_SIMULACAO_BASE, fg.LONG_RIGHT - fg.LONG_LEFT)
    z2 = flora_tiles.zoom_para_escala(
        2.0, fg.LARGURA_SIMULACAO_BASE, fg.LONG_RIGHT - fg.LONG_LEFT)
    z4 = flora_tiles.zoom_para_escala(
        4.0, fg.LARGURA_SIMULACAO_BASE, fg.LONG_RIGHT - fg.LONG_LEFT)
    assert z2 == z1 + 1, f"dobrar a visao devia subir um degrau: {z1} -> {z2}"
    assert z4 == z1 + 2, f"quadruplicar devia subir dois degraus: {z1} -> {z4}"


def test_visao_arrasta_no_zoom_1():
    """
    No zoom 1 o mundo ocupa a janela inteira; ainda assim tem de dar arrasto.

    O limite antigo prendia o centro ao bloco do mundo, e no zoom 1 isso deixava
    o mapa travado: era o zoom que dava a impressao de mapa "nao movel". A
    folga de meia tela e o que distingue um mapa arrastavel de uma imagem fixa.
    """
    import flora_ui
    visao = flora_ui.Visao()
    visao.reenquadrar()
    antes = visao.centro_u
    visao.deslocar(-120.0, 0.0)
    assert abs(visao.centro_u - antes) > 1.0, "o mapa nao arrastou no zoom 1"


def test_fundo_por_tiles_cobre_a_janela():
    """O fundo de satelite tem de montar a area visivel a partir dos tiles."""
    app = _app_de_teste()
    if app is None:
        return
    import flora_ui
    app.mapa_online = False
    app.camada_satelite.permitir_rede = False
    app.visao.zoom = 2.0
    app.visao.centro_u = flora_ui.LARGURA_SIMULACAO_BASE / 2
    app.visao.centro_v = flora_ui.ALTURA_TELA_BASE / 2
    app.visao.limitar()
    assert app._desenhar_base_tiles(app._camada_mapa()) is True
    centro = app.tela.get_at((
        flora_ui.LARGURA_SIMULACAO_BASE // 2,
        flora_ui.ALTURA_MENU + flora_ui.ALTURA_TELA_BASE // 2,
    ))
    assert tuple(centro)[:3] != flora_tiles.COR_FALTA, \
        "o centro do mapa ficou na cor de tile ausente"


# ---------------------------------------------------------------------------
# 7b. GESTAO DINAMICA DE NOS E NOVOS MENUS
# ---------------------------------------------------------------------------
def test_adicionar_embarcacao_em_tempo_de_execucao() -> None:
    cfg = fd.ConfiguracaoDTN(semente=123, cenario="C1", protocolo="flora")
    motor = fd.MotorDTN(cfg)
    total_inicial = len(motor.frota)

    nova = motor.adicionar_embarcacao("LANCHA", km_inicial=45.0, sentido=1)
    assert len(motor.frota) == total_inicial + 1
    assert nova.id in [no.id for no in motor.frota]
    assert nova.tipo == "LANCHA"
    assert nova.km_atual == 45.0
    assert nova.sentido == 1
    assert nova.indice_frota == len(motor.frota) - 1

    # Avanco de passo roda sem erro com o novo no integrado
    motor.passo()
    assert nova.distancia_percorrida_km > 0.0


def test_remover_embarcacao_reorganiza_indices() -> None:
    cfg = fd.ConfiguracaoDTN(semente=123, cenario="C1", protocolo="flora")
    motor = fd.MotorDTN(cfg)
    id_para_remover = motor.frota[1].id
    total_inicial = len(motor.frota)

    removido = motor.remover_embarcacao(id_para_remover)
    assert removido is True
    assert len(motor.frota) == total_inicial - 1
    assert id_para_remover not in [no.id for no in motor.frota]

    # Verifica se os indices_frota foram recalculados consecutivamente
    for idx, no in enumerate(motor.frota):
        assert no.indice_frota == idx

    # Verifica que tentar remover ID inexistente retorna False
    assert motor.remover_embarcacao(999999) is False

    # Motor continua rodando estavel apos remocao
    motor.passo()


def test_adicionar_e_remover_embarcacao_com_gateway_movel() -> None:
    cfg = fd.ConfiguracaoDTN(semente=123, cenario="C1", protocolo="flora", tipos_gateway_movel=("PRINCIPAL",))
    motor = fd.MotorDTN(cfg)
    gw_moveis_ini = sum(1 for sn in motor.supernos if sn.movel)

    nova = motor.adicionar_embarcacao("PRINCIPAL", km_inicial=80.0, sentido=-1)
    gw_moveis_depois = sum(1 for sn in motor.supernos if sn.movel)
    assert gw_moveis_depois == gw_moveis_ini + 1

    # Remove a embarcacao que tem gateway
    motor.remover_embarcacao(nova.id)
    gw_moveis_fim = sum(1 for sn in motor.supernos if sn.movel)
    assert gw_moveis_fim == gw_moveis_ini


def test_menu_frota_e_exportar_presentes_na_ui() -> None:
    app = _app_de_teste()
    if app is None:
        return
    titulos_menus = [m.titulo for m in app.menus]
    assert "Frota" in titulos_menus
    assert "Exportar" in titulos_menus
    assert "Simulação" in titulos_menus
    assert "Camadas" in titulos_menus
    exportar = next(m for m in app.menus if m.titulo == "Exportar")
    assert any("simula" in item.rotulo.lower() for item in exportar.itens)


# ---------------------------------------------------------------------------
# 8. EXECUCAO DIRETA (sem pytest)
# ---------------------------------------------------------------------------
def _executar_todos() -> int:
    funcoes = [(n, f) for n, f in sorted(globals().items())
               if n.startswith("test_") and callable(f)]
    falhas = []
    for nome, funcao in funcoes:
        try:
            funcao()
            print(f"  [OK   ] {nome}")
        except Exception as exc:  # noqa: BLE001 - relatorio de teste
            print(f"  [FALHA] {nome}: {exc.__class__.__name__}: {exc}")
            falhas.append(nome)
    print(f"\n{len(funcoes) - len(falhas)}/{len(funcoes)} testes passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(_executar_todos())
