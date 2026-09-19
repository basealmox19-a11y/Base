"""pages/estoque.py — Com histórico de movimentações por produto"""
import streamlit as st, datetime, io
import pandas as pd
import plotly.graph_objects as go
from utils.database import (listar_produtos, listar_categorias, atualizar_produto,
    registrar_movimentacao, listar_movimentacoes, historico_produto, listar_solicitacoes)
from utils.database import mesclar_classificacoes, definir_classificacao_produto  # classificação manual (produto_flags)
from utils.auth import sessao, is_admin, is_almoxarife
from utils.ui import badge, status_estoque
from utils.fmt import qtd_br, datahora_br
from utils.unidades import SIGLAS, OPCOES, sigla_para_opcao, opcao_para_sigla
from utils.sanitize import esc, esc_trunc

def _u(label,val="UN",key=None):
    idx=SIGLAS.index(val) if val in SIGLAS else 0
    kw={"key":key} if key else {}
    return opcao_para_sigla(st.selectbox(label,OPCOES,index=idx,**kw))

# ── Tokens de tipografia — harmoniza os tamanhos de fonte em toda a página de Estoque ──
FS_HEAD  = ".68rem"   # cabeçalhos de coluna/rótulos em uppercase
FS_BODY  = ".84rem"   # texto principal das células (nome, valores de destaque)
FS_SUB   = ".71rem"   # texto secundário/apoio (conversões, tags, datas)
FS_MICRO = ".66rem"   # rótulos muito pequenos (hints, legendas)
FS_HERO  = "1.35rem"  # números grandes em destaque (ex.: estoque atual no ajuste)

def _moeda(v):
    """Formata um valor numérico como moeda brasileira: R$ 1.234,56."""
    v=float(v or 0)
    s=f"{v:,.2f}".replace(",","X").replace(".",",").replace("X",".")
    return f"R$ {s}"

# Rótulos de status do sistema: apenas 3 existem — "OK", "Estoque Baixo" e "Estoque Zerado".
# status_estoque() (utils/ui) ainda retorna os nomes antigos ("Baixo"/"Crítico") por baixo dos panos;
# aqui traduzimos para exibição, sem tocar na classe css (cls) que ele também retorna.
_ROTULOS_STATUS = {"Baixo": "Estoque Baixo", "Crítico": "Estoque Zerado"}
def _rotulo_status(txt):
    return _ROTULOS_STATUS.get(txt, txt)

_PL=dict(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
         font=dict(family="Plus Jakarta Sans",size=11),margin=dict(l=0,r=0,t=20,b=0))

def _planilha_estoque(prods):
    """Gera um .xlsx (bytes) com todo o inventário, independente de filtros aplicados na tela."""
    linhas=[]
    for p in prods:
        est=float(p["quantidade_total_secundaria"]); minp=float(p["estoque_minimo_primario"]); fat=float(p["fator_conversao"])
        estp=est/fat if fat else 0
        status,_=status_estoque(est,minp,fat); status=_rotulo_status(status)
        cat=(p.get("categorias") or {}).get("nome","—")
        linhas.append({
            "Código":                p["codigo_interno"],
            "Produto":               p["nome"],
            "EAN":                   p.get("ean") or "",
            "Categoria":             cat,
            "Estoque (Secundária)":  round(est,2),
            "Unidade Secundária":    sigla_para_opcao(p["unidade_secundaria"]),
            "Estoque (Primária)":    round(estp,2),
            "Unidade Primária":      sigla_para_opcao(p["unidade_primaria"]),
            "Estoque Mínimo (Prim.)":round(minp,2),
            "Valor Última Compra (R$)": round(float(p.get("valor_unitario") or 0),2),
            "Status":                status,
            "Estratégico":           "⭐ Sim" if p.get("essencial") else "Não",
            "Reposição Contínua":    "Sim" if p.get("reposicao_continua") else "Não",
            "Ativo":                 "Sim" if p.get("ativo",True) else "Não",
        })
    df=pd.DataFrame(linhas)
    buf=io.BytesIO()
    with pd.ExcelWriter(buf,engine="openpyxl") as writer:
        df.to_excel(writer,index=False,sheet_name="Inventário")
        ws=writer.sheets["Inventário"]
        for i,col in enumerate(df.columns):
            largura=max((df[col].astype(str).map(len).max() if not df.empty else 0),len(col))+2
            ws.column_dimensions[chr(65+i)].width=largura
    buf.seek(0)
    return buf.getvalue()

def tela_estoque():
    st.markdown('<div class="pg">',unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📦 Controle de Estoque</div><div class="pg-sub">Inventário com conversão de unidades</div>',unsafe_allow_html=True)
    tabs=["Inventário"]
    if is_admin(): tabs+=["Ajuste Manual","Editar Produto"]
    tabs+=["Histórico de Ajustes"]
    tl=st.tabs(tabs)
    with tl[0]: _inv()
    if is_admin():
        with tl[1]: _ajuste()
        with tl[2]: _editar()
        with tl[3]: _hist_aj()
    else: tl[1]; _hist_aj()
    st.markdown("</div>",unsafe_allow_html=True)

_ROTULOS_CLASSIFICACAO = {
    "essencial": {
        "titulo": "estratégico",
        "dica_on": "Insumos estratégicos recebem prioridade na Saúde de Estoque e na Previsão de Reposição do Dashboard.",
        "dica_off": "O insumo deixará de aparecer nos painéis de prioridade do Dashboard.",
    },
    "reposicao_continua": {
        "titulo": "de reposição contínua",
        "dica_on": "Insumos de reposição contínua são tratados como itens de giro constante, priorizados no cálculo de previsão.",
        "dica_off": "O insumo deixará de ser tratado como item de reposição contínua.",
    },
}

@st.dialog("Confirmar classificação de insumo")
def _dialog_confirmar_classificacao():
    pend=st.session_state.get("class_pendente")
    if not pend:
        st.rerun(); return
    rot=_ROTULOS_CLASSIFICACAO[pend["campo"]]
    acao="marcar" if pend["novo"] else "desmarcar"
    st.markdown(f'Deseja **{acao}** o insumo **{esc(pend["nome"])}** como **{rot["titulo"]}**?')
    st.caption(rot["dica_on"] if pend["novo"] else rot["dica_off"])
    cc1,cc2=st.columns(2)
    with cc1:
        if st.button("✅ Confirmar",type="primary",use_container_width=True,key="class_dialog_confirmar"):
            definir_classificacao_produto(pend["produto_id"],pend["campo"],pend["novo"])
            st.session_state.pop("class_pendente",None)
            st.rerun()
    with cc2:
        if st.button("Cancelar",use_container_width=True,key="class_dialog_cancelar"):
            st.session_state.pop(f"{pend['campo']}_sel_{pend['produto_id']}",None)  # reseta a selectbox para o valor salvo
            st.session_state.pop("class_pendente",None)
            st.rerun()

def _inv():
    prods=listar_produtos(); cats=listar_categorias()
    if not prods: st.info("Nenhum produto."); return
    mesclar_classificacoes(prods)

    # Aplica overrides pendentes vindos dos cards de KPI. Precisa acontecer ANTES de
    # qualquer widget com a mesma key ser instanciado nesta execução — do contrário
    # o Streamlit recusa a escrita em session_state (StreamlitAPIException).
    for k,v in st.session_state.pop("inv_overrides",{}).items():
        st.session_state[k]=v

    ver_reserva=is_almoxarife()
    pode_classificar=is_admin() or is_almoxarife()
    reservas={}
    if ver_reserva:
        for s in listar_solicitacoes():
            if s.get("status") in ("pendente","aprovado"):
                pid=(s.get("produto") or {}).get("id")
                if pid: reservas[pid]=reservas.get(pid,0.0)+float(s.get("quantidade_convertida") or 0)

    total=len(prods)
    criticos=sum(1 for p in prods if float(p["quantidade_total_secundaria"])<=0)
    baixos=sum(1 for p in prods if 0<float(p["quantidade_total_secundaria"])<=float(p["estoque_minimo_primario"])*float(p["fator_conversao"]))
    ok_c=total-criticos-baixos
    estrategicos_c=sum(1 for p in prods if p.get("essencial"))

    # Cards de KPI clicáveis: clicar em um deles filtra o inventário abaixo.
    status_atual=st.session_state.get("inv_status_filtro","Todos")
    estr_atual=st.session_state.get("inv_estrategico_filtro","Todos")
    _CARDS_KPI=[
        ("📦","Total",total,{"inv_status_filtro":"Todos","inv_estrategico_filtro":"Todos","inv_reposicao_filtro":"Todos","inv_f_produto":"","inv_f_codigo":"","inv_f_ean":"","inv_f_categoria":"Todas"}),
        ("🟢","OK",ok_c,{"inv_status_filtro":"OK","inv_estrategico_filtro":"Todos"}),
        ("🟠","Estoque Baixo",baixos,{"inv_status_filtro":"Estoque Baixo","inv_estrategico_filtro":"Todos"}),
        ("🔴","Estoque Zerado",criticos,{"inv_status_filtro":"Estoque Zerado","inv_estrategico_filtro":"Todos"}),
        ("⭐","Estratégicos",estrategicos_c,{"inv_status_filtro":"Todos","inv_estrategico_filtro":"Sim"}),
    ]
    cB=st.columns(5)
    for col,(icone,rotulo,valor,overrides) in zip(cB,_CARDS_KPI):
        with col:
            ativo=(status_atual==overrides.get("inv_status_filtro","Todos")
                   and estr_atual==overrides.get("inv_estrategico_filtro","Todos"))
            if st.button(f"{icone} {rotulo} — {valor}",use_container_width=True,
                         type="primary" if ativo else "secondary",key=f"kpi_card_{rotulo}"):
                st.session_state["inv_overrides"]=overrides
                st.rerun()

    if ver_reserva:
        dados_xlsx=_planilha_estoque(prods)
        st.download_button(
            "📥 Baixar Planilha do Inventário",
            data=dados_xlsx,
            file_name=f"inventario_{datetime.date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="btn_export_inv",
        )

    st.markdown(f'<div class="card"><div class="card-h">Produtos</div>',unsafe_allow_html=True)

    # --- Filtros por coluna (mesmo padrão de Solicitações) ---
    head_ratio = [1.65, 0.72, 0.8, 1.0, 1.35, 0.8, 1.0, 0.8, 0.95, 1.05, 0.6]
    heads = ["Produto","Código","EAN","Categoria","Estoque","Mínimo","Valor Última Compra","Status","Estratégico","Repos. Contínua","Foto"]

    fc = st.columns(head_ratio)
    with fc[0]: f_produto=st.text_input("Produto",placeholder="🔍 Produto…",key="inv_f_produto",label_visibility="collapsed")
    with fc[1]: f_codigo=st.text_input("Código",placeholder="🔍 Código…",key="inv_f_codigo",label_visibility="collapsed")
    with fc[2]: f_ean=st.text_input("EAN",placeholder="🔍 EAN…",key="inv_f_ean",label_visibility="collapsed")
    with fc[3]: f_categoria=st.selectbox("Categoria",["Todas"]+[c["nome"] for c in cats],key="inv_f_categoria",label_visibility="collapsed")
    with fc[4]: st.markdown("&nbsp;",unsafe_allow_html=True)
    with fc[5]: st.markdown("&nbsp;",unsafe_allow_html=True)
    with fc[6]: st.markdown("&nbsp;",unsafe_allow_html=True)
    with fc[7]: f_status=st.selectbox("Status",["Todos","OK","Estoque Baixo","Estoque Zerado"],key="inv_status_filtro",label_visibility="collapsed")
    with fc[8]: f_estrategico=st.selectbox("Estratégico",["Todos","Sim","Não"],key="inv_estrategico_filtro",label_visibility="collapsed")
    with fc[9]: f_reposicao=st.selectbox("Repos. Contínua",["Todos","Sim","Não"],key="inv_reposicao_filtro",label_visibility="collapsed")
    with fc[10]: st.markdown("&nbsp;",unsafe_allow_html=True)

    hc = st.columns(head_ratio)
    for col, txt in zip(hc, heads):
        col.markdown(
            f'<div style="font-size:{FS_HEAD};font-weight:700;color:var(--t3);'
            f'letter-spacing:.04em;text-transform:uppercase;border-bottom:1px solid var(--bdr);'
            f'padding-bottom:.4rem;margin-bottom:.35rem;line-height:1.25;">{txt}</div>', unsafe_allow_html=True)

    def _passa(p):
        if f_produto.strip() and f_produto.strip().lower() not in p["nome"].lower(): return False
        if f_codigo.strip() and f_codigo.strip().lower() not in p["codigo_interno"].lower(): return False
        if f_ean.strip() and f_ean.strip().lower() not in (p.get("ean") or "").lower(): return False
        if f_categoria!="Todas" and (not p.get("categorias") or p["categorias"]["nome"]!=f_categoria): return False
        if f_status!="Todos":
            t,_=status_estoque(float(p["quantidade_total_secundaria"]),float(p["estoque_minimo_primario"]),float(p["fator_conversao"]))
            if _rotulo_status(t)!=f_status: return False
        if f_estrategico!="Todos" and bool(p.get("essencial"))!=(f_estrategico=="Sim"): return False
        if f_reposicao!="Todos" and bool(p.get("reposicao_continua"))!=(f_reposicao=="Sim"): return False
        return True

    fil=[p for p in prods if _passa(p)]
    st.markdown(f'<div style="font-size:{FS_SUB};color:var(--t3);margin:.2rem 0 .5rem;">{len(fil)} de {total} produto(s)</div>',unsafe_allow_html=True)

    # --- Paginação ---
    OPCOES_PP=[10,20,40]
    filtro_sig=f"{f_produto}|{f_codigo}|{f_ean}|{f_categoria}|{f_status}|{f_estrategico}|{f_reposicao}"
    if st.session_state.get("inv_filtro_sig")!=filtro_sig:
        st.session_state["inv_filtro_sig"]=filtro_sig
        st.session_state["inv_pagina"]=1

    cpp1,cpp2=st.columns([1,5])
    with cpp1:
        por_pagina=st.selectbox("Itens por página",OPCOES_PP,key="inv_por_pagina")
    if st.session_state.get("inv_por_pagina_ant")!=por_pagina:
        st.session_state["inv_por_pagina_ant"]=por_pagina
        st.session_state["inv_pagina"]=1

    total_paginas=max(1,-(-len(fil)//por_pagina)) if fil else 1
    pagina=st.session_state.get("inv_pagina",1)
    pagina=min(max(pagina,1),total_paginas)
    st.session_state["inv_pagina"]=pagina

    ini=(pagina-1)*por_pagina; fim=ini+por_pagina
    fil_pag=fil[ini:fim]

    if fil_pag:
        for p in fil_pag:
            est=float(p["quantidade_total_secundaria"]); minp=float(p["estoque_minimo_primario"]); fat=float(p["fator_conversao"])
            estp=est/fat if fat else 0; txt,cls=status_estoque(est,minp,fat); txt=_rotulo_status(txt)
            cat=(p.get("categorias") or {}).get("nome","—"); up_lbl=sigla_para_opcao(p["unidade_primaria"]); us_lbl=sigla_para_opcao(p["unidade_secundaria"])
            res_qtd=reservas.get(p["id"],0.0) if ver_reserva else 0.0
            res_html=f'<br><span style="font-size:{FS_MICRO};color:var(--warn);font-weight:600;">🔒 Reservado: {qtd_br(res_qtd)} {us_lbl}</span>' if res_qtd>0 else ''
            valor_un=p.get("valor_unitario")
            valor_html=(f'<strong style="font-size:{FS_BODY};">{_moeda(valor_un)}</strong>'
                        f'<br><span style="font-size:{FS_MICRO};color:var(--t3);">/{us_lbl}</span>'
                        if valor_un else f'<span style="font-size:{FS_SUB};color:var(--t4);">— não informado</span>')
            rc = st.columns(head_ratio)
            rc[0].markdown(f'<span style="font-size:{FS_BODY};font-weight:700;">{esc(p["nome"])}</span>', unsafe_allow_html=True)
            rc[1].markdown(f'<span class="mono" style="font-size:{FS_SUB};">{esc(p["codigo_interno"])}</span>', unsafe_allow_html=True)
            rc[2].markdown(f'<span class="mono" style="font-size:{FS_SUB};color:var(--t4);">{esc(p.get("ean") or "—")}</span>', unsafe_allow_html=True)
            rc[3].markdown(f'<span style="font-size:{FS_SUB};color:var(--t3);">{esc(cat)}</span>', unsafe_allow_html=True)
            rc[4].markdown(f'<span style="font-size:{FS_BODY};font-weight:700;">{qtd_br(est)} {us_lbl}</span><br><span style="font-size:{FS_MICRO};color:var(--t3);">= {qtd_br(estp)} {up_lbl}</span>{res_html}', unsafe_allow_html=True)
            rc[5].markdown(f'<span style="font-size:{FS_SUB};color:var(--t3);">{qtd_br(minp)} {up_lbl}</span>', unsafe_allow_html=True)
            rc[6].markdown(valor_html, unsafe_allow_html=True)
            rc[7].markdown(badge(txt,cls), unsafe_allow_html=True)
            for campo,col in (("essencial",rc[8]),("reposicao_continua",rc[9])):
                with col:
                    if pode_classificar:
                        atual=bool(p.get(campo))
                        sel=st.selectbox(campo,["Não","Sim"],index=1 if atual else 0,
                                          key=f"{campo}_sel_{p['id']}",label_visibility="collapsed")
                        novo=(sel=="Sim")
                        if novo!=atual:
                            st.session_state["class_pendente"]={"produto_id":p["id"],"nome":p["nome"],"campo":campo,"novo":novo}
                    else:
                        st.markdown(f'<span style="font-size:{FS_BODY};">{"⭐" if p.get(campo) else "—"}</span>', unsafe_allow_html=True)
            with rc[10]:
                if st.button("📷", key=f"foto_btn_{p['id']}", use_container_width=True, help="Ver/gerenciar foto"):
                    st.session_state["foto_produto"]=p
                    st.session_state.pop("foto_modo",None)
                    st.rerun()
            st.markdown('<hr style="margin:.35rem 0;border:none;border-top:1px solid var(--bdr);">', unsafe_allow_html=True)
        if st.session_state.get("class_pendente"):
            _dialog_confirmar_classificacao()
    else:
        st.markdown(f'<div style="text-align:center;color:var(--t3);font-size:{FS_SUB};padding:2rem;">Nenhum resultado</div>', unsafe_allow_html=True)

    if fil and total_paginas>1:
        cn1,cn2,cn3=st.columns([1,2,1])
        with cn1:
            if st.button("← Anterior",disabled=(pagina<=1),key="inv_prev",use_container_width=True):
                st.session_state["inv_pagina"]=pagina-1; st.rerun()
        with cn2:
            st.markdown(f'<div style="text-align:center;color:var(--t3);padding-top:.45rem;font-size:{FS_SUB};">Página {pagina} de {total_paginas}</div>',unsafe_allow_html=True)
        with cn3:
            if st.button("Próxima →",disabled=(pagina>=total_paginas),key="inv_next",use_container_width=True):
                st.session_state["inv_pagina"]=pagina+1; st.rerun()

    st.markdown("</div>",unsafe_allow_html=True)
    if fil:
        st.markdown("**📊 Ver histórico de movimentações por produto:**")
        pm={f"{p['nome']} ({p['codigo_interno']})":p for p in fil}
        cs,cb=st.columns([4,1])
        with cs: sel=st.selectbox("Produto",list(pm.keys()),key="sel_hist",label_visibility="collapsed")
        with cb:
            if st.button("📊 Ver Histórico",use_container_width=True,key="btn_hist"): st.session_state["hist_produto"]=pm[sel]; st.rerun()
    if st.session_state.get("hist_produto"): _hist_modal(st.session_state["hist_produto"])

    if st.session_state.get("foto_produto"): _foto_modal(st.session_state["foto_produto"])

def _hist_modal(prod):
    st.markdown(f'<div class="card"><div class="card-h">📊 Histórico — {esc(prod["nome"])} ({esc(prod["codigo_interno"])})</div>',unsafe_allow_html=True)
    hoje=datetime.date.today(); ini=hoje.replace(month=1,day=1)
    c1,c2,c3=st.columns([2,2,1])
    with c1: d_ini=st.date_input("De",value=ini,key="hist_ini")
    with c2: d_fim=st.date_input("Até",value=hoje,key="hist_fim")
    with c3:
        st.markdown("<div style='height:27px'></div>",unsafe_allow_html=True)
        st.button("🔍 Filtrar",key="btn_hf",use_container_width=True)
    if st.button("✖ Fechar",key="fechar_hist"): del st.session_state["hist_produto"]; st.rerun()
    movs=historico_produto(prod["id"],d_ini.strftime("%Y-%m-%d"),d_fim.strftime("%Y-%m-%d"))
    if not movs: st.info("Nenhuma movimentação no período."); st.markdown("</div>",unsafe_allow_html=True); return
    us_lbl=sigla_para_opcao(prod.get("unidade_secundaria","UN"))
    datas=[]; entradas=[]; saidas=[]; saldo=[]; acum=0.0
    for m in movs:
        data=m.get("criado_em","")[:10]; qtd=float(m.get("quantidade_convertida",0)); tipo=m.get("tipo","")
        if tipo=="entrada": acum+=qtd; entradas.append(qtd); saidas.append(0)
        else: acum=max(0,acum-qtd); saidas.append(qtd); entradas.append(0)
        datas.append(data); saldo.append(acum)
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=datas,y=saldo,name="Saldo",mode="lines+markers",line=dict(color="#CC0000",width=2),hovertemplate="<b>%{x}</b><br>Saldo: %{y:.2f}<extra></extra>"))
    fig.add_trace(go.Bar(x=datas,y=entradas,name="Entrada",marker_color="rgba(22,163,74,.6)",hovertemplate="<b>%{x}</b><br>+%{y:.2f}<extra></extra>"))
    fig.add_trace(go.Bar(x=datas,y=[-v for v in saidas],name="Saída",marker_color="rgba(220,38,38,.5)",hovertemplate="<b>%{x}</b><br>-%{y:.2f}<extra></extra>"))
    fig.update_layout(**_PL,height=280,barmode="relative",legend=dict(bgcolor="rgba(0,0,0,0)"),
                      xaxis=dict(gridcolor="rgba(0,0,0,.05)"),yaxis=dict(gridcolor="rgba(0,0,0,.05)",title=f"Qtd ({us_lbl})"))
    st.plotly_chart(fig,use_container_width=True)
    st.markdown(f'<div style="font-size:{FS_HEAD};font-weight:700;color:var(--t3);letter-spacing:.06em;text-transform:uppercase;margin:.8rem 0 .4rem;">Detalhamento</div>',unsafe_allow_html=True)
    rows=""
    for m in reversed(movs):
        tipo=m.get("tipo",""); cor="var(--ok)" if tipo=="entrada" else "var(--err)"
        sinal="+"; tipo_lbl="📥 Entrada" if tipo=="entrada" else "📤 Saída"
        if tipo!="entrada": sinal="-"
        un_lbl=sigla_para_opcao(m.get("unidade_informada","UN"))
        exe=(m.get("exe") or {}).get("nick",""); sol=(m.get("sol") or {}).get("nick","")
        resp=exe if exe else sol; subtipo=m.get("tipo_entrada") or m.get("tipo_saida") or "—"
        rows+=f'<tr><td style="color:var(--t3);font-size:{FS_SUB};">{datahora_br(m["criado_em"])}</td><td style="font-size:{FS_BODY};"><strong style="color:{cor};">{tipo_lbl}</strong></td><td style="color:var(--t3);font-size:{FS_SUB};">{subtipo}</td><td style="color:{cor};font-weight:700;font-family:var(--mono);font-size:{FS_BODY};">{sinal}{qtd_br(m["quantidade_convertida"])} {un_lbl}</td><td style="font-size:{FS_SUB};">{m.get("setor_solicitante") or "—"}</td><td style="color:var(--t3);font-size:{FS_SUB};">{m.get("numero_nf") or "—"}</td><td style="color:var(--t3);font-size:{FS_SUB};">{resp}</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Data/Hora</th><th>Tipo</th><th>Subtipo</th><th>Quantidade</th><th>Setor</th><th>NF</th><th>Responsável</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
    st.markdown("</div>",unsafe_allow_html=True)

def _foto_modal(prod):
    st.markdown(f'<div class="card"><div class="card-h">🖼️ Foto — {esc(prod["nome"])} ({esc(prod["codigo_interno"])})</div>',unsafe_allow_html=True)
    tem_foto = bool(prod.get("foto_url"))
    modo = st.session_state.get("foto_modo")

    if not tem_foto:
        st.info("Nenhuma foto cadastrada para este produto.")
        if modo == "adicionar":
            nova = st.text_input("URL da Foto", key="foto_nova_url", placeholder="Cole o link da imagem")
            if nova.strip():
                st.image(nova.strip(), width=200)
            cs, cc = st.columns(2)
            with cs:
                if st.button("💾 Salvar Foto", type="primary", use_container_width=True, key="foto_salvar_btn"):
                    if nova.strip():
                        atualizar_produto(prod["id"], {"foto_url": nova.strip()})
                        st.session_state.pop("foto_modo", None)
                        st.session_state.pop("foto_nova_url", None)
                        st.session_state.pop("foto_produto", None)
                        st.success("Foto adicionada com sucesso.")
                        st.rerun()
                    else:
                        st.error("Informe uma URL válida.")
            with cc:
                if st.button("Cancelar", use_container_width=True, key="foto_add_cancelar"):
                    st.session_state.pop("foto_modo", None); st.rerun()
        else:
            if st.button("➕ Adicionar Foto", type="primary", key="foto_add_btn"):
                st.session_state["foto_modo"] = "adicionar"; st.rerun()

    else:
        if modo == "ver":
            st.image(prod["foto_url"], caption=prod["nome"], use_container_width=True)
            if st.button("← Voltar", key="foto_ver_voltar"):
                st.session_state.pop("foto_modo", None); st.rerun()
        elif modo == "confirmar_apagar":
            st.warning("Tem certeza que deseja apagar a foto deste produto? Essa ação não pode ser desfeita.")
            ca, cb = st.columns(2)
            with ca:
                if st.button("🗑️ Sim, apagar", type="primary", use_container_width=True, key="foto_apagar_sim"):
                    atualizar_produto(prod["id"], {"foto_url": None})
                    st.session_state.pop("foto_modo", None)
                    st.session_state.pop("foto_produto", None)
                    st.success("Foto removida.")
                    st.rerun()
            with cb:
                if st.button("Cancelar", use_container_width=True, key="foto_apagar_nao"):
                    st.session_state.pop("foto_modo", None); st.rerun()
        else:
            cv, cd = st.columns(2)
            with cv:
                if st.button("👁️ Ver Foto", use_container_width=True, key="foto_ver_btn"):
                    st.session_state["foto_modo"] = "ver"; st.rerun()
            with cd:
                if st.button("🗑️ Apagar Foto", use_container_width=True, key="foto_apagar_btn"):
                    st.session_state["foto_modo"] = "confirmar_apagar"; st.rerun()

    st.markdown('<div style="margin-top:.6rem;"></div>', unsafe_allow_html=True)
    if st.button("✖ Fechar", key="fechar_foto"):
        st.session_state.pop("foto_produto", None)
        st.session_state.pop("foto_modo", None)
        st.rerun()
    st.markdown("</div>",unsafe_allow_html=True)

def _ajuste():
    u=sessao(); prods=listar_produtos()
    if not prods: st.info("Nenhum produto."); return
    pm={f"{p['nome']} ({p['codigo_interno']})":p for p in prods}
    st.markdown('<div class="card"><div class="card-h">⚙️ Ajuste Manual</div>',unsafe_allow_html=True)

    # Tela de confirmação pós-ajuste
    if st.session_state.get("ajuste_sucesso"):
        info=st.session_state["ajuste_sucesso"]
        st.success("✅ Ajuste realizado com sucesso!")
        st.markdown(f'<div style="font-size:{FS_SUB};color:var(--t3);">Estoque de **{info["nome"]}** definido para <strong>{qtd_br(info["nova"])} {info["unidade"]}</strong>.</div>',unsafe_allow_html=True)
        if st.button("➕ Sugerir novo ajuste",type="primary",use_container_width=True):
            # limpa o estado do produto ajustado para os campos voltarem ao padrão
            st.session_state.pop(f"ajuste_nova_{info['prod_id']}",None)
            st.session_state.pop(f"ajuste_motivo_{info['prod_id']}",None)
            del st.session_state["ajuste_sucesso"]
            st.rerun()
        st.markdown("</div>",unsafe_allow_html=True)
        return

    st.warning("⚠️ Sobrescreve o estoque. Use apenas para correções de inventário.")

    # Selectbox fora do form -> troca de produto atualiza tudo na hora
    sel=st.selectbox("Produto *",list(pm.keys()),key="ajuste_sel_produto")
    prod=pm[sel]
    est=float(prod["quantidade_total_secundaria"]); fat=float(prod["fator_conversao"])
    us_lbl=sigla_para_opcao(prod["unidade_secundaria"]); up_lbl=sigla_para_opcao(prod["unidade_primaria"])

    c1,c2=st.columns(2)
    with c1:
        st.markdown(f'<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;padding:.7rem;margin-bottom:.5rem;"><div style="font-size:{FS_MICRO};color:var(--t3);letter-spacing:.04em;text-transform:uppercase;">Atual</div><div style="font-size:{FS_HERO};font-weight:700;">{qtd_br(est)} {us_lbl}</div><div style="font-size:{FS_SUB};color:var(--t3);">= {qtd_br(est/fat if fat else 0)} {up_lbl}</div></div>',unsafe_allow_html=True)
        # key por produto -> reseta valor automaticamente ao trocar de item
        nova=st.number_input(f"Quantidade atual (Ajuste acrescentando ou diminuindo o valor de acordo com o que há no estoque físico) ({us_lbl}) *",min_value=0.0,value=est,step=1.0,key=f"ajuste_nova_{prod['id']}")
    with c2:
        motivo=st.text_area("Motivo *",height=100,key=f"ajuste_motivo_{prod['id']}")

    diff=nova-est; cor="var(--ok)" if diff>=0 else "var(--err)"
    st.markdown(f'<div style="font-size:{FS_SUB};color:var(--t3);padding:.2rem 0;">Variação: <strong style="color:{cor};">{("+" if diff>=0 else "")}{qtd_br(diff)} {us_lbl}</strong></div>',unsafe_allow_html=True)

    if st.button("Aplicar ↓",type="primary",use_container_width=True):
        if not motivo.strip():
            st.error("Motivo obrigatório.")
        else:
            da=abs(diff); direcao="entrada" if diff>=0 else "saida"
            # tipo_saida=None garante que este ajuste NUNCA seja contabilizado como consumo:
            # as queries de consumo (dashboard, previsão de demanda) filtram por
            # tipo_saida="SOLICITADA" ou tipo_saida="MANUAL" — ajustes ficam de fora automaticamente.
            registrar_movimentacao({
                "produto_id":            prod["id"],
                "tipo":                  direcao,          # necessário para o trigger de estoque
                "tipo_entrada":          "Ajuste Manual",   # identifica como ajuste, nunca como consumo
                "tipo_saida":            None,              # exclui das métricas de consumo/saída
                "status":                "concluido",
                "quantidade_informada":  da,
                "unidade_informada":     prod["unidade_secundaria"],
                "quantidade_convertida": da,
                "observacao":            f"[AJUSTE] {motivo.strip()}",
                "usuario_executor":      u["id"],
            })
            st.session_state["ajuste_sucesso"]={"prod_id":prod["id"],"nome":prod["nome"],"nova":nova,"unidade":us_lbl}
            st.rerun()
    st.markdown("</div>",unsafe_allow_html=True)

def _editar():
    prods=listar_produtos(apenas_ativos=False); cats=listar_categorias(); cm={c["nome"]:c["id"] for c in cats}
    if not prods: st.info("Nenhum produto."); return
    PLACEHOLDER="— Selecione um produto —"
    pm={f"{p['nome']} ({p['codigo_interno']})":p for p in prods}
    st.markdown('<div class="card"><div class="card-h">✏️ Editar Produto</div>',unsafe_allow_html=True)
    sel=st.selectbox("Produto",[PLACEHOLDER]+list(pm.keys()),key="eps")
    if sel==PLACEHOLDER:
        st.markdown(f'<div style="text-align:center;color:var(--t3);font-size:{FS_SUB};padding:1.5rem;">Selecione um produto acima para editar.</div>',unsafe_allow_html=True)
        st.markdown("</div>",unsafe_allow_html=True)
        return
    p=pm[sel]
    with st.form(f"fep_{p['id']}"):
        c1,c2=st.columns(2)
        with c1:
            ne=st.text_input("Nome",value=p["nome"])
            cc=next((c["nome"] for c in cats if c["id"]==p.get("categoria_id")),list(cm.keys())[0] if cm else "")
            ce=st.selectbox("Categoria",list(cm.keys()),index=list(cm.keys()).index(cc) if cc in cm else 0)
            # Keys por produto (upe_<id>/use_<id>): garante que, ao trocar de insumo,
            # o Streamlit reconheça automaticamente a unidade primária/secundária DESSE
            # produto, em vez de repetir o valor do produto editado anteriormente.
            upe=_u("Unidade primária",val=p["unidade_primaria"],key=f"upe_{p['id']}")
            use=_u("Unidade secundária",val=p["unidade_secundaria"],key=f"use_{p['id']}")
        with c2:
            fe=st.number_input("Fator",value=float(p["fator_conversao"]),min_value=0.001)
            eme=st.number_input("Est. mín (prim)",value=float(p["estoque_minimo_primario"]),min_value=0.0)
            eane=st.text_input("CODIGO DO PRODUTO",value=p.get("ean") or ""); ate=st.checkbox("Ativo",value=p.get("ativo",True))
            ve=st.number_input("Valor Unitário (R$) — Valor última compra",value=float(p.get("valor_unitario") or 0.0),min_value=0.0,step=0.01,format="%.2f")
        de=st.text_area("Descrição",value=p.get("descricao") or "")
        fote=st.text_input("URL da Foto (opcional)",value=p.get("foto_url") or "",help="Cole o link de uma imagem do produto (ex.: link do Supabase Storage).")
        if fote.strip():
            st.image(fote.strip(),width=160)
        st.caption("💡 Classificação de Estratégico / Reposição Contínua agora é feita direto na aba Inventário.")
        if st.form_submit_button("Salvar →",type="primary"):
            atualizar_produto(p["id"],{"nome":ne.strip(),"categoria_id":cm.get(ce),"unidade_primaria":upe,"unidade_secundaria":use,"fator_conversao":fe,"estoque_minimo_primario":eme,"ean":eane.strip() or None,"descricao":de.strip() or None,"ativo":ate,"foto_url":fote.strip() or None,"valor_unitario":ve if ve>0 else None})
            st.success(f"✅ \"{p['nome']}\" atualizado com sucesso! Selecione outro produto acima para continuar editando.")
            st.session_state.pop("eps",None)  # volta o seletor ao placeholder, solicitando nova escolha
            st.rerun()
    st.markdown("</div>",unsafe_allow_html=True)

def _hist_aj():
    movs=listar_movimentacoes(limite=100)
    aj=[m for m in movs if "[AJUSTE]" in (m.get("observacao") or "") or m.get("tipo_entrada")=="Ajuste Manual"]
    if not aj: st.info("Nenhum ajuste registrado."); return
    st.markdown('<div class="card"><div class="card-h">Histórico de Ajustes</div>',unsafe_allow_html=True)

    # --- Filtros por coluna (mesmo padrão de Solicitações) ---
    head_ratio=[1.3,1.6,1.2,1.8,1.2]
    fc=st.columns(head_ratio)
    with fc[0]:
        f_data=st.date_input("Data",value=(),key="haj_f_data",label_visibility="collapsed")
    with fc[1]: f_produto=st.text_input("Produto",placeholder="🔍 Produto…",key="haj_f_produto",label_visibility="collapsed")
    with fc[2]: st.markdown("&nbsp;",unsafe_allow_html=True)
    with fc[3]: f_motivo=st.text_input("Motivo",placeholder="🔍 Motivo…",key="haj_f_motivo",label_visibility="collapsed")
    with fc[4]: f_resp=st.text_input("Responsável",placeholder="🔍 Responsável…",key="haj_f_resp",label_visibility="collapsed")

    hc=st.columns(head_ratio)
    for col,txt in zip(hc,["Data","Produto","Variação","Motivo","Responsável"]):
        col.markdown(f'<div style="font-size:{FS_HEAD};font-weight:700;color:var(--t3);letter-spacing:.04em;text-transform:uppercase;border-bottom:1px solid var(--bdr);padding-bottom:.4rem;margin-bottom:.35rem;">{txt}</div>',unsafe_allow_html=True)

    def _passa(a):
        if len(f_data)==2:
            d0,d1=f_data
            dm=datetime.datetime.fromisoformat(a["criado_em"].replace("Z","+00:00")).date()
            if not (d0<=dm<=d1): return False
        if f_produto.strip() and f_produto.strip().lower() not in (a.get("produto") or {}).get("nome","").lower(): return False
        obs=(a.get("observacao") or "").replace("[AJUSTE] ","")
        if f_motivo.strip() and f_motivo.strip().lower() not in obs.lower(): return False
        if f_resp.strip() and f_resp.strip().lower() not in ((a.get("exe") or {}).get("nick","")).lower(): return False
        return True
    aj=[a for a in aj if _passa(a)]

    # --- Paginação (mesmo padrão do Inventário) ---
    OPCOES_PP=[10,20,40]
    filtro_sig=f"{f_data}|{f_produto}|{f_motivo}|{f_resp}"
    if st.session_state.get("haj_filtro_sig")!=filtro_sig:
        st.session_state["haj_filtro_sig"]=filtro_sig
        st.session_state["haj_pagina"]=1
    cpp1,cpp2=st.columns([1,5])
    with cpp1: por_pagina=st.selectbox("Itens por página",OPCOES_PP,key="haj_por_pagina")
    if st.session_state.get("haj_por_pagina_ant")!=por_pagina:
        st.session_state["haj_por_pagina_ant"]=por_pagina
        st.session_state["haj_pagina"]=1
    total_paginas=max(1,-(-len(aj)//por_pagina)) if aj else 1
    pagina=st.session_state.get("haj_pagina",1)
    pagina=min(max(pagina,1),total_paginas)
    st.session_state["haj_pagina"]=pagina
    ini=(pagina-1)*por_pagina; fim=ini+por_pagina
    aj_pag=aj[ini:fim]

    if not aj_pag:
        st.markdown(f'<div style="text-align:center;color:var(--t3);font-size:{FS_SUB};padding:2rem;">Nenhum resultado</div>',unsafe_allow_html=True)
        st.markdown("</div>",unsafe_allow_html=True)
        return

    rows=""
    for a in aj_pag:
        prod=a.get("produto") or {}; eu=(a.get("exe") or {}).get("nick","—")
        ds=f"+{qtd_br(a['quantidade_convertida'])}" if a["tipo"]=="entrada" else f"-{qtd_br(a['quantidade_convertida'])}"
        cor="var(--ok)" if a["tipo"]=="entrada" else "var(--err)"; obs=(a.get("observacao") or "").replace("[AJUSTE] ",""); un_lbl=sigla_para_opcao(a.get("unidade_informada","UN"))
        rows+=f'<tr><td style="color:var(--t3);font-size:{FS_SUB};">{datahora_br(a["criado_em"])}</td><td style="font-size:{FS_BODY};"><strong>{prod.get("nome","—")}</strong></td><td style="color:{cor};font-weight:700;font-family:var(--mono);font-size:{FS_BODY};">{ds} {un_lbl}</td><td style="color:var(--t3);font-size:{FS_SUB};">{obs[:50]}{"…" if len(obs)>50 else ""}</td><td style="color:var(--t3);font-size:{FS_SUB};">{eu}</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Variação</th><th>Motivo</th><th>Responsável</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)

    if total_paginas>1:
        cn1,cn2,cn3=st.columns([1,2,1])
        with cn1:
            if st.button("← Anterior",disabled=(pagina<=1),key="haj_prev",use_container_width=True):
                st.session_state["haj_pagina"]=pagina-1; st.rerun()
        with cn2:
            st.markdown(f'<div style="text-align:center;color:var(--t3);padding-top:.45rem;font-size:{FS_SUB};">Página {pagina} de {total_paginas}</div>',unsafe_allow_html=True)
        with cn3:
            if st.button("Próxima →",disabled=(pagina>=total_paginas),key="haj_next",use_container_width=True):
                st.session_state["haj_pagina"]=pagina+1; st.rerun()
    st.markdown("</div>",unsafe_allow_html=True)
