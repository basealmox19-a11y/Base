"""pages/previsao.py — Previsão de demanda (30 dias) com sazonalidade de Black Friday

Modelo (documentado aqui de propósito — é a peça mais sensível do módulo):
  • Consumo-base: média móvel simples das semanas COMPLETAS de histórico. O sistema
    tem só ~2 meses de implantação — curto demais para uma tendência linear ser
    confiável, por isso o método é média simples por semana, não regressão.
  • Sazonalidade de Black Friday: como ainda não há histórico próprio de Out/Nov/Dez,
    aplica-se um fator de mercado pesquisado (ver FATOR_SAZONAL_BF), dia a dia,
    conforme o mês de cada dia projetado.
  • Ponto de pedido e ruptura prevista: simulação dia a dia do saldo de estoque a
    partir do consumo diário médio — recalculada do zero a cada execução da tela,
    então reflete automaticamente qualquer movimentação de saída nova. Datas
    exibidas em dd/mm/aaaa.
"""
import streamlit as st, datetime, io
from collections import defaultdict
import pandas as pd
import plotly.graph_objects as go
from openpyxl.utils import get_column_letter
from utils.database import historico_saidas_previsao
from utils.auth import pode
from utils.ui import kpi_html
from utils.fmt import qtd_br
from utils.sanitize import esc

_PL = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
           font=dict(family="Plus Jakarta Sans", size=11), margin=dict(l=0, r=0, t=20, b=0))

# ── Parâmetros do modelo (ajustáveis) ─────────────────────────────
FATOR_SAZONAL_BF = 0.15                    # crescimento estimado de mercado p/ Out-Dez (ponderado 2023-2025, sem 2022)
PESO_SAZONAL_MES = {10: 0.40, 11: 1.00, 12: 0.60}   # Out = rampa, Nov = pico, Dez = resíduo BF + Natal
DIAS_HISTORICO = 3650                      # sem corte prático — usa todo o histórico de movimentações já registrado
                                            # (a sazonalidade acima é a ÚNICA variação aplicada fora da média real;
                                            #  a média-base nunca é inflada, só o período de Out/Nov/Dez na projeção)
DIAS_SEGURANCA_PADRAO = 3
LEAD_TIME_PADRAO_DIAS = 7
HORIZONTE_SIMULACAO_DIAS = 400             # até onde a simulação dia-a-dia procura pedido/ruptura
SEMANAS_GRAFICO_PRODUTO = 16
SEMANAS_PREVISAO_SETOR = 8


def tela_previsao_demanda():
    if not pode("previsao_demanda"):
        st.error("❌ Acesso restrito a administradores e almoxarifes.")
        return

    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📈 Previsão de Demanda</div>'
                 '<div class="pg-sub">Previsão de 30 dias por média móvel semanal, com sazonalidade de Black Friday</div>',
                 unsafe_allow_html=True)

    with st.spinner("Calculando previsão..."):
        base = _montar_base()

    if not base["produtos"]:
        st.info("Histórico insuficiente para gerar previsão. Registre mais movimentações de saída.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    c1, c2 = st.columns(2)
    with c1:
        lead_time = st.number_input("Tempo médio de reposição (dias)", min_value=1,
                                     value=LEAD_TIME_PADRAO_DIAS, step=1,
                                     help="Tempo entre o pedido de compra e a chegada do produto no almoxarifado.")
    with c2:
        dias_seg = st.number_input("Estoque de segurança (dias de consumo)", min_value=0,
                                    value=DIAS_SEGURANCA_PADRAO, step=1)

    produtos = _calcular_previsao_produtos(base, lead_time, dias_seg)
    resumo_setores = _calcular_resumo_setores(base)

    _kpis(produtos)

    tabs = st.tabs(["Por produto", "Por setor", "Exportar"])
    with tabs[0]: _tab_produto(produtos)
    with tabs[1]: _tab_setor(base)
    with tabs[2]: _tab_exportar(produtos, resumo_setores)

    st.markdown("</div>", unsafe_allow_html=True)


# ── Coleta e agregação ─────────────────────────────────────────────
def _montar_base():
    hist = historico_saidas_previsao(DIAS_HISTORICO)
    produtos_map = {}
    setor_movs = defaultdict(list)
    for m in hist:
        prod = m.get("produto") or {}
        pid = prod.get("id") or m.get("produto_id")
        data = (m.get("criado_em") or "")[:10]
        if not pid or not data:
            continue
        qtd = float(m.get("quantidade_convertida") or 0)
        setor = m.get("setor_solicitante") or "Sem setor"
        p = produtos_map.setdefault(pid, {"info": prod, "movs": []})
        item = {"data": data, "qtd": qtd}
        p["movs"].append(item)
        setor_movs[setor].append(item)
    return {"produtos": produtos_map, "setores": dict(setor_movs)}


# ── Semana ISO (chave = segunda-feira daquela semana) ─────────────
def _semana_inicio(ano, semana):
    return datetime.date.fromisocalendar(ano, semana, 1)

def _semana_atual():
    hoje = datetime.date.today()
    ano, semana, _ = hoje.isocalendar()
    return _semana_inicio(ano, semana)

def _serie_semanal(movs):
    """Agrupa quantidade por semana (chave = segunda-feira da semana ISO)."""
    porw = defaultdict(float)
    for m in movs:
        d = datetime.date.fromisoformat(m["data"])
        ano, semana, _ = d.isocalendar()
        porw[_semana_inicio(ano, semana)] += m["qtd"]
    return dict(sorted(porw.items()))

def _consumo_diario_medio(movs):
    """Média móvel simples: média das semanas COMPLETAS de histórico, convertida
    para consumo/dia. A semana corrente (em andamento) é excluída para não
    distorcer a média com um período parcial."""
    if not movs:
        return 0.0
    serie = _serie_semanal(movs)
    atual = _semana_atual()
    completas = {k: v for k, v in serie.items() if k != atual}
    if completas:
        return (sum(completas.values()) / len(completas)) / 7
    # só há dado na semana corrente (produto novo) — usa a taxa observada até agora
    datas = sorted(m["data"] for m in movs)
    dias = (datetime.date.fromisoformat(datas[-1]) - datetime.date.fromisoformat(datas[0])).days + 1
    return sum(m["qtd"] for m in movs) / max(dias, 1)


# ── Sazonalidade e simulação dia a dia ────────────────────────────
def _mult_sazonal(dia):
    return 1 + FATOR_SAZONAL_BF * PESO_SAZONAL_MES.get(dia.month, 0.0)

def _previsao_periodo(daily_rate, dias):
    hoje = datetime.date.today()
    return sum(daily_rate * _mult_sazonal(hoje + datetime.timedelta(days=i)) for i in range(1, dias + 1))

def _simular(estoque_atual, daily_rate, lead_time, dias_seg):
    """Simula o saldo de estoque dia a dia a partir de amanhã, aplicando a
    sazonalidade de cada dia, até encontrar a data exata de pedido e de ruptura."""
    if daily_rate <= 0:
        return {"ponto_pedido_qtd": None, "previsao_30d": None, "data_pedido": None, "data_ruptura": None}
    ponto_pedido_qtd = daily_rate * (lead_time + dias_seg)
    hoje = datetime.date.today()
    saldo = estoque_atual
    data_pedido = data_ruptura = None
    previsao_30d = 0.0
    for i in range(1, HORIZONTE_SIMULACAO_DIAS + 1):
        dia = hoje + datetime.timedelta(days=i)
        consumo = daily_rate * _mult_sazonal(dia)
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
    return {"ponto_pedido_qtd": ponto_pedido_qtd, "previsao_30d": previsao_30d,
            "data_pedido": data_pedido, "data_ruptura": data_ruptura}


# ── Cálculo por produto ──────────────────────────────────────────
def _calcular_previsao_produtos(base, lead_time, dias_seg):
    out = []
    for pid, p in base["produtos"].items():
        info, movs = p["info"], p["movs"]
        daily_rate = _consumo_diario_medio(movs)
        estoque_atual = float(info.get("quantidade_total_secundaria") or 0)
        sim = _simular(estoque_atual, daily_rate, lead_time, dias_seg)
        out.append({
            "id": pid, "nome": info.get("nome", "—"), "codigo": info.get("codigo_interno", "—"),
            "unidade": info.get("unidade_secundaria", "UN"), "estoque_atual": estoque_atual,
            "consumo_diario": daily_rate, "serie_semanal": _serie_semanal(movs),
            "previsao_30d": sim["previsao_30d"], "ponto_pedido_qtd": sim["ponto_pedido_qtd"],
            "data_pedido": sim["data_pedido"], "data_ruptura": sim["data_ruptura"],
        })
    out.sort(key=lambda i: (i["data_pedido"] is None, i["data_pedido"] or datetime.date.max))
    return out


# ── Resumo por setor (usado no relatório exportável) ──────────────
def _calcular_resumo_setores(base):
    out = []
    for setor, movs in base["setores"].items():
        daily_rate = _consumo_diario_medio(movs)
        out.append({
            "setor": setor, "consumo_diario": daily_rate,
            "previsao_30d": _previsao_periodo(daily_rate, 30) if daily_rate > 0 else 0.0,
            "previsao_12m": _previsao_periodo(daily_rate, 365) if daily_rate > 0 else 0.0,
        })
    out.sort(key=lambda s: -s["previsao_12m"])
    return out


# ── UI ────────────────────────────────────────────────────────────
def _fmt_data(d):
    return d.strftime("%d/%m/%Y") if d else "—"

def _kpis(produtos):
    hoje = datetime.date.today()
    total_30d = sum(p["previsao_30d"] or 0 for p in produtos)
    urgentes = sum(1 for p in produtos if p["data_pedido"] and (p["data_pedido"] - hoje).days <= 30)
    sem_dados = sum(1 for p in produtos if p["previsao_30d"] is None)
    st.markdown(
        f'<div class="kpis" style="grid-template-columns:repeat(3,1fr);margin:.7rem 0 1rem;">'
        f'{kpi_html("Previsão consumo (30d)", qtd_br(round(total_30d)), "", "var(--t2)")}'
        f'{kpi_html("Pedido necessário em ≤30d", urgentes, "", "var(--err)")}'
        f'{kpi_html("Sem histórico suficiente", sem_dados, "", "var(--warn)")}'
        f'</div>', unsafe_allow_html=True)

def _tab_produto(produtos):
    st.markdown('<div class="card"><div class="card-h">Previsão por produto (SKU)</div>', unsafe_allow_html=True)
    rows = "".join(
        f'<tr><td><strong>{esc(p["nome"])}</strong><br>'
        f'<span style="color:var(--t3);font-size:.72rem;">{esc(p["codigo"])}</span></td>'
        f'<td>{qtd_br(round(p["estoque_atual"]))} {esc(p["unidade"])}</td>'
        f'<td>{qtd_br(round(p["previsao_30d"])) if p["previsao_30d"] is not None else "—"}</td>'
        f'<td style="color:var(--err);font-weight:700;">{_fmt_data(p["data_pedido"])}</td>'
        f'<td>{_fmt_data(p["data_ruptura"])}</td></tr>'
        for p in produtos)
    st.markdown(
        f'<table class="tbl"><thead><tr><th>Produto</th><th>Estoque atual</th>'
        f'<th>Previsão 30 dias</th><th>Ponto de Pedido</th><th>Ruptura Prevista</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    opcoes = {p["nome"]: p for p in produtos if p["consumo_diario"] > 0}
    if opcoes:
        st.markdown('<div class="card" style="margin-top:1rem;">'
                     '<div class="card-h">Simulação de estoque</div>', unsafe_allow_html=True)
        sel = st.selectbox("Produto", list(opcoes.keys()), key="prev_sel_prod")
        _grafico_produto(opcoes[sel])
        st.markdown("</div>", unsafe_allow_html=True)

def _grafico_produto(p):
    hoje = datetime.date.today()
    hist_items = sorted(p["serie_semanal"].items())
    hist_x = [d.strftime("%d/%m") for d, _ in hist_items]
    hist_y = [v for _, v in hist_items]

    saldo = p["estoque_atual"]
    proj_x, proj_y = [], []
    cursor = _semana_atual()
    for _s in range(SEMANAS_GRAFICO_PRODUTO):
        for j in range(7):
            dia = cursor + datetime.timedelta(days=j)
            if dia > hoje:
                saldo = max(saldo - p["consumo_diario"] * _mult_sazonal(dia), 0.0)
        proj_x.append(cursor.strftime("%d/%m"))
        proj_y.append(saldo)
        cursor += datetime.timedelta(days=7)

    ordem_x = hist_x + [x for x in proj_x if x not in hist_x]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=hist_x, y=hist_y, name="Consumo semanal (real)", marker_color="rgba(120,120,120,.5)"))
    fig.add_trace(go.Scatter(x=proj_x, y=proj_y, name="Estoque projetado", mode="lines+markers",
                              line=dict(color="#CC0000", width=2), yaxis="y2"))
    if p["ponto_pedido_qtd"] is not None:
        fig.add_trace(go.Scatter(x=proj_x, y=[p["ponto_pedido_qtd"]] * len(proj_x), name="Ponto de pedido ideal",
                                  mode="lines", line=dict(color="#B45309", width=1.5, dash="dash"), yaxis="y2"))
    if p["data_pedido"]:
        d_pedido = p["data_pedido"]
        ano, semana, _ = d_pedido.isocalendar()
        rotulo = _semana_inicio(ano, semana).strftime("%d/%m")
        if rotulo in ordem_x:
            fig.add_vline(x=rotulo, line_width=1, line_dash="dot", line_color="#B45309")
            fig.add_annotation(x=rotulo, y=1, yref="paper", showarrow=False,
                                text=f"Pedido em {_fmt_data(d_pedido)}", font=dict(size=10, color="#B45309"))
    fig.update_layout(**_PL, height=320, legend=dict(bgcolor="rgba(0,0,0,0)"),
                       xaxis=dict(type="category", categoryorder="array", categoryarray=ordem_x),
                       yaxis=dict(title=f'Consumo semanal ({p["unidade"]})', gridcolor="rgba(0,0,0,.05)"),
                       yaxis2=dict(title="Estoque projetado", overlaying="y", side="right", gridcolor="rgba(0,0,0,0)"))
    st.plotly_chart(fig, use_container_width=True)


# ── Aba Por setor — filtro individual + período, sem consolidação ─
def _tab_setor(base):
    st.markdown('<div class="card"><div class="card-h">Previsão por setor</div>', unsafe_allow_html=True)
    setores_disponiveis = sorted(base["setores"].keys())
    if not setores_disponiveis:
        st.info("Sem dados de consumo por setor no período.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    c1, c2 = st.columns([1, 1.4])
    with c1:
        setor_sel = st.selectbox("Setor", setores_disponiveis, key="prev_setor_sel")

    movs = base["setores"][setor_sel]
    datas = sorted(datetime.date.fromisoformat(m["data"]) for m in movs)
    with c2:
        intervalo = st.date_input("Período", value=(datas[0], datas[-1]),
                                   min_value=datas[0], max_value=datas[-1], key="prev_setor_periodo")

    if isinstance(intervalo, tuple) and len(intervalo) == 2:
        d_ini, d_fim = intervalo
    else:
        d_ini, d_fim = datas[0], datas[-1]

    movs_filtrados = [m for m in movs if d_ini <= datetime.date.fromisoformat(m["data"]) <= d_fim]
    daily_rate = _consumo_diario_medio(movs)  # taxa sobre TODO o histórico do setor, não sobre o filtro de exibição
    _grafico_setor(movs_filtrados, daily_rate)
    st.markdown("</div>", unsafe_allow_html=True)

def _grafico_setor(movs_filtrados, daily_rate):
    hist_items = sorted(_serie_semanal(movs_filtrados).items())
    hist_x = [d.strftime("%d/%m") for d, _ in hist_items]
    hist_y = [v for _, v in hist_items]

    proj_x, proj_y = [], []
    cursor = _semana_atual()
    for _s in range(SEMANAS_PREVISAO_SETOR):
        total_semana = sum(daily_rate * _mult_sazonal(cursor + datetime.timedelta(days=j)) for j in range(7))
        proj_x.append(cursor.strftime("%d/%m"))
        proj_y.append(total_semana)
        cursor += datetime.timedelta(days=7)

    ordem_x = hist_x + [x for x in proj_x if x not in hist_x]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=hist_x, y=hist_y, name="Consumo real", marker_color="rgba(204,0,0,.55)"))
    fig.add_trace(go.Scatter(x=proj_x, y=proj_y, name="Consumo previsto", mode="lines+markers",
                              line=dict(color="#F2C94C", width=2.5)))
    fig.update_layout(**_PL, height=320, legend=dict(bgcolor="rgba(0,0,0,0)"),
                       xaxis=dict(type="category", categoryorder="array", categoryarray=ordem_x),
                       yaxis=dict(title="Consumo semanal", gridcolor="rgba(0,0,0,.05)"))
    st.plotly_chart(fig, use_container_width=True)


# ── Exportação (recalculada a cada execução — sempre reflete o histórico atual) ──
def _autoajustar_colunas(ws, df):
    """Iteração Python pura (não vetorizada) — evita o bug do pandas 3.0 (backend
    Arrow) onde .astype(str).map(len) quebra em colunas com None misturado a números."""
    for i, col in enumerate(df.columns):
        maior = max((len(str(v)) for v in df[col].tolist()), default=0)
        largura = max(maior, len(str(col))) + 2
        ws.column_dimensions[get_column_letter(i + 1)].width = largura

_CARACTERES_FORMULA = ("=", "+", "-", "@", "\t", "\r")
def _sanitizar_celula(v):
    """Neutraliza injeção de fórmula em Excel: se um nome de produto, código ou
    setor vindo do banco começar com um caractere que o Excel interpreta como
    início de fórmula, prefixa com apóstrofo para forçar texto puro."""
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
        "Estoque atual": round(p["estoque_atual"]), "Unidade": p["unidade"],
        "Consumo diário médio": round(p["consumo_diario"]),
        "Previsão 30 dias": round(p["previsao_30d"]) if p["previsao_30d"] is not None else None,
        "Ponto de Pedido": _fmt_data(p["data_pedido"]),
        "Ruptura Prevista": _fmt_data(p["data_ruptura"]),
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
