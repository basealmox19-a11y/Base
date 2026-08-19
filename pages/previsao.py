"""pages/previsao.py — Previsão de demanda com sazonalidade de Black Friday

Modelo (documentado aqui de propósito — é a peça mais sensível do módulo):
  • Dias úteis/mês = contagem REAL do calendário de cada mês específico (não é
    mais um valor fixo): todos os dias do mês exceto domingo — ou seja, sábado
    conta como dia cheio (peso 1,0), só domingo é dia fechado (peso 0). Um mês
    de 31 dias com 4 domingos tem 27 dias úteis; agosto/26 tem 26.
  • Consumo-base: para cada mês FECHADO do histórico, o total consumido naquele
    mês é dividido pelos dias úteis REAIS daquele mês específico (ver acima),
    gerando uma taxa diária própria por mês. Essas taxas mensais (já
    normalizadas) passam pelo expurgo de outliers e depois pela média móvel
    ponderada por recência (peso maior pros meses mais recentes) — resultado:
    "taxa diária de referência".
  • Consumo diário projetado = taxa_diaria_referencia × peso do dia da semana
    (seg-sáb=1,0 · dom=0) × fator sazonal do mês (só Out/Nov/Dez levam o fator
    de Black Friday — a média-base nunca é inflada por ele).
  • Ponto de pedido e ruptura: simulação dia a dia a partir de hoje, recalculada
    do zero a cada execução — reflete qualquer movimentação nova. Datas em
    dd/mm/aaaa.
  • Nível de serviço: reconstrução retroativa do saldo (a partir do estoque
    atual, andando para trás pelas movimentações) para checar se cada entrada
    real ocorreu em até N dias (lead time configurado) depois do saldo
    reconstruído cruzar o ponto de pedido atual. É uma aproximação — assume que
    o ponto de pedido de hoje também valia no passado, na ausência de um
    histórico de saldo diário armazenado.
"""
import streamlit as st, datetime, io, calendar, statistics, math
from collections import defaultdict
import pandas as pd
import plotly.graph_objects as go
from openpyxl.utils import get_column_letter
from utils.database import historico_saidas_previsao, historico_entradas_previsao
from utils.auth import pode
from utils.ui import kpi_html
from utils.fmt import qtd_br
from utils.sanitize import esc

_PL = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
           font=dict(family="Plus Jakarta Sans", size=11), margin=dict(l=0, r=0, t=20, b=0))

# ── Parâmetros do modelo (ajustáveis) ─────────────────────────────
FATOR_SAZONAL_BF = 0.15                    # crescimento estimado de mercado p/ Out-Dez (ponderado 2023-2025, sem 2022)
PESO_SAZONAL_MES = {10: 0.40, 11: 1.00, 12: 0.60}   # Out = rampa, Nov = pico, Dez = resíduo BF + Natal
DIAS_HISTORICO = 3650                      # sem corte prático — usa todo o histórico já registrado
DIAS_SEGURANCA_PADRAO = 5
LEAD_TIME_PADRAO_DIAS = 10                 # também é o prazo usado na medição de nível de serviço
HORIZONTE_SIMULACAO_DIAS = 400
MESES_PROJECAO_FUTUROS = 12
_NOMES_MES = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def tela_previsao_demanda():
    if not pode("previsao_demanda"):
        st.error("❌ Acesso restrito a administradores e almoxarifes.")
        return

    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📈 Previsão de Demanda</div>'
                 '<div class="pg-sub">Baseada nos meses fechados, com dias úteis reais de cada mês (sábado como dia cheio) e sazonalidade de Black Friday</div>',
                 unsafe_allow_html=True)

    with st.spinner("Calculando previsão..."):
        base = _montar_base()

    if not base["produtos"]:
        st.info("Histórico insuficiente para gerar previsão. Registre mais movimentações de saída.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    c1, c2 = st.columns(2)
    with c1:
        lead_time = st.number_input("Lead time de reposição (dias)", min_value=1,
                                     value=LEAD_TIME_PADRAO_DIAS, step=1,
                                     help="Tempo entre o pedido de compra e a chegada do produto. Também usado para medir o nível de serviço.")
    with c2:
        dias_seg = st.number_input("Estoque de segurança (dias de consumo)", min_value=0,
                                    value=DIAS_SEGURANCA_PADRAO, step=1)

    st.caption("Consumo-base: média móvel ponderada dos meses fechados (peso maior para os mais "
               "recentes), com expurgo de meses atípicos antes do cálculo.")

    produtos = _calcular_previsao_produtos(base, lead_time, dias_seg)
    resumo_setores = _calcular_resumo_setores(base)

    _kpis(produtos, base, lead_time)

    tabs = st.tabs(["Por produto", "Por setor", "Exportar"])
    with tabs[0]: _tab_produto(produtos)
    with tabs[1]: _tab_setor(base, produtos)
    with tabs[2]: _tab_exportar(produtos, resumo_setores)

    st.markdown("</div>", unsafe_allow_html=True)


# ── Coleta e agregação ─────────────────────────────────────────────
def _montar_base():
    hist = historico_saidas_previsao(DIAS_HISTORICO)
    entradas = historico_entradas_previsao(DIAS_HISTORICO)

    produtos_map = {}
    setor_movs = defaultdict(list)
    setor_produto_map = defaultdict(dict)
    for m in hist:
        prod = m.get("produto") or {}
        pid = prod.get("id") or m.get("produto_id")
        data = (m.get("criado_em") or "")[:10]
        if not pid or not data:
            continue
        qtd = float(m.get("quantidade_convertida") or 0)
        setor = m.get("setor_solicitante") or "Sem setor"
        item = {"data": data, "qtd": qtd}
        p = produtos_map.setdefault(pid, {"info": prod, "movs": []})
        p["movs"].append(item)
        setor_movs[setor].append(item)
        sp = setor_produto_map[setor].setdefault(pid, {"movs": []})
        sp["movs"].append(item)

    entradas_map = defaultdict(list)
    for e in entradas:
        pid = e.get("produto_id")
        data = (e.get("criado_em") or "")[:10]
        if not pid or not data:
            continue
        entradas_map[pid].append({"data": data, "qtd": float(e.get("quantidade_convertida") or 0)})

    return {"produtos": produtos_map, "setores": dict(setor_movs),
            "setor_produto": dict(setor_produto_map), "entradas": dict(entradas_map)}

def _extrair_categoria(info):
    c = info.get("categorias")
    if isinstance(c, dict):
        return c.get("nome") or "Sem categoria"
    if isinstance(c, list) and c:
        return (c[0] or {}).get("nome") or "Sem categoria"
    return "Sem categoria"


# ── Calendário: mês de referência, fim de mês, soma de meses ─────
def _add_meses(ano, mes, n):
    total = (mes - 1) + n
    return ano + total // 12, total % 12 + 1

def _fim_do_mes(ano, mes):
    return datetime.date(ano, mes, calendar.monthrange(ano, mes)[1])

def _dias_uteis_mes(ano, mes):
    """Dias úteis REAIS daquele mês específico: todos os dias exceto domingo
    (sábado conta como dia cheio). Substitui o antigo valor fixo de 24."""
    total_dias = calendar.monthrange(ano, mes)[1]
    domingos = sum(1 for d in range(1, total_dias + 1)
                   if datetime.date(ano, mes, d).weekday() == 6)
    return total_dias - domingos

def _meses_completos(movs):
    """Totais mensais de TODOS os meses fechados (exclui o mês corrente, em
    andamento), ordenados do mais antigo pro mais recente."""
    hoje = datetime.date.today()
    mes_atual = (hoje.year, hoje.month)
    por_mes = defaultdict(float)
    for m in movs:
        d = datetime.date.fromisoformat(m["data"])
        por_mes[(d.year, d.month)] += m["qtd"]
    por_mes.pop(mes_atual, None)
    return dict(sorted(por_mes.items()))

def _expurgar_outliers(valores):
    """Remove meses de consumo zero (não representativos — normalmente ruptura
    de estoque, não ausência de demanda). Com 4+ meses restantes, remove também
    outliers estatísticos via z-score modificado (Iglewicz-Hoaglin: 0,6745×
    (x-mediana)/MAD, limiar 3,5) — método robusto pra séries curtas, não exige
    distribuição normal. Retorna os ÍNDICES mantidos, na ordem cronológica original."""
    idx_validos = [i for i, v in enumerate(valores) if v > 0]
    if len(idx_validos) < 4:
        return idx_validos
    vals = [valores[i] for i in idx_validos]
    mediana = statistics.median(vals)
    mad = statistics.median([abs(v - mediana) for v in vals])
    if mad == 0:
        # MAD degenera a zero quando a maioria dos meses é idêntica — cai pra uma
        # regra de razão simples (fora de 0,5x–2x a mediana é expurgado)
        mantidos = [i for i in idx_validos if 0.5 * mediana <= valores[i] <= 2 * mediana]
    else:
        mantidos = [i for i in idx_validos if abs(0.6745 * (valores[i] - mediana) / mad) <= 3.5]
    return mantidos if mantidos else idx_validos

def _taxa_mensal_ponderada(movs):
    """Média móvel ponderada dos meses fechados (após expurgo de outliers), com
    peso crescente por recência (peso 1 pro mais antigo mantido, até peso N pro
    mais recente) — meses recentes pesam mais que meses antigos na taxa final.

    Cada mês é normalizado ANTES de comparar/ponderar: total do mês ÷ dias
    úteis REAIS daquele mês específico (_dias_uteis_mes — sábado dia cheio,
    só domingo fechado). Isso evita comparar/misturar meses com quantidades
    diferentes de dias úteis sob um único divisor fixo.
    Retorna a taxa diária de referência e um resumo do que foi usado/expurgado."""
    por_mes = _meses_completos(movs)
    if not por_mes:
        return 0.0, {"considerados": 0, "expurgados": 0}
    chaves = list(por_mes.keys())            # [(ano, mes), ...] cronológico
    taxas_mensais = [por_mes[(ano, mes)] / _dias_uteis_mes(ano, mes) for (ano, mes) in chaves]
    mantidos_idx = _expurgar_outliers(taxas_mensais)
    if not mantidos_idx:
        return 0.0, {"considerados": 0, "expurgados": len(taxas_mensais)}
    pesos = list(range(1, len(mantidos_idx) + 1))  # cronológico -> mais recente = maior peso
    soma_pesos = sum(pesos)
    taxa = sum(taxas_mensais[idx] * peso for idx, peso in zip(mantidos_idx, pesos)) / soma_pesos
    return taxa, {"considerados": len(mantidos_idx), "expurgados": len(taxas_mensais) - len(mantidos_idx)}


# ── Sazonalidade, peso do dia da semana e simulação dia a dia ────
def _mult_sazonal(dia):
    return 1 + FATOR_SAZONAL_BF * PESO_SAZONAL_MES.get(dia.month, 0.0)

def _peso_dia_semana(dia):
    wd = dia.weekday()          # 0=seg ... 6=dom
    if wd == 6: return 0.0      # domingo — fechado
    return 1.0                  # segunda a sábado — dia cheio

def _consumo_dia(taxa_dia_util_pleno, dia):
    return taxa_dia_util_pleno * _mult_sazonal(dia) * _peso_dia_semana(dia)

def _previsao_periodo(taxa_dia_util_pleno, dias):
    hoje = datetime.date.today()
    return sum(_consumo_dia(taxa_dia_util_pleno, hoje + datetime.timedelta(days=i)) for i in range(1, dias + 1))

def _simular(estoque_atual, taxa_dia_util_pleno, lead_time, dias_seg):
    if taxa_dia_util_pleno <= 0:
        return {"ponto_pedido_qtd": None, "previsao_30d": None, "data_pedido": None,
                "data_ruptura": None, "dias_atraso_pedido": 0, "quantidade_comprar": None}
    ponto_pedido_qtd = taxa_dia_util_pleno * (lead_time + dias_seg)
    hoje = datetime.date.today()

    # Se o estoque de HOJE já está no ponto de pedido ou abaixo dele, o pedido
    # já deveria ter saído no passado — reconstrói retroativamente (somando de
    # volta o consumo dia a dia) a data em que o saldo cruzou o ponto de pedido,
    # pra dizer quantos dias de atraso já existem. Sem isso, a simulação (que só
    # olha pra frente) nunca encontra essa data e o item simplesmente some do
    # alerta, mesmo sendo o mais urgente de todos.
    data_pedido = None
    dias_atraso_pedido = 0
    if estoque_atual <= ponto_pedido_qtd:
        saldo_retro = estoque_atual
        dia_retro = hoje
        for _ in range(HORIZONTE_SIMULACAO_DIAS):
            dia_retro -= datetime.timedelta(days=1)
            saldo_retro += _consumo_dia(taxa_dia_util_pleno, dia_retro)
            dias_atraso_pedido += 1
            if saldo_retro >= ponto_pedido_qtd:
                break
        data_pedido = dia_retro

    saldo = estoque_atual
    data_ruptura = hoje if estoque_atual <= 0 else None
    previsao_30d = 0.0
    for i in range(1, HORIZONTE_SIMULACAO_DIAS + 1):
        dia = hoje + datetime.timedelta(days=i)
        consumo = _consumo_dia(taxa_dia_util_pleno, dia)
        if i <= 30:
            previsao_30d += consumo
        anterior = saldo
        saldo = max(saldo - consumo, 0.0)
        if data_pedido is None and anterior > ponto_pedido_qtd >= saldo:
            data_pedido = dia
        if data_ruptura is None and anterior > 0 and saldo <= 0:
            data_ruptura = dia
        if data_pedido and data_ruptura:
            break

    # Quantidade a comprar: cobre o consumo esperado até a chegada do pedido
    # (lead time) e ainda deixa o estoque de segurança reconstituído na chegada
    # — ou seja, repõe até o nível em que o PRÓXIMO ponto de pedido só seria
    # cruzado de novo depois de mais um ciclo de lead time.
    quantidade_comprar = 0.0
    if estoque_atual <= ponto_pedido_qtd:
        nivel_alvo = ponto_pedido_qtd + taxa_dia_util_pleno * lead_time
        quantidade_comprar = max(0.0, nivel_alvo - estoque_atual)

    return {"ponto_pedido_qtd": ponto_pedido_qtd, "previsao_30d": previsao_30d,
            "data_pedido": data_pedido, "data_ruptura": data_ruptura,
            "dias_atraso_pedido": dias_atraso_pedido, "quantidade_comprar": quantidade_comprar}

def _forecast_mensal(taxa_dia_util_pleno):
    """Mês em vigor (parcial, do dia seguinte até o fim do mês) + 12 meses completos."""
    if taxa_dia_util_pleno <= 0:
        return []
    hoje = datetime.date.today()
    resultado = []
    cursor = hoje + datetime.timedelta(days=1)
    fim_mes_atual = _fim_do_mes(hoje.year, hoje.month)
    total = 0.0
    while cursor <= fim_mes_atual:
        total += _consumo_dia(taxa_dia_util_pleno, cursor)
        cursor += datetime.timedelta(days=1)
    resultado.append({"ano": hoje.year, "mes": hoje.month, "valor": total})

    ano, mes = _add_meses(hoje.year, hoje.month, 1)
    for _ in range(MESES_PROJECAO_FUTUROS):
        d_fim = _fim_do_mes(ano, mes)
        cursor = datetime.date(ano, mes, 1)
        total = 0.0
        while cursor <= d_fim:
            total += _consumo_dia(taxa_dia_util_pleno, cursor)
            cursor += datetime.timedelta(days=1)
        resultado.append({"ano": ano, "mes": mes, "valor": total})
        ano, mes = _add_meses(ano, mes, 1)
    return resultado


# ── Cálculo por produto ──────────────────────────────────────────
def _calcular_previsao_produtos(base, lead_time, dias_seg):
    out = []
    for pid, p in base["produtos"].items():
        info, movs = p["info"], p["movs"]
        taxa, expurgo = _taxa_mensal_ponderada(movs)
        estoque_atual = float(info.get("quantidade_total_secundaria") or 0)
        fator = float(info.get("fator_conversao") or 1) or 1.0
        sim = _simular(estoque_atual, taxa, lead_time, dias_seg)
        qtd_comprar_sec = sim["quantidade_comprar"] or 0.0
        # arredonda pra cima: não dá pra comprar fração da unidade primária (caixa, fardo, etc.)
        qtd_comprar_prim = math.ceil(qtd_comprar_sec / fator - 1e-9) if qtd_comprar_sec > 0 else 0
        out.append({
            "id": pid, "nome": info.get("nome", "—"), "codigo": info.get("codigo_interno", "—"),
            "unidade": info.get("unidade_secundaria", "UN"),
            "unidade_primaria": info.get("unidade_primaria", "UN"), "fator_conversao": fator,
            "categoria": _extrair_categoria(info),
            "estoque_atual": estoque_atual, "consumo_diario": taxa, "movs": movs, "expurgo": expurgo,
            "forecast_mensal": _forecast_mensal(taxa),
            "previsao_30d": sim["previsao_30d"], "ponto_pedido_qtd": sim["ponto_pedido_qtd"],
            "data_pedido": sim["data_pedido"], "data_ruptura": sim["data_ruptura"],
            "dias_atraso_pedido": sim["dias_atraso_pedido"],
            "quantidade_comprar_secundaria": qtd_comprar_sec,
            "quantidade_comprar_primaria": qtd_comprar_prim,
        })
    out.sort(key=lambda i: (i["data_pedido"] is None, i["data_pedido"] or datetime.date.max))
    return out


# ── Resumo por setor (usado no relatório exportável) ──────────────
def _calcular_resumo_setores(base):
    out = []
    for setor, movs in base["setores"].items():
        taxa, _expurgo = _taxa_mensal_ponderada(movs)
        out.append({
            "setor": setor, "consumo_diario": taxa,
            "previsao_30d": _previsao_periodo(taxa, 30) if taxa > 0 else 0.0,
            "previsao_12m": _previsao_periodo(taxa, 365) if taxa > 0 else 0.0,
        })
    out.sort(key=lambda s: -s["previsao_12m"])
    return out


# ── Nível de serviço (reconstrução retroativa do saldo) ───────────
def _nivel_servico(produtos, base, lead_time):
    entradas_por_produto = base.get("entradas", {})
    total = no_prazo = 0
    for p in produtos:
        if p["ponto_pedido_qtd"] is None:
            continue
        evs_entrada = entradas_por_produto.get(p["id"], [])
        if not evs_entrada:
            continue
        eventos = [{"data": m["data"], "tipo": "saida", "qtd": m["qtd"]} for m in p["movs"]]
        eventos += [{"data": e["data"], "tipo": "entrada", "qtd": e["qtd"]} for e in evs_entrada]

        saldo = p["estoque_atual"]
        pontos = [(datetime.date.today(), saldo)]
        for ev in sorted(eventos, key=lambda e: e["data"], reverse=True):
            if ev["tipo"] == "saida":
                saldo += ev["qtd"]      # saldo ANTES desta saída era maior
            else:
                saldo -= ev["qtd"]      # saldo ANTES desta entrada era menor
            pontos.append((datetime.date.fromisoformat(ev["data"]), saldo))
        pontos.sort(key=lambda x: x[0])  # crescente por data

        cursor_desde = None  # marca a entrada anterior, pra não reaproveitar um cruzamento já resolvido
        for e in sorted(evs_entrada, key=lambda x: x["data"]):
            data_entrada = datetime.date.fromisoformat(e["data"])
            gatilho = None
            for d, s in pontos:
                if cursor_desde is not None and d <= cursor_desde:
                    continue
                if d > data_entrada:
                    break
                if s <= p["ponto_pedido_qtd"]:
                    gatilho = d
                    break  # primeira data em que cruzou — é o gatilho real, não a última antes da entrada
            total += 1
            if gatilho is None:
                no_prazo += 1  # reposição preventiva, feita antes de cruzar o ponto de pedido
            elif (data_entrada - gatilho).days <= lead_time:
                no_prazo += 1
            cursor_desde = data_entrada
    return round(100 * no_prazo / total) if total else None

def _cobertura_media(produtos):
    hoje = datetime.date.today()
    dias = [(p["data_ruptura"] - hoje).days for p in produtos if p["data_ruptura"]]
    return round(sum(dias) / len(dias)) if dias else None


# ── UI: cabeçalho / KPIs ───────────────────────────────────────────
def _fmt_data(d):
    return d.strftime("%d/%m/%Y") if d else "—"

def _status_reposicao(p, hoje):
    if p["data_pedido"] is None:
        return "Sem dados suficientes", "var(--t3)"
    if p.get("dias_atraso_pedido"):
        return f'Atrasado há {p["dias_atraso_pedido"]}d', "var(--err)"
    dias = (p["data_pedido"] - hoje).days
    if dias <= 0:
        return "Repor agora", "var(--err)"
    if dias <= 30:
        return "Repor em breve", "var(--warn)"
    return "OK", "var(--ok)"

def _kpis(produtos, base, lead_time):
    hoje = datetime.date.today()
    atrasados = sum(1 for p in produtos if p.get("dias_atraso_pedido"))
    repor_30d = sum(1 for p in produtos if p["data_pedido"] and not p.get("dias_atraso_pedido") and (p["data_pedido"] - hoje).days <= 30)
    cobertura = _cobertura_media(produtos)
    nivel = _nivel_servico(produtos, base, lead_time)
    cor_nivel = "var(--ok)" if (nivel or 0) >= 90 else ("var(--warn)" if nivel is not None else "var(--t3)")
    st.markdown(
        f'<div class="kpis" style="grid-template-columns:repeat(4,1fr);margin:.7rem 0 1rem;">'
        f'{kpi_html("Pedidos atrasados", atrasados, "já deveriam ter saído", "var(--err)")}'
        f'{kpi_html("Reposição necessária em 30d", repor_30d, "ainda dentro do prazo", "var(--warn)")}'
        f'{kpi_html("Cobertura média do estoque", f"{cobertura} dias" if cobertura is not None else "—", "", "var(--t2)")}'
        f'{kpi_html("Nível de serviço", f"{nivel}%" if nivel is not None else "—", f"lead time de {lead_time}d", cor_nivel)}'
        f'</div>', unsafe_allow_html=True)


# ── Aba Por produto — com filtro de categoria ─────────────────────
def _tab_produto(produtos):
    st.markdown('<div class="card"><div class="card-h">Previsão por produto (SKU)</div>', unsafe_allow_html=True)
    categorias = ["Todas"] + sorted({p["categoria"] for p in produtos})
    cat_sel = st.selectbox("Categoria", categorias, key="prev_cat_sel")
    produtos_f = produtos if cat_sel == "Todas" else [p for p in produtos if p["categoria"] == cat_sel]

    def _celula_base(p):
        exp = p["expurgo"]
        txt = f'{exp["considerados"]} meses'
        if exp["expurgados"]:
            txt += f' · {exp["expurgados"]} exp.'
        return txt

    def _celula_pedido(p):
        if p["data_pedido"] is None:
            return "—"
        if p["dias_atraso_pedido"]:
            return f'{_fmt_data(p["data_pedido"])} <span style="color:var(--err);font-size:.7rem;">(atrasado {p["dias_atraso_pedido"]}d)</span>'
        return _fmt_data(p["data_pedido"])

    def _celula_comprar(p):
        if p["quantidade_comprar_primaria"] <= 0:
            return "—"
        return f'{qtd_br(p["quantidade_comprar_primaria"])} {esc(p["unidade_primaria"])}'

    rows = "".join(
        f'<tr><td><strong>{esc(p["nome"])}</strong><br>'
        f'<span style="color:var(--t3);font-size:.72rem;">{esc(p["codigo"])} · {esc(p["categoria"])}</span></td>'
        f'<td>{qtd_br(round(p["estoque_atual"]))} {esc(p["unidade"])}</td>'
        f'<td>{qtd_br(round(p["previsao_30d"])) if p["previsao_30d"] is not None else "—"}</td>'
        f'<td style="color:var(--err);font-weight:700;">{_celula_pedido(p)}</td>'
        f'<td>{_fmt_data(p["data_ruptura"])}</td>'
        f'<td style="font-weight:600;">{_celula_comprar(p)}</td>'
        f'<td style="color:var(--t3);font-size:.75rem;">{_celula_base(p)}</td></tr>'
        for p in produtos_f)
    st.markdown(
        f'<table class="tbl"><thead><tr><th>Produto</th><th>Estoque atual</th>'
        f'<th>Previsão 30 dias</th><th>Ponto de Pedido</th><th>Ruptura Prevista</th>'
        f'<th>Comprar agora</th><th>Base do cálculo</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    opcoes = {p["nome"]: p for p in produtos_f if p["consumo_diario"] > 0}
    if opcoes:
        st.markdown('<div class="card" style="margin-top:1rem;">'
                     '<div class="card-h">Simulação de estoque — mês em vigor + 12 meses</div>', unsafe_allow_html=True)
        sel = st.selectbox("Produto", list(opcoes.keys()), key="prev_sel_prod")
        _grafico_produto(opcoes[sel])
        st.markdown("</div>", unsafe_allow_html=True)

def _grafico_produto(p):
    hist_por_mes = defaultdict(float)
    for m in p["movs"]:
        d = datetime.date.fromisoformat(m["data"])
        hist_por_mes[(d.year, d.month)] += m["qtd"]
    hist_items = sorted(hist_por_mes.items())
    hist_x = [f'{_NOMES_MES[mes]}/{str(ano)[2:]}' for (ano, mes), _ in hist_items]
    hist_y = [v for _, v in hist_items]

    forecast = p["forecast_mensal"]
    fc_x = [f'{_NOMES_MES[f["mes"]]}/{str(f["ano"])[2:]}' for f in forecast]
    fc_y = [f["valor"] for f in forecast]
    saldo = p["estoque_atual"]
    traj_y = []
    for f in forecast:
        saldo = max(saldo - f["valor"], 0.0)
        traj_y.append(saldo)

    ordem_x = hist_x + [x for x in fc_x if x not in hist_x]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=hist_x, y=hist_y, name="Consumo mensal (real)", marker_color="rgba(120,120,120,.5)"))
    fig.add_trace(go.Bar(x=fc_x, y=fc_y, name="Consumo previsto", marker_color="rgba(204,0,0,.55)"))
    fig.add_trace(go.Scatter(x=fc_x, y=traj_y, name="Estoque projetado", mode="lines+markers",
                              line=dict(color="#CC0000", width=2), yaxis="y2"))
    if p["ponto_pedido_qtd"] is not None:
        fig.add_trace(go.Scatter(x=fc_x, y=[p["ponto_pedido_qtd"]] * len(fc_x), name="Ponto de pedido ideal",
                                  mode="lines", line=dict(color="#B45309", width=1.5, dash="dash"), yaxis="y2"))
    if p["data_pedido"]:
        rotulo = f'{_NOMES_MES[p["data_pedido"].month]}/{str(p["data_pedido"].year)[2:]}'
        if rotulo in ordem_x:
            fig.add_vline(x=rotulo, line_width=1, line_dash="dot", line_color="#B45309")
            fig.add_annotation(x=rotulo, y=1, yref="paper", showarrow=False,
                                text=f"Pedido em {_fmt_data(p['data_pedido'])}", font=dict(size=10, color="#B45309"))
    fig.update_layout(**_PL, height=340, barmode="overlay", legend=dict(bgcolor="rgba(0,0,0,0)"),
                       xaxis=dict(type="category", categoryorder="array", categoryarray=ordem_x),
                       yaxis=dict(title=f'Consumo mensal ({p["unidade"]})', gridcolor="rgba(0,0,0,.05)"),
                       yaxis2=dict(title="Estoque projetado", overlaying="y", side="right", gridcolor="rgba(0,0,0,0)"))
    st.plotly_chart(fig, use_container_width=True)


# ── Aba Por setor — filtro individual + tabela de ressuprimento ──
def _tab_setor(base, produtos):
    st.markdown('<div class="card"><div class="card-h">Consumo por setor</div>', unsafe_allow_html=True)
    setores_disponiveis = sorted(base["setores"].keys())
    if not setores_disponiveis:
        st.info("Sem dados de consumo por setor no período.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    c1, c2 = st.columns([1, 1.4])
    with c1:
        setor_sel = st.selectbox("Setor", setores_disponiveis, key="prev_setor_sel")

    movs_setor = base["setores"][setor_sel]
    datas = sorted(datetime.date.fromisoformat(m["data"]) for m in movs_setor)
    with c2:
        intervalo = st.date_input("Período", value=(datas[0], datas[-1]),
                                   min_value=datas[0], max_value=datas[-1], key="prev_setor_periodo")
    if isinstance(intervalo, tuple) and len(intervalo) == 2:
        d_ini, d_fim = intervalo
    else:
        d_ini, d_fim = datas[0], datas[-1]

    movs_filtrados = [m for m in movs_setor if d_ini <= datetime.date.fromisoformat(m["data"]) <= d_fim]
    taxa_setor, _expurgo_setor = _taxa_mensal_ponderada(movs_setor)
    _grafico_setor(movs_filtrados, taxa_setor)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card" style="margin-top:1rem;">'
                 '<div class="card-h">Itens consumidos por este setor — previsão de ressuprimento</div>', unsafe_allow_html=True)
    produtos_by_id = {p["id"]: p for p in produtos}
    itens_setor = base["setor_produto"].get(setor_sel, {})
    hoje = datetime.date.today()
    linhas = ""
    for pid, sp in itens_setor.items():
        prod_geral = produtos_by_id.get(pid)
        if not prod_geral:
            continue
        qtd_periodo = sum(m["qtd"] for m in sp["movs"] if d_ini <= datetime.date.fromisoformat(m["data"]) <= d_fim)
        if qtd_periodo <= 0:
            continue
        status, cor = _status_reposicao(prod_geral, hoje)
        linhas += (
            f'<tr><td><strong>{esc(prod_geral["nome"])}</strong></td>'
            f'<td>{qtd_br(round(qtd_periodo))} {esc(prod_geral["unidade"])}</td>'
            f'<td>{_fmt_data(prod_geral["data_pedido"])}</td>'
            f'<td><span style="color:{cor};font-weight:700;">{status}</span></td></tr>'
        )
    if linhas:
        st.markdown(
            f'<table class="tbl"><thead><tr><th>Item</th><th>Consumido no período</th>'
            f'<th>Reposição prevista em</th><th>Situação</th></tr></thead><tbody>{linhas}</tbody></table>',
            unsafe_allow_html=True)
    else:
        st.info("Nenhum item com consumo no período selecionado.")
    st.markdown("</div>", unsafe_allow_html=True)

def _grafico_setor(movs_filtrados, taxa_setor):
    hist_por_mes = defaultdict(float)
    for m in movs_filtrados:
        d = datetime.date.fromisoformat(m["data"])
        hist_por_mes[(d.year, d.month)] += m["qtd"]
    hist_items = sorted(hist_por_mes.items())
    hist_x = [f'{_NOMES_MES[mes]}/{str(ano)[2:]}' for (ano, mes), _ in hist_items]
    hist_y = [v for _, v in hist_items]

    forecast = _forecast_mensal(taxa_setor)
    fc_x = [f'{_NOMES_MES[f["mes"]]}/{str(f["ano"])[2:]}' for f in forecast]
    fc_y = [f["valor"] for f in forecast]

    ordem_x = hist_x + [x for x in fc_x if x not in hist_x]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=hist_x, y=hist_y, name="Consumo real", marker_color="rgba(204,0,0,.55)"))
    fig.add_trace(go.Scatter(x=fc_x, y=fc_y, name="Consumo previsto", mode="lines+markers",
                              line=dict(color="#F2C94C", width=2.5)))
    fig.update_layout(**_PL, height=320, legend=dict(bgcolor="rgba(0,0,0,0)"),
                       xaxis=dict(type="category", categoryorder="array", categoryarray=ordem_x),
                       yaxis=dict(title="Consumo mensal", gridcolor="rgba(0,0,0,.05)"))
    st.plotly_chart(fig, use_container_width=True)


# ── Exportação (recalculada a cada execução — sempre reflete o histórico atual) ──
def _autoajustar_colunas(ws, df):
    for i, col in enumerate(df.columns):
        maior = max((len(str(v)) for v in df[col].tolist()), default=0)
        largura = max(maior, len(str(col))) + 2
        ws.column_dimensions[get_column_letter(i + 1)].width = largura

_CARACTERES_FORMULA = ("=", "+", "-", "@", "\t", "\r")
def _sanitizar_celula(v):
    if isinstance(v, str) and v.startswith(_CARACTERES_FORMULA):
        return "'" + v
    return v

def _planilha_setor(resumo_setores):
    df = pd.DataFrame([{
        "Setor": _sanitizar_celula(s["setor"]),
        "Consumo diário médio": round(s["consumo_diario"]),
        "Previsão 30 dias": round(s["previsao_30d"]),
        "Previsão 12 meses (com sazonalidade BF)": round(s["previsao_12m"]),
    } for s in resumo_setores])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Previsão por Setor")
        _autoajustar_colunas(w.sheets["Previsão por Setor"], df)
    buf.seek(0)
    return buf.getvalue()

def _planilha_produto(produtos):
    df = pd.DataFrame([{
        "Código": _sanitizar_celula(p["codigo"]), "Produto": _sanitizar_celula(p["nome"]),
        "Categoria": _sanitizar_celula(p["categoria"]),
        "Estoque atual": round(p["estoque_atual"]), "Unidade": p["unidade"],
        "Consumo diário médio": round(p["consumo_diario"]),
        "Previsão 30 dias": round(p["previsao_30d"]) if p["previsao_30d"] is not None else None,
        "Ponto de Pedido": _fmt_data(p["data_pedido"]),
        "Dias de atraso": p["dias_atraso_pedido"] or 0,
        "Ruptura Prevista": _fmt_data(p["data_ruptura"]),
        "Comprar agora": p["quantidade_comprar_primaria"] if p["quantidade_comprar_primaria"] > 0 else 0,
        "Unidade de Compra": p["unidade_primaria"],
    } for p in produtos])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Previsão por SKU")
        _autoajustar_colunas(w.sheets["Previsão por SKU"], df)
    buf.seek(0)
    return buf.getvalue()

def _tab_exportar(produtos, resumo_setores):
    st.markdown('<div class="card"><div class="card-h">Exportar relatórios</div>', unsafe_allow_html=True)
    st.caption("Os relatórios são recalculados com os dados mais recentes no momento do download.")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 Baixar previsão por setor (.xlsx)",
            data=_planilha_setor(resumo_setores),
            file_name=f"previsao_demanda_setor_{datetime.date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True, key="btn_export_prev_setor")
    with c2:
        st.download_button("📥 Baixar previsão por SKU (.xlsx)",
            data=_planilha_produto(produtos),
            file_name=f"previsao_demanda_sku_{datetime.date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True, key="btn_export_prev_sku")
    st.markdown("</div>", unsafe_allow_html=True)
