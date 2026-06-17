"""pages/dashboard.py"""
import io, datetime
import plotly.graph_objects as go
import streamlit as st
from utils.database import stats_dashboard, consumo_por_periodo, listar_setores, historico_consumo_mensal, contar_solicitacoes_compra_pendentes
from utils.ui import badge, kpi_html, status_estoque
from utils.fmt import qtd_br, datahora_br, data_br
from utils.sanitize import esc, esc_trunc

_PL=dict(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
         font=dict(family="Plus Jakarta Sans",size=11),margin=dict(l=0,r=0,t=20,b=0),
         showlegend=True,legend=dict(bgcolor="rgba(0,0,0,0)",font=dict(size=10)))

def tela_dashboard():
    st.markdown('<div class="pg">',unsafe_allow_html=True)
    st.markdown('<div class="pg-title">Dashboard</div><div class="pg-sub">Visão geral em tempo real</div>',unsafe_allow_html=True)
    s=stats_dashboard()
    st.markdown(f'<div class="kpis">{kpi_html("Produtos",s["total_produtos"],"ativos","var(--red)")}{kpi_html("OK",s["ok"],"acima do mínimo","var(--ok)")}{kpi_html("Baixo",s["baixos"],"abaixo do mínimo","var(--warn)")}{kpi_html("Crítico",s["criticos"],"sem estoque","var(--err)")}{kpi_html("Solicitações",s["pend_solicitacoes"],"pendentes","#7C3AED")}{kpi_html("Notas NF",s["pend_notas"],"aguardando envio","var(--info)")}{kpi_html("Parados 30d",s["parados"],"sem movimentação","var(--t3)")}{kpi_html("Movimentações",s["total_movimentacoes"],"total","var(--t2)")}</div>',unsafe_allow_html=True)
    # Alert for pending purchase requests
    sc_pend = contar_solicitacoes_compra_pendentes()
    if sc_pend:
        st.warning(f"🛒 **{sc_pend} solicitação(ões) de compra** aguardando aprovação.")
    if s["criticos"]: st.error(f"🔴 **{s['criticos']} produto(s) com estoque zerado.**")
    if s["pend_solicitacoes"]: st.warning(f"🟡 **{s['pend_solicitacoes']} solicitação(ões)** aguardando aprovação.")
    if s["pend_notas"]: st.info(f"🔵 **{s['pend_notas']} nota(s)** pendentes de envio ao financeiro.")
    c1,c2=st.columns([1.4,1])
    with c1: _consumo_geral(s["consumo_setor"])
    with c2: _pie(s)
    c3,c4=st.columns(2)
    with c3: _recentes(s["recentes"])
    with c4: _atencao(s["produtos"])
    _secao_consumo_periodo()
    st.markdown("</div>",unsafe_allow_html=True)

def _consumo_geral(consumo):
    st.markdown('<div class="card"><div class="card-h">📊 Consumo por Setor</div>',unsafe_allow_html=True)
    if not consumo:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;text-align:center;padding:1rem">Sem dados.</p>',unsafe_allow_html=True)
    else:
        cores=["#CC0000","#E53535","#FF6666","#FF9999","#8B0000","#B22222","#DC143C","#F08080"]
        fig=go.Figure(go.Bar(x=list(consumo.keys()),y=list(consumo.values()),marker=dict(color=cores[:len(consumo)],line=dict(width=0)),hovertemplate="<b>%{x}</b><br>%{y:.0f}<extra></extra>"))
        fig.update_layout(**_PL,height=220,xaxis=dict(gridcolor="rgba(0,0,0,.05)",tickfont=dict(size=10)),yaxis=dict(gridcolor="rgba(0,0,0,.05)"))
        st.plotly_chart(fig,use_container_width=True)
    st.markdown("</div>",unsafe_allow_html=True)

def _pie(s):
    st.markdown('<div class="card"><div class="card-h">📦 Status Inventário</div>',unsafe_allow_html=True)
    fig=go.Figure(go.Pie(labels=["OK","Baixo","Crítico"],values=[s["ok"],s["baixos"],s["criticos"]],hole=0.65,marker=dict(colors=["#16A34A","#D97706","#DC2626"],line=dict(color="rgba(255,255,255,.15)",width=2)),hovertemplate="<b>%{label}</b>: %{value}<extra></extra>"))
    fig.update_layout(**_PL,height=220,annotations=[dict(text=f"<b>{s['total_produtos']}</b>",x=.5,y=.5,font_size=22,showarrow=False)])
    st.plotly_chart(fig,use_container_width=True)
    st.markdown("</div>",unsafe_allow_html=True)

def _recentes(r):
    st.markdown('<div class="card"><div class="card-h">🔄 Movimentações Recentes</div>',unsafe_allow_html=True)
    if not r: st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma.</p>',unsafe_allow_html=True)
    else:
        rows=""
        for m in r:
            prod=(m.get("produtos") or {}).get("nome","—"); cor="var(--ok)" if m["tipo"]=="entrada" else "var(--err)"; sinal="+" if m["tipo"]=="entrada" else "-"
            rows+=f'<tr><td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td><td>{prod[:26]}{"…" if len(prod)>26 else ""}</td><td style="color:{cor};font-weight:700;font-family:var(--mono);">{sinal}{qtd_br(m["quantidade_informada"])} {m["unidade_informada"]}</td></tr>'
        st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Qtd</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
    st.markdown("</div>",unsafe_allow_html=True)

def _atencao(produtos):
    st.markdown('<div class="card"><div class="card-h">🚨 Produtos em Atenção</div>',unsafe_allow_html=True)
    at=[(p,*status_estoque(float(p["quantidade_total_secundaria"]),float(p["estoque_minimo_primario"]),float(p["fator_conversao"]))) for p in produtos]
    at=[x for x in at if x[2]!="ok"]
    if not at: st.markdown('<p style="color:var(--ok);font-size:.82rem;">✅ Todos OK.</p>',unsafe_allow_html=True)
    else:
        rows=""
        for p,txt,cls in sorted(at,key=lambda x:float(x[0]["quantidade_total_secundaria"]))[:8]:
            rows+=f'<tr><td>{p["nome"][:26]}{"…" if len(p["nome"])>26 else ""}</td><td class="mono">{qtd_br(p["quantidade_total_secundaria"])} {p["unidade_secundaria"]}</td><td>{badge(txt,cls)}</td></tr>'
        st.markdown(f'<table class="tbl"><thead><tr><th>Produto</th><th>Estoque</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
    st.markdown("</div>",unsafe_allow_html=True)

def _secao_consumo_periodo():
    st.markdown('<div class="card"><div class="card-h">📈 Análise de Consumo por Período</div>',unsafe_allow_html=True)
    hoje=datetime.date.today(); ini_pad=hoje.replace(day=1)
    setores=listar_setores(); set_nomes=["Todos os setores"]+[s["nome"] for s in setores]
    c1,c2,c3,c4=st.columns([2,2,2,1])
    with c1: data_ini=st.date_input("Início",value=ini_pad,key="dash_ini")
    with c2: data_fim=st.date_input("Fim",value=hoje,key="dash_fim")
    with c3: setor_sel=st.selectbox("Setor",set_nomes,key="dash_setor")
    with c4:
        st.markdown("<div style='height:27px'></div>",unsafe_allow_html=True)
        buscar=st.button("Filtrar",type="primary",use_container_width=True,key="dash_filtrar")
    if data_ini>data_fim: st.warning("Data início deve ser anterior à fim."); st.markdown("</div>",unsafe_allow_html=True); return
    if buscar or "dash_resultado" not in st.session_state:
        setor_f=None if setor_sel=="Todos os setores" else setor_sel
        dados=consumo_por_periodo(data_ini.strftime("%Y-%m-%d"),data_fim.strftime("%Y-%m-%d"),setor_f)
        st.session_state["dash_resultado"]=dados; st.session_state["dash_filtros"]={"ini":data_ini,"fim":data_fim,"setor":setor_sel}
    dados=st.session_state.get("dash_resultado",[]); filtros=st.session_state.get("dash_filtros",{})
    if not dados: st.markdown('<p style="color:var(--t3);font-size:.82rem;text-align:center;padding:1.5rem 0;">Nenhuma movimentação no período.</p>',unsafe_allow_html=True); st.markdown("</div>",unsafe_allow_html=True); return
    consumo={}; detalhes=[]
    for row in dados:
        prod_info=row.get("produto") or {}; nome=prod_info.get("nome","—"); un=prod_info.get("unidade_secundaria","UN")
        qtd=float(row.get("quantidade_convertida") or 0); tipo=row.get("tipo","")
        tipo_ent=row.get("tipo_entrada",""); tipo_sai=row.get("tipo_saida","")
        exe=(row.get("exe") or {}).get("nick","—"); setor=row.get("setor_solicitante","—") or "—"
        if tipo=="saida": consumo[f"{nome} ({un})"]=consumo.get(f"{nome} ({un})",0)+qtd
        if tipo=="entrada": tipo_mov=f"📥 Entrada — {tipo_ent}" if tipo_ent else "📥 Entrada"
        elif tipo=="saida": tipo_mov=f"📤 Saída — {tipo_sai}" if tipo_sai else "📤 Saída"
        else: tipo_mov=tipo
        detalhes.append({"Data":datahora_br(row.get("criado_em","")),"Tipo":tipo_mov,"Produto":nome,"Qtd":qtd,"Sinal":"-" if tipo=="saida" else "+","Unidade":un,"Setor":setor,"Executor":exe})
    if consumo:
        nomes=list(consumo.keys()); valores=list(consumo.values())
        cores=["#CC0000","#E53535","#FF6666","#FF9999","#8B0000","#B22222","#DC143C","#F08080","#CD5C5C","#FA8072"]
        titulo=f"{data_br(filtros.get('ini'))} a {data_br(filtros.get('fim'))}" + (f" — {filtros.get('setor')}" if filtros.get("setor")!="Todos os setores" else "")
        fig=go.Figure(go.Bar(x=nomes,y=valores,marker=dict(color=cores[:len(nomes)] if len(nomes)<=len(cores) else ["#CC0000"]*len(nomes),line=dict(width=0)),text=[qtd_br(v) for v in valores],textposition="outside",hovertemplate="<b>%{x}</b><br>Consumo: %{y:.2f}<extra></extra>"))
        fig.update_layout(**_PL,height=max(300,80+40*len(nomes)),title=dict(text=f"Consumo saídas: {titulo}",font=dict(size=12)),xaxis=dict(gridcolor="rgba(0,0,0,.05)",tickfont=dict(size=10),tickangle=-30 if len(nomes)>6 else 0),yaxis=dict(gridcolor="rgba(0,0,0,.05)"),bargap=0.35)
        st.plotly_chart(fig,use_container_width=True)
    else: st.info("Nenhuma saída no período.")
    with st.expander("📋 Tabela detalhada (entradas e saídas)"):
        rows=""
        for d in detalhes:
            cor="var(--err)" if d["Sinal"]=="-" else "var(--ok)"
            rows+=f'<tr><td style="color:var(--t3);font-size:.73rem;">{d["Data"]}</td><td style="font-size:.78rem;">{d["Tipo"]}</td><td><strong>{d["Produto"]}</strong></td><td style="color:{cor};font-weight:700;font-family:var(--mono);">{d["Sinal"]}{qtd_br(d["Qtd"])} {d["Unidade"]}</td><td>{d["Setor"]}</td><td style="color:var(--t3);">{d["Executor"]}</td></tr>'
        st.markdown(f'<table class="tbl"><thead><tr><th>Data/Hora</th><th>Tipo</th><th>Produto</th><th>Quantidade</th><th>Setor</th><th>Responsável</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
    st.markdown("**⬇️ Exportar**"); _excel_download(detalhes,f"{data_br(filtros.get('ini'))}_{data_br(filtros.get('fim'))}")
    st.markdown("</div>",unsafe_allow_html=True)

def _excel_download(detalhes,titulo):
    try:
        import openpyxl; wb=openpyxl.Workbook(); ws=wb.active; ws.title="Consumo"
        ws.append(["Data","Tipo","Produto","Quantidade","Unidade","Setor","Responsável"])
        for d in detalhes: ws.append([d["Data"],d["Tipo"],d["Produto"],f"{d['Sinal']}{d['Qtd']}",d["Unidade"],d["Setor"],d["Executor"]])
        buf=io.BytesIO(); wb.save(buf); buf.seek(0)
        st.download_button("📥 Baixar Excel",data=buf.getvalue(),file_name=f"consumo_{titulo[:25].replace(' ','_').replace('/','_')}.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except ImportError:
        import csv,io as sio; buf=sio.StringIO(); writer=csv.writer(buf)
        writer.writerow(["Data","Tipo","Produto","Quantidade","Unidade","Setor","Responsável"])
        for d in detalhes: writer.writerow([d["Data"],d["Tipo"],d["Produto"],f"{d['Sinal']}{d['Qtd']}",d["Unidade"],d["Setor"],d["Executor"]])
        st.download_button("📥 Baixar CSV",data=buf.getvalue().encode("utf-8-sig"),file_name=f"consumo_{titulo[:25]}.csv",mime="text/csv")


# ══════════════════════════════════════════════════════════════════
# PREVISÃO DE DEMANDA — Crowdsourcing histórico
# ══════════════════════════════════════════════════════════════════

def _secao_previsao_demanda():
    """Analisa histórico de consumo e projeta demanda mensal para os próximos 12 meses."""
    st.markdown('<div class="card"><div class="card-h">🔮 Previsão de Demanda — Próximos 12 Meses</div>',
                unsafe_allow_html=True)
    st.caption("Projeção baseada na média móvel do consumo histórico registrado no sistema.")

    hoje = datetime.date.today()
    ini_pad = (hoje.replace(day=1) - datetime.timedelta(days=365))

    c1, c2, c3 = st.columns([2,2,1])
    with c1: d_ini = st.date_input("Histórico de", value=ini_pad, key="prev_ini")
    with c2: d_fim = st.date_input("até", value=hoje, key="prev_fim")
    with c3:
        st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
        calcular = st.button("📊 Calcular", type="primary", use_container_width=True, key="btn_prev")

    if not calcular and "prev_resultado" not in st.session_state:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Clique em Calcular para gerar as previsões.</p>',
                    unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if calcular:
        dados_hist = historico_consumo_mensal(meses=24)
        st.session_state["prev_resultado"] = dados_hist
        st.session_state["prev_datas"] = (d_ini, d_fim)

    dados_hist = st.session_state.get("prev_resultado", [])
    d_ini, d_fim = st.session_state.get("prev_datas", (ini_pad, hoje))

    if not dados_hist:
        st.info("Sem histórico de consumo para projeção. Registre saídas primeiro.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Filtra pelo período selecionado
    from datetime import datetime as _dt
    dados_filt = []
    for row in dados_hist:
        try:
            dt_str = row.get("criado_em","")[:10]
            dt = _dt.strptime(dt_str, "%Y-%m-%d").date()
            if d_ini <= dt <= d_fim:
                dados_filt.append(row)
        except: continue

    if not dados_filt:
        st.info("Sem dados no período selecionado.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Agrupa consumo por produto e por mês
    from collections import defaultdict
    consumo_prod: dict = defaultdict(lambda: defaultdict(float))
    prod_info: dict = {}

    for row in dados_filt:
        prod_obj = row.get("produto") or {}
        pid      = row.get("produto_id","")
        nome     = prod_obj.get("nome","—")
        un       = prod_obj.get("unidade_secundaria","UN")
        mes      = row.get("criado_em","")[:7]  # YYYY-MM
        qtd      = float(row.get("quantidade_convertida") or 0)
        consumo_prod[pid][mes] += qtd
        prod_info[pid] = {"nome": nome, "un": un}

    # Calcula média mensal e projeta 12 meses
    previsoes = []
    for pid, meses_consumo in consumo_prod.items():
        if not meses_consumo: continue
        total = sum(meses_consumo.values())
        n_meses = len(meses_consumo)
        media_mensal = total / n_meses if n_meses > 0 else 0
        info = prod_info.get(pid, {})

        # Projeta próximos 12 meses com média
        import calendar
        proj = {}
        hoje_d = datetime.date.today()
        for i in range(1, 13):
            m_delta = hoje_d.month + i
            ano = hoje_d.year + (m_delta - 1) // 12
            mes_num = ((m_delta - 1) % 12) + 1
            label = f"{mes_num:02d}/{ano}"
            proj[label] = round(media_mensal, 2)

        previsoes.append({
            "pid":          pid,
            "nome":         info.get("nome","—"),
            "un":           info.get("un","UN"),
            "media_mensal": round(media_mensal, 2),
            "total_hist":   round(total, 2),
            "n_meses":      n_meses,
            "projecao":     proj,
        })

    # Ordena por maior consumo médio
    previsoes.sort(key=lambda x: x["media_mensal"], reverse=True)

    # Gráfico dos top 8 produtos
    top = previsoes[:8]
    if top:
        fig = go.Figure()
        cores = ["#CC0000","#E53535","#FF6666","#8B0000","#B22222","#DC143C","#F08080","#CD5C5C"]
        for i, p in enumerate(top):
            meses_proj = list(p["projecao"].keys())
            vals_proj  = list(p["projecao"].values())
            fig.add_trace(go.Bar(
                name=p["nome"][:25],
                x=meses_proj,
                y=vals_proj,
                marker_color=cores[i % len(cores)],
                hovertemplate=f"<b>{p['nome']}</b><br>%{{x}}: %{{y:.1f}} {p['un']}<extra></extra>",
            ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Plus Jakarta Sans", size=11),
            margin=dict(l=0,r=0,t=30,b=0),
            height=320, barmode="group", bargap=0.2, bargroupgap=0.05,
            xaxis=dict(gridcolor="rgba(0,0,0,.05)", title="Mês"),
            yaxis=dict(gridcolor="rgba(0,0,0,.05)", title="Quantidade projetada"),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=9)),
            title=dict(text=f"Projeção mensal — média dos últimos {dados_filt and len(set(r['criado_em'][:7] for r in dados_filt))} meses", font=dict(size=11)),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Tabela resumo
    with st.expander("📋 Tabela de previsões por produto"):
        rows = ""
        for p in previsoes:
            anual = p["media_mensal"] * 12
            rows += (f'<tr>'
                     f'<td><strong>{esc(p["nome"])}</strong></td>'
                     f'<td class="mono">{qtd_br(p["media_mensal"])} {esc(p["un"])}/mês</td>'
                     f'<td class="mono">{qtd_br(anual)} {esc(p["un"])}/ano</td>'
                     f'<td style="color:var(--t3);">{p["n_meses"]} mês(es)</td>'
                     f'</tr>')
        st.markdown(
            f'<table class="tbl"><thead><tr>'
            f'<th>Produto</th><th>Média/mês</th><th>Projeção Anual</th><th>Base histórica</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
