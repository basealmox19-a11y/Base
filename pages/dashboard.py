"""pages/dashboard.py — Dashboard com consumo por período e export Excel"""
import io
import datetime
import plotly.graph_objects as go
import streamlit as st
from utils.database import stats_dashboard, consumo_por_periodo, listar_setores, listar_movimentacoes
from utils.ui import badge, kpi_html, status_estoque
from utils.fmt import qtd_br, datahora_br, data_br

_PL = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Plus Jakarta Sans", size=11),
    margin=dict(l=0, r=0, t=20, b=0),
    showlegend=True,
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
)


def tela_dashboard():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown(
        '<div class="pg-title">Dashboard</div>'
        '<div class="pg-sub">Visão geral em tempo real</div>',
        unsafe_allow_html=True,
    )

    s = stats_dashboard()

    # ── KPIs ──────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="kpis">
        {kpi_html("Produtos",       s["total_produtos"],       "ativos",            "var(--red)")}
        {kpi_html("OK",             s["ok"],                   "acima do mínimo",   "var(--ok)")}
        {kpi_html("Baixo",          s["baixos"],               "abaixo do mínimo",  "var(--warn)")}
        {kpi_html("Crítico",        s["criticos"],             "sem estoque",       "var(--err)")}
        {kpi_html("Solicitações",   s["pend_solicitacoes"],    "pendentes",         "#7C3AED")}
        {kpi_html("Notas NF",       s["pend_notas"],           "aguardando envio",  "var(--info)")}
        {kpi_html("Parados 30d",    s["parados"],              "sem movimentação",  "var(--t3)")}
        {kpi_html("Movimentações",  s["total_movimentacoes"],  "total",             "var(--t2)")}
    </div>
    """, unsafe_allow_html=True)

    # ── Alertas ───────────────────────────────────────────────────
    if s["criticos"] or s["baixos"]:
        total_atencao = s["criticos"] + s["baixos"]
        partes = []
        if s["criticos"]: partes.append(f"<strong>{s['criticos']} zerado(s)</strong>")
        if s["baixos"]:   partes.append(f"<strong>{s['baixos']} abaixo do mínimo</strong>")
        st.markdown(
            f'<div style="background:rgba(220,38,38,.1);border:1.5px solid var(--err);border-radius:8px;'
            f'padding:.85rem 1.1rem;margin:.5rem 0 1rem;display:flex;align-items:center;gap:.75rem;">'
            f'<span style="font-size:1.4rem;">⚠️</span>'
            f'<div><div style="font-weight:700;color:var(--err);font-size:.92rem;">'
            f'{total_atencao} produto(s) precisam de atenção</div>'
            f'<div style="font-size:.8rem;color:var(--t3);margin-top:.15rem;">{" · ".join(partes)}'
            f' — verifique a lista abaixo.</div></div></div>',
            unsafe_allow_html=True,
        )
    if s["pend_solicitacoes"]:
        st.warning(f"🟡 **{s['pend_solicitacoes']} solicitação(ões)** aguardando aprovação.")
    if s["pend_notas"]:
        st.info(f"🔵 **{s['pend_notas']} nota(s)** pendentes de envio ao financeiro.")

    # ── Gráficos gerais ───────────────────────────────────────────
    c1, c2 = st.columns([1.4, 1])
    with c1: _consumo_geral(s["consumo_setor"])
    with c2: _pie(s)

    c3, c4 = st.columns(2)
    with c3: _recentes(s["recentes"])
    with c4: _atencao(s["produtos"])

    # ── Análise de consumo por período ───────────────────────────
    _secao_consumo_periodo()

    st.markdown("</div>", unsafe_allow_html=True)


# ── Gráfico de consumo geral ────────────────────────────────────

def _consumo_geral(consumo):
    st.markdown(
        '<div class="card"><div class="card-h">📊 Consumo por Setor (total)</div>',
        unsafe_allow_html=True,
    )
    if not consumo:
        st.markdown(
            '<p style="color:var(--t3);font-size:.82rem;text-align:center;padding:1rem">Sem dados.</p>',
            unsafe_allow_html=True,
        )
    else:
        cores = ["#CC0000","#E53535","#FF6666","#FF9999","#8B0000","#B22222","#DC143C","#F08080"]
        fig = go.Figure(go.Bar(
            x=list(consumo.keys()), y=list(consumo.values()),
            marker=dict(color=cores[:len(consumo)], line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>%{y:.0f}<extra></extra>",
        ))
        fig.update_layout(
            **_PL, height=220,
            xaxis=dict(gridcolor="rgba(0,0,0,.05)", tickfont=dict(size=10)),
            yaxis=dict(gridcolor="rgba(0,0,0,.05)"),
        )
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _pie(s):
    st.markdown(
        '<div class="card"><div class="card-h">📦 Status Inventário</div>',
        unsafe_allow_html=True,
    )
    fig = go.Figure(go.Pie(
        labels=["OK","Baixo","Crítico"],
        values=[s["ok"], s["baixos"], s["criticos"]],
        hole=0.65,
        marker=dict(
            colors=["#16A34A","#D97706","#DC2626"],
            line=dict(color="rgba(255,255,255,.15)", width=2),
        ),
        hovertemplate="<b>%{label}</b>: %{value}<extra></extra>",
    ))
    fig.update_layout(
        **_PL, height=220,
        annotations=[dict(
            text=f"<b>{s['total_produtos']}</b>",
            x=.5, y=.5, font_size=22, showarrow=False,
        )],
    )
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _recentes(r):
    st.markdown(
        '<div class="card"><div class="card-h">🔄 Movimentações Recentes</div>',
        unsafe_allow_html=True,
    )
    hoje      = datetime.date.today()
    ini_pad   = hoje - datetime.timedelta(days=30)
    ca, cb    = st.columns(2)
    with ca: d_ini = st.date_input("De",  value=ini_pad, key="rec_ini")
    with cb: d_fim = st.date_input("Até", value=hoje,    key="rec_fim")

    # Busca movimentações; tenta filtrar por data se o banco suportar, senão filtra em Python
    try:
        movs = listar_movimentacoes(
            limite=500,
            data_inicio=d_ini.strftime("%Y-%m-%d"),
            data_fim=d_fim.strftime("%Y-%m-%d"),
        )
    except TypeError:
        # fallback: função não aceita parâmetros de data — filtra em Python
        movs = listar_movimentacoes(limite=500)
        movs = [
            m for m in movs
            if d_ini.strftime("%Y-%m-%d") <= (m.get("criado_em") or "")[:10] <= d_fim.strftime("%Y-%m-%d")
        ]

    if d_ini > d_fim:
        st.warning("Data início deve ser anterior à data fim.")
    elif not movs:
        st.markdown(
            '<p style="color:var(--t3);font-size:.82rem;">Nenhuma movimentação no período.</p>',
            unsafe_allow_html=True,
        )
    else:
        rows = ""
        for m in movs:
            prod  = (m.get("produtos") or {}).get("nome","—")
            cor   = "var(--ok)" if m["tipo"] == "entrada" else "var(--err)"
            sinal = "+" if m["tipo"] == "entrada" else "-"
            tipo_lbl = "📥" if m["tipo"] == "entrada" else "📤"
            rows += (
                f'<tr>'
                f'<td style="color:var(--t3);font-size:.73rem;white-space:nowrap;">{datahora_br(m["criado_em"])}</td>'
                f'<td>{prod[:28]}{"…" if len(prod)>28 else ""}</td>'
                f'<td style="color:{cor};font-weight:700;font-family:var(--mono);">'
                f'{tipo_lbl} {sinal}{qtd_br(m["quantidade_informada"])} {m["unidade_informada"]}</td>'
                f'</tr>'
            )
        # Altura fixa para 10 linhas (~38px cada) — rola se houver mais
        st.markdown(
            f'<div style="max-height:390px;overflow-y:auto;border-radius:5px;">'
            f'<table class="tbl"><thead><tr>'
            f'<th>Data/Hora</th><th>Produto</th><th>Movimentação</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>'
            f'<div style="font-size:.72rem;color:var(--t3);margin-top:.4rem;">'
            f'{len(movs)} registro(s) no período</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _atencao(produtos):
    at = [
        (p, *status_estoque(
            float(p["quantidade_total_secundaria"]),
            float(p["estoque_minimo_primario"]),
            float(p["fator_conversao"]),
        ))
        for p in produtos
    ]
    # Exibe APENAS itens fora do normal — ao voltar ao estoque OK saem automaticamente
    at = [x for x in at if x[2] != "ok"]
    at_sorted = sorted(at, key=lambda x: float(x[0]["quantidade_total_secundaria"]))

    criticos_n = sum(1 for _, _, cls in at_sorted if cls == "err")
    baixos_n   = sum(1 for _, _, cls in at_sorted if cls == "warn")

    st.markdown(
        '<div class="card"><div class="card-h">🚨 Produtos em Atenção</div>',
        unsafe_allow_html=True,
    )

    if not at_sorted:
        st.markdown(
            '<p style="color:var(--ok);font-size:.87rem;padding:.3rem 0;">✅ Todos os produtos estão com estoque OK.</p>',
            unsafe_allow_html=True,
        )
    else:
        # Mini-resumo dentro do card
        resumo_partes = []
        if criticos_n: resumo_partes.append(f'<span style="color:var(--err);font-weight:700;">{criticos_n} zerado(s)</span>')
        if baixos_n:   resumo_partes.append(f'<span style="color:var(--warn);font-weight:700;">{baixos_n} baixo(s)</span>')
        st.markdown(
            f'<div style="font-size:.78rem;color:var(--t3);margin-bottom:.5rem;">'
            f'{" · ".join(resumo_partes)} — role para ver todos</div>',
            unsafe_allow_html=True,
        )
        rows = ""
        for p, txt, cls in at_sorted:
            nome = p["nome"]
            est  = float(p["quantidade_total_secundaria"])
            un   = p.get("unidade_secundaria","")
            rows += (
                f'<tr>'
                f'<td>{nome[:28]}{"…" if len(nome)>28 else ""}</td>'
                f'<td class="mono">{qtd_br(est)} {un}</td>'
                f'<td>{badge(txt,cls)}</td>'
                f'</tr>'
            )
        # max-height para 10 linhas (~38px) com scroll
        st.markdown(
            f'<div style="max-height:390px;overflow-y:auto;border-radius:5px;">'
            f'<table class="tbl"><thead><tr>'
            f'<th>Produto</th><th>Estoque</th><th>Status</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>'
            f'<div style="font-size:.72rem;color:var(--t3);margin-top:.4rem;">'
            f'{len(at_sorted)} produto(s) em atenção</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# ANÁLISE DE CONSUMO POR PERÍODO
# ══════════════════════════════════════════════════════════════════

def _secao_consumo_periodo():
    st.markdown(
        '<div class="card"><div class="card-h">📈 Análise de Consumo por Período</div>',
        unsafe_allow_html=True,
    )

    # ── Filtros ───────────────────────────────────────────────────
    hoje       = datetime.date.today()
    ini_padrao = hoje.replace(day=1)          # primeiro dia do mês atual

    setores    = listar_setores()
    set_nomes  = ["Todos os setores"] + [s["nome"] for s in setores]

    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
    with col1:
        data_ini = st.date_input("Data início", value=ini_padrao, key="dash_ini")
    with col2:
        data_fim = st.date_input("Data fim",    value=hoje,       key="dash_fim")
    with col3:
        setor_sel = st.selectbox("Setor", set_nomes, key="dash_setor")
    with col4:
        st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
        buscar = st.button("Filtrar", type="primary", use_container_width=True, key="dash_filtrar")

    if data_ini > data_fim:
        st.warning("Data início deve ser anterior à data fim.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Executa na primeira carga e ao clicar Filtrar
    if buscar or "dash_resultado" not in st.session_state:
        setor_filtro = None if setor_sel == "Todos os setores" else setor_sel
        dados = consumo_por_periodo(
            data_ini.strftime("%Y-%m-%d"),
            data_fim.strftime("%Y-%m-%d"),
            setor_filtro,
        )
        st.session_state["dash_resultado"] = dados
        st.session_state["dash_filtros"]   = {
            "ini":   data_ini,
            "fim":   data_fim,
            "setor": setor_sel,
        }

    dados   = st.session_state.get("dash_resultado", [])
    filtros = st.session_state.get("dash_filtros",   {})

    if not dados:
        st.markdown(
            '<p style="color:var(--t3);font-size:.82rem;text-align:center;padding:1.5rem 0;">'
            'Nenhuma saída encontrada no período selecionado.</p>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── Agrega por produto ────────────────────────────────────────
    agrupado: dict[str, float] = {}
    detalhes: list[dict]       = []

    for row in dados:
        prod_info = row.get("produto") or {}
        nome      = prod_info.get("nome","—")
        un        = prod_info.get("unidade_secundaria","UN")
        qtd       = float(row.get("quantidade_convertida") or 0)
        agrupado[f"{nome} ({un})"] = agrupado.get(f"{nome} ({un})", 0) + qtd
        detalhes.append({
            "Data":              datahora_br(row.get("criado_em","")),
            "Produto":           nome,
            "Qtd":               qtd,
            "Unidade":           un,
            "Setor":             row.get("setor_solicitante","—"),
        })

    # ── Gráfico de barras verticais ───────────────────────────────
    nomes  = list(agrupado.keys())
    valores= list(agrupado.values())
    cores  = ["#CC0000","#E53535","#FF6666","#FF9999","#8B0000",
              "#B22222","#DC143C","#F08080","#CD5C5C","#FA8072"]

    titulo_periodo = (
        f"{data_br(filtros.get('ini'))} a {data_br(filtros.get('fim'))}"
        + (f" — {filtros.get('setor')}" if filtros.get("setor") != "Todos os setores" else "")
    )

    fig = go.Figure(go.Bar(
        x=nomes, y=valores,
        marker=dict(
            color=cores[:len(nomes)] if len(nomes) <= len(cores)
                  else ["#CC0000"] * len(nomes),
            line=dict(width=0),
        ),
        text=[qtd_br(v) for v in valores],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Consumo: %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        **_PL,
        height=max(300, 80 + 40 * len(nomes)),
        title=dict(text=f"Consumo: {titulo_periodo}", font=dict(size=12)),
        xaxis=dict(
            gridcolor="rgba(0,0,0,.05)",
            tickfont=dict(size=10),
            tickangle=-30 if len(nomes) > 6 else 0,
        ),
        yaxis=dict(gridcolor="rgba(0,0,0,.05)"),
        bargap=0.35,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Tabela resumo ─────────────────────────────────────────────
    with st.expander("📋 Ver tabela detalhada"):
        rows = ""
        for d in detalhes:
            rows += (
                f'<tr>'
                f'<td style="color:var(--t3);font-size:.73rem;">{d["Data"]}</td>'
                f'<td><strong>{d["Produto"]}</strong></td>'
                f'<td style="font-weight:600;">{qtd_br(d["Qtd"])} {d["Unidade"]}</td>'
                f'<td>{d["Setor"]}</td>'
                f'</tr>'
            )
        st.markdown(
            f'<table class="tbl"><thead><tr>'
            f'<th>Data</th><th>Produto</th><th>Qtd</th><th>Setor</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True,
        )

    # ── Download Excel ────────────────────────────────────────────
    st.markdown("**⬇️ Exportar dados**", unsafe_allow_html=False)
    _excel_download(detalhes, titulo_periodo)

    st.markdown("</div>", unsafe_allow_html=True)


def _excel_download(detalhes: list, titulo: str):
    """Gera arquivo Excel sem formatação a partir dos dados filtrados."""
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Consumo"

        # Cabeçalho
        headers = ["Data", "Produto", "Quantidade", "Unidade", "Setor"]
        ws.append(headers)

        # Dados
        for d in detalhes:
            ws.append([
                d["Data"],
                d["Produto"],
                d["Qtd"],
                d["Unidade"],
                d["Setor"],
            ])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        nome_arq = f"consumo_{titulo[:30].replace(' ','_').replace('/','_')}.xlsx"
        st.download_button(
            label="📥 Baixar Excel",
            data=buf.getvalue(),
            file_name=nome_arq,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ImportError:
        # openpyxl não disponível — usa CSV como fallback
        import csv, io as sio
        buf = sio.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Data","Produto","Quantidade","Unidade","Setor"])
        for d in detalhes:
            writer.writerow([d["Data"], d["Produto"], d["Qtd"], d["Unidade"], d["Setor"]])
        nome_arq = f"consumo_{titulo[:30].replace(' ','_').replace('/','_')}.csv"
        st.download_button(
            label="📥 Baixar CSV",
            data=buf.getvalue().encode("utf-8-sig"),
            file_name=nome_arq,
            mime="text/csv",
        )
