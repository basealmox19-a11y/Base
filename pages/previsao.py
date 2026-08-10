"""pages/previsao.py — Previsão de demanda (12 meses) com sazonalidade de Black Friday

Modelo (documentado aqui de propósito — é a peça mais sensível do módulo):
  • Consumo-base mensal por produto: tendência linear (regressão simples) quando
    há histórico regular ("Alta" confiança), ou média simples quando o histórico
    é curto/irregular ("Média"). Itens com menos de 3 saídas registradas ficam
    marcados como "Baixa" confiança e NÃO recebem número de previsão — mostrar
    um valor ali passaria uma precisão que os dados não sustentam.
  • Sazonalidade de Black Friday: como o sistema ainda tem ~3 meses de histórico
    (insuficiente para medir o efeito comparando anos anteriores), aplica-se um
    fator de mercado pesquisado externamente (ver FATOR_SAZONAL_BF abaixo).
    Trocar por sazonalidade própria assim que houver 1-2 Black Fridays de dados
    reais no sistema.
  • Ponto de pedido / estoque mínimo ideal: consumo_diário × (lead time + dias de
    segurança). Lead time e dias de segurança são ajustáveis na tela porque não
    existem hoje como campo no cadastro de produto.
"""
import streamlit as st, datetime, io
from collections import defaultdict
import pandas as pd
import numpy as np
import plotly.graph_objects as go
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
DIAS_HISTORICO = 120                       # janela de coleta (~4 meses, cobre os ~3 meses disponíveis hoje)
DIAS_SEGURANCA_PADRAO = 3
LEAD_TIME_PADRAO_DIAS = 7
_NOMES_MES = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def tela_previsao_demanda():
    if not pode("previsao_demanda"):
        st.error("❌ Acesso restrito a administradores e almoxarifes.")
        return

    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📈 Previsão de Demanda</div>'
                 '<div class="pg-sub">Projeção 12 meses, com sazonalidade de Black Friday (Out-Nov-Dez)</div>',
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
    setores = _calcular_previsao_setores(base)

    _kpis(produtos)

    tabs = st.tabs(["Por produto", "Por setor", "Exportar"])
    with tabs[0]: _tab_produto(produtos)
    with tabs[1]: _tab_setor(setores)
    with tabs[2]: _tab_exportar(produtos, setores)

    st.markdown("</div>", unsafe_allow_html=True)


# ── Coleta e agregação ─────────────────────────────────────────────
def _montar_base():
    hist = historico_saidas_previsao(DIAS_HISTORICO)
    produtos_map = {}
    for m in hist:
        prod = m.get("produto") or {}
        pid = prod.get("id") or m.get("produto_id")
        data = (m.get("criado_em") or "")[:10]
        if not pid or not data:
            continue
        qtd = float(m.get("quantidade_convertida") or 0)
        setor = m.get("setor_solicitante") or "Sem setor"
        p = produtos_map.setdefault(pid, {"info": prod, "movs": []})
        p["movs"].append({"data": data, "qtd": qtd, "setor": setor})
    return {"produtos": produtos_map}


# ── Cálculo por produto ──────────────────────────────────────────
def _classificar_confianca(movs):
    n = len(movs)
    if n < 3:
        return "Baixa"
    semanas = {datetime.date.fromisoformat(m["data"]).isocalendar()[:2] for m in movs}
    return "Alta" if len(semanas) >= 6 else "Média"

def _serie_mensal(movs):
    porm = defaultdict(float)
    for m in movs:
        porm[m["data"][:7]] += m["qtd"]
    return dict(sorted(porm.items()))

def _consumo_diario_medio(movs, serie_mensal):
    if not movs:
        return 0.0
    datas = sorted(m["data"] for m in movs)
    dias = (datetime.date.fromisoformat(datas[-1]) - datetime.date.fromisoformat(datas[0])).days + 1
    dias = max(dias, 30)
    return sum(serie_mensal.values()) / dias

def _serie_mensal_completa(serie_mensal):
    """Remove o mês corrente (ainda em andamento) da série usada para projeção —
    um mês parcial derruba artificialmente a média e a tendência."""
    mes_atual = datetime.date.today().strftime("%Y-%m")
    return {k: v for k, v in serie_mensal.items() if k != mes_atual}

def _projetar_base_mensal(serie_mensal, confianca, consumo_diario):
    completa = _serie_mensal_completa(serie_mensal)
    valores = list(completa.values())
    if not valores:
        # só existe o mês corrente (parcial) — usa o consumo diário observado
        return consumo_diario * 30
    if confianca == "Alta" and len(valores) >= 2:
        x = np.arange(len(valores))
        slope, intercept = np.polyfit(x, valores, 1)
        return max(intercept + slope * len(valores), 0.0)
    return sum(valores) / len(valores)

def _add_meses(ano, mes, n):
    total = (mes - 1) + n
    return ano + total // 12, total % 12 + 1

def _forecast_12_meses(base_mensal, ano_ini, mes_ini):
    out = []
    for i in range(1, 13):
        ano, mes = _add_meses(ano_ini, mes_ini, i)
        peso = PESO_SAZONAL_MES.get(mes, 0.0)
        valor = base_mensal * (1 + FATOR_SAZONAL_BF * peso)
        out.append({"ano": ano, "mes": mes, "valor": valor, "sazonal": peso > 0})
    return out

def _simular_estoque(estoque_atual, forecast_mensal, consumo_diario, lead_time, dias_seg):
    ponto_pedido = consumo_diario * (lead_time + dias_seg)
    trajetoria = []
    saldo = estoque_atual
    mes_pedido = mes_ruptura = None
    for f in forecast_mensal:
        anterior = saldo
        saldo = max(saldo - f["valor"], 0.0)
        trajetoria.append({"ano": f["ano"], "mes": f["mes"], "saldo": saldo})
        if mes_pedido is None and anterior > ponto_pedido >= saldo:
            mes_pedido = (f["ano"], f["mes"])
        if mes_ruptura is None and anterior > 0 and saldo <= 0:
            mes_ruptura = (f["ano"], f["mes"])
    return {"ponto_pedido": ponto_pedido, "trajetoria": trajetoria,
            "mes_pedido": mes_pedido, "mes_ruptura": mes_ruptura}

def _calcular_previsao_produtos(base, lead_time, dias_seg):
    hoje = datetime.date.today()
    out = []
    for pid, p in base["produtos"].items():
        info, movs = p["info"], p["movs"]
        confianca = _classificar_confianca(movs)
        serie = _serie_mensal(movs)
        consumo_dia = _consumo_diario_medio(movs, serie)
        item = {
            "id": pid, "nome": info.get("nome", "—"), "codigo": info.get("codigo_interno", "—"),
            "unidade": info.get("unidade_secundaria", "UN"),
            "estoque_atual": float(info.get("quantidade_total_secundaria") or 0),
            "confianca": confianca, "consumo_diario": consumo_dia, "serie_mensal": serie,
            "forecast": [], "trajetoria": [], "previsao_30d": None,
            "ponto_pedido": None, "data_ruptura": None, "data_pedido": None,
        }
        if confianca != "Baixa" and consumo_dia > 0:
            base_mensal = _projetar_base_mensal(serie, confianca, consumo_dia)
            forecast = _forecast_12_meses(base_mensal, hoje.year, hoje.month)
            sim = _simular_estoque(item["estoque_atual"], forecast, consumo_dia, lead_time, dias_seg)
            item.update({
                "forecast": forecast, "trajetoria": sim["trajetoria"],
                "previsao_30d": forecast[0]["valor"],
                "ponto_pedido": sim["ponto_pedido"],
                "data_ruptura": sim["mes_ruptura"],
                "data_pedido": sim["mes_pedido"],
            })
        out.append(item)
    out.sort(key=lambda i: (i["data_pedido"] is None, i["data_pedido"] or (9999, 99)))
    return out


# ── Cálculo por setor ────────────────────────────────────────────
def _calcular_previsao_setores(base):
    hoje = datetime.date.today()
    por_setor = defaultdict(lambda: defaultdict(float))
    for p in base["produtos"].values():
        for m in p["movs"]:
            por_setor[m["setor"]][m["data"][:7]] += m["qtd"]
    out = []
    for setor, serie in por_setor.items():
        valores = [v for _, v in sorted(serie.items())]
        media = sum(valores) / len(valores) if valores else 0.0
        forecast = _forecast_12_meses(media, hoje.year, hoje.month)
        out.append({
            "setor": setor, "consumo_medio_mensal": media,
            "previsao_30d": forecast[0]["valor"] if forecast else 0.0,
            "previsao_12m": sum(f["valor"] for f in forecast),
            "forecast": forecast,
        })
    out.sort(key=lambda s: -s["previsao_12m"])
    return out


# ── UI ────────────────────────────────────────────────────────────
def _fmt_mes(ano_mes):
    if not ano_mes:
        return "—"
    ano, mes = ano_mes
    return f"{_NOMES_MES[mes]}/{ano}"

def _meses_ate(hoje, ano_mes):
    return (ano_mes[0] - hoje.year) * 12 + (ano_mes[1] - hoje.month)

def _kpis(produtos):
    total_30d = sum(p["previsao_30d"] or 0 for p in produtos)
    hoje = datetime.date.today()
    urgentes = sum(1 for p in produtos if p["data_pedido"] and _meses_ate(hoje, p["data_pedido"]) <= 1)
    baixa_conf = sum(1 for p in produtos if p["confianca"] == "Baixa")
    st.markdown(
        f'<div class="kpis" style="grid-template-columns:repeat(3,1fr);margin:.7rem 0 1rem;">'
        f'{kpi_html("Previsão consumo (30d)", qtd_br(total_30d), "", "var(--t2)")}'
        f'{kpi_html("Pedido necessário em ≤30d", urgentes, "", "var(--err)")}'
        f'{kpi_html("Dados insuficientes", baixa_conf, "", "var(--warn)")}'
        f'</div>', unsafe_allow_html=True)

def _tab_produto(produtos):
    st.markdown('<div class="card"><div class="card-h">Previsão por produto (SKU)</div>', unsafe_allow_html=True)
    rows = ""
    for p in produtos:
        cor = {"Alta": "var(--ok)", "Média": "var(--warn)", "Baixa": "var(--err)"}[p["confianca"]]
        rows += (
            f'<tr><td><strong>{esc(p["nome"])}</strong><br>'
            f'<span style="color:var(--t3);font-size:.72rem;">{esc(p["codigo"])}</span></td>'
            f'<td>{qtd_br(p["estoque_atual"])} {p["unidade"]}</td>'
            f'<td>{qtd_br(p["previsao_30d"]) if p["previsao_30d"] is not None else "—"}</td>'
            f'<td>{qtd_br(p["ponto_pedido"]) if p["ponto_pedido"] is not None else "—"}</td>'
            f'<td style="color:var(--err);font-weight:700;">{_fmt_mes(p["data_pedido"])}</td>'
            f'<td>{_fmt_mes(p["data_ruptura"])}</td>'
            f'<td><span style="color:{cor};font-weight:700;">{p["confianca"]}</span></td></tr>'
        )
    st.markdown(
        f'<table class="tbl"><thead><tr><th>Produto</th><th>Estoque atual</th>'
        f'<th>Previsão 30d</th><th>Ponto de pedido ideal</th><th>Pedido necessário em</th>'
        f'<th>Ruptura prevista</th><th>Confiança</th></tr></thead><tbody>{rows}</tbody></table>',
        unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    opcoes = {p["nome"]: p for p in produtos if p["forecast"]}
    if opcoes:
        st.markdown('<div class="card" style="margin-top:1rem;">'
                     '<div class="card-h">Simulação de estoque — 12 meses</div>', unsafe_allow_html=True)
        sel = st.selectbox("Produto", list(opcoes.keys()), key="prev_sel_prod")
        _grafico_produto(opcoes[sel])
        st.markdown("</div>", unsafe_allow_html=True)

def _grafico_produto(p):
    hist_x = list(p["serie_mensal"].keys())
    hist_y = list(p["serie_mensal"].values())
    fc_x = [f'{f["ano"]}-{f["mes"]:02d}' for f in p["forecast"]]
    fc_y = [f["valor"] for f in p["forecast"]]
    traj_y = [t["saldo"] for t in p["trajetoria"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=hist_x, y=hist_y, name="Consumo histórico", marker_color="rgba(120,120,120,.5)"))
    fig.add_trace(go.Bar(x=fc_x, y=fc_y, name="Consumo previsto", marker_color="rgba(204,0,0,.55)"))
    fig.add_trace(go.Scatter(x=fc_x, y=traj_y, name="Estoque projetado", mode="lines+markers",
                              line=dict(color="#CC0000", width=2), yaxis="y2"))
    fig.add_trace(go.Scatter(x=fc_x, y=[p["ponto_pedido"]] * len(fc_x), name="Ponto de pedido ideal",
                              mode="lines", line=dict(color="#B45309", width=1.5, dash="dash"), yaxis="y2"))
    if p["data_pedido"]:
        rotulo = f'{p["data_pedido"][0]}-{p["data_pedido"][1]:02d}'
        fig.add_vline(x=rotulo, line_width=1, line_dash="dot", line_color="#B45309")
        fig.add_annotation(x=rotulo, y=1, yref="paper", showarrow=False,
                            text=f"Pedido até {_fmt_mes(p['data_pedido'])}", font=dict(size=10, color="#B45309"))
    fig.update_layout(**_PL, height=320, barmode="overlay", legend=dict(bgcolor="rgba(0,0,0,0)"),
                       yaxis=dict(title=f'Consumo ({p["unidade"]})', gridcolor="rgba(0,0,0,.05)"),
                       yaxis2=dict(title="Estoque projetado", overlaying="y", side="right", gridcolor="rgba(0,0,0,0)"))
    st.plotly_chart(fig, use_container_width=True)

def _tab_setor(setores):
    st.markdown('<div class="card"><div class="card-h">Previsão por setor</div>', unsafe_allow_html=True)
    if not setores:
        st.info("Sem dados de consumo por setor no período.")
    else:
        rows = "".join(
            f'<tr><td><strong>{esc(s["setor"])}</strong></td>'
            f'<td>{qtd_br(s["consumo_medio_mensal"])}</td>'
            f'<td>{qtd_br(s["previsao_30d"])}</td>'
            f'<td>{qtd_br(s["previsao_12m"])}</td></tr>'
            for s in setores)
        st.markdown(
            f'<table class="tbl"><thead><tr><th>Setor</th><th>Consumo médio/mês</th>'
            f'<th>Previsão 30d</th><th>Previsão 12 meses</th></tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Exportação (recalculada a cada execução — sempre reflete o histórico atual) ──
def _autoajustar_colunas(ws, df):
    for i, col in enumerate(df.columns):
        largura = max((df[col].astype(str).map(len).max() if not df.empty else 0), len(col)) + 2
        ws.column_dimensions[chr(65 + i)].width = largura

def _planilha_setor(setores):
    df = pd.DataFrame([{
        "Setor": s["setor"],
        "Consumo médio mensal": round(s["consumo_medio_mensal"], 2),
        "Previsão 30 dias": round(s["previsao_30d"], 2),
        "Previsão 12 meses (com sazonalidade BF)": round(s["previsao_12m"], 2),
    } for s in setores])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Previsão por Setor")
        _autoajustar_colunas(w.sheets["Previsão por Setor"], df)
    buf.seek(0)
    return buf.getvalue()

def _planilha_produto(produtos):
    df = pd.DataFrame([{
        "Código": p["codigo"], "Produto": p["nome"],
        "Estoque atual": round(p["estoque_atual"], 2), "Unidade": p["unidade"],
        "Consumo diário médio": round(p["consumo_diario"], 3),
        "Previsão 30 dias": round(p["previsao_30d"], 2) if p["previsao_30d"] is not None else None,
        "Ponto de pedido ideal": round(p["ponto_pedido"], 2) if p["ponto_pedido"] is not None else None,
        "Pedido necessário em": _fmt_mes(p["data_pedido"]),
        "Ruptura prevista em": _fmt_mes(p["data_ruptura"]),
        "Confiança da previsão": p["confianca"],
    } for p in produtos])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Previsão por SKU")
        _autoajustar_colunas(w.sheets["Previsão por SKU"], df)
    buf.seek(0)
    return buf.getvalue()

def _tab_exportar(produtos, setores):
    st.markdown('<div class="card"><div class="card-h">Exportar relatórios</div>', unsafe_allow_html=True)
    st.caption("Os relatórios são recalculados com os dados mais recentes no momento do download.")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 Baixar previsão por setor (.xlsx)",
            data=_planilha_setor(setores),
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
