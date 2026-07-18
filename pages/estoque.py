"""pages/estoque.py — Com histórico de movimentações por produto"""
import streamlit as st, datetime
import plotly.graph_objects as go
from utils.database import (listar_produtos, listar_categorias, atualizar_produto,
    registrar_movimentacao, listar_movimentacoes, historico_produto)
from utils.auth import sessao, is_admin
from utils.ui import badge, status_estoque, kpi_html
from utils.fmt import qtd_br, datahora_br
from utils.unidades import SIGLAS, OPCOES, sigla_para_opcao, opcao_para_sigla
from utils.sanitize import esc, esc_trunc

def _u(label,val="UN",key=None):
    idx=SIGLAS.index(val) if val in SIGLAS else 0
    kw={"key":key} if key else {}
    return opcao_para_sigla(st.selectbox(label,OPCOES,index=idx,**kw))

_PL=dict(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
         font=dict(family="Plus Jakarta Sans",size=11),margin=dict(l=0,r=0,t=20,b=0))

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

def _inv():
    prods=listar_produtos(); cats=listar_categorias()
    if not prods: st.info("Nenhum produto."); return
    c1,c2,c3=st.columns([3,2,2])
    with c1: busca=st.text_input("🔍 Buscar",key="eb2")
    with c2: cf=st.selectbox("Categoria",["Todas"]+[c["nome"] for c in cats])
    with c3: sf=st.selectbox("Status",["Todos","OK","Baixo","Crítico"])
    total=len(prods)
    criticos=sum(1 for p in prods if float(p["quantidade_total_secundaria"])<=0)
    baixos=sum(1 for p in prods if 0<float(p["quantidade_total_secundaria"])<=float(p["estoque_minimo_primario"])*float(p["fator_conversao"]))
    ok_c=total-criticos-baixos
    st.markdown(f'<div class="kpis" style="grid-template-columns:repeat(4,1fr);margin:.7rem 0 1rem;">{kpi_html("Total",total,"","var(--t2)")}{kpi_html("OK",ok_c,"","var(--ok)")}{kpi_html("Baixo",baixos,"","var(--warn)")}{kpi_html("Crítico",criticos,"","var(--err)")}</div>',unsafe_allow_html=True)
    fil=prods
    if busca.strip():
        b=busca.lower(); fil=[p for p in fil if b in p["nome"].lower() or b in p["codigo_interno"].lower() or (p.get("ean") and b in p["ean"].lower())]
    if cf!="Todas": fil=[p for p in fil if p.get("categorias") and p["categorias"]["nome"]==cf]
    if sf!="Todos":
        def _s(p): t,_=status_estoque(float(p["quantidade_total_secundaria"]),float(p["estoque_minimo_primario"]),float(p["fator_conversao"])); return t
        fil=[p for p in fil if _s(p)==sf]
    st.markdown(f'<div class="card"><div class="card-h">Produtos ({len(fil)})</div>',unsafe_allow_html=True)

    # --- Paginação ---
    OPCOES_PP=[10,20,40]
    filtro_sig=f"{busca}|{cf}|{sf}"
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

    rows=""
    for p in fil_pag:
        est=float(p["quantidade_total_secundaria"]); minp=float(p["estoque_minimo_primario"]); fat=float(p["fator_conversao"])
        estp=est/fat if fat else 0; txt,cls=status_estoque(est,minp,fat)
        cat=(p.get("categorias") or {}).get("nome","—"); up_lbl=sigla_para_opcao(p["unidade_primaria"]); us_lbl=sigla_para_opcao(p["unidade_secundaria"])
        rows+=f'<tr><td><strong>{p["nome"]}</strong></td><td class="mono">{p["codigo_interno"]}</td><td class="mono" style="color:var(--t4);">{p.get("ean") or "—"}</td><td style="color:var(--t3);">{cat}</td><td><strong>{qtd_br(est)} {us_lbl}</strong><br><span style="font-size:.71rem;color:var(--t3);">= {qtd_br(estp)} {up_lbl}</span></td><td style="color:var(--t3);">{qtd_br(minp)} {up_lbl}</td><td>{badge(txt,cls)}</td></tr>'
    vz='<tr><td colspan="7" style="text-align:center;color:var(--t3);padding:2rem;">Nenhum resultado</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Produto</th><th>Código</th><th>EAN</th><th>Categoria</th><th>Estoque</th><th>Mínimo</th><th>Status</th></tr></thead><tbody>{rows or vz}</tbody></table>',unsafe_allow_html=True)

    if fil and total_paginas>1:
        cn1,cn2,cn3=st.columns([1,2,1])
        with cn1:
            if st.button("← Anterior",disabled=(pagina<=1),key="inv_prev",use_container_width=True):
                st.session_state["inv_pagina"]=pagina-1; st.rerun()
        with cn2:
            st.markdown(f'<div style="text-align:center;color:var(--t3);padding-top:.45rem;font-size:.82rem;">Página {pagina} de {total_paginas}</div>',unsafe_allow_html=True)
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
    st.markdown('<div style="font-size:.75rem;font-weight:700;color:var(--t3);letter-spacing:.06em;text-transform:uppercase;margin:.8rem 0 .4rem;">Detalhamento</div>',unsafe_allow_html=True)
    rows=""
    for m in reversed(movs):
        tipo=m.get("tipo",""); cor="var(--ok)" if tipo=="entrada" else "var(--err)"
        sinal="+"; tipo_lbl="📥 Entrada" if tipo=="entrada" else "📤 Saída"
        if tipo!="entrada": sinal="-"
        un_lbl=sigla_para_opcao(m.get("unidade_informada","UN"))
        exe=(m.get("exe") or {}).get("nick",""); sol=(m.get("sol") or {}).get("nick","")
        resp=exe if exe else sol; subtipo=m.get("tipo_entrada") or m.get("tipo_saida") or "—"
        rows+=f'<tr><td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td><td><strong style="color:{cor};">{tipo_lbl}</strong></td><td style="color:var(--t3);font-size:.75rem;">{subtipo}</td><td style="color:{cor};font-weight:700;font-family:var(--mono);">{sinal}{qtd_br(m["quantidade_convertida"])} {un_lbl}</td><td>{m.get("setor_solicitante") or "—"}</td><td style="color:var(--t3);">{m.get("numero_nf") or "—"}</td><td style="color:var(--t3);">{resp}</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Data/Hora</th><th>Tipo</th><th>Subtipo</th><th>Quantidade</th><th>Setor</th><th>NF</th><th>Responsável</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
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
        st.markdown(f'<div style="font-size:.85rem;color:var(--t3);">Estoque de **{info["nome"]}** definido para <strong>{qtd_br(info["nova"])} {info["unidade"]}</strong>.</div>',unsafe_allow_html=True)
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
        st.markdown(f'<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;padding:.7rem;margin-bottom:.5rem;"><div style="font-size:.65rem;color:var(--t3);">ATUAL</div><div style="font-size:1.4rem;font-weight:700;">{qtd_br(est)} {us_lbl}</div><div style="font-size:.72rem;color:var(--t3);">= {qtd_br(est/fat if fat else 0)} {up_lbl}</div></div>',unsafe_allow_html=True)
        # key por produto -> reseta valor automaticamente ao trocar de item
        nova=st.number_input(f"Quantidade atual (Ajuste acrescentando ou diminuindo o valor de acordo com o que há no estoque físico) ({us_lbl}) *",min_value=0.0,value=est,step=1.0,key=f"ajuste_nova_{prod['id']}")
    with c2:
        motivo=st.text_area("Motivo *",height=100,key=f"ajuste_motivo_{prod['id']}")

    diff=nova-est; cor="var(--ok)" if diff>=0 else "var(--err)"
    st.markdown(f'<div style="font-size:.78rem;color:var(--t3);padding:.2rem 0;">Variação: <strong style="color:{cor};">{("+" if diff>=0 else "")}{qtd_br(diff)} {us_lbl}</strong></div>',unsafe_allow_html=True)

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
    pm={f"{p['nome']} ({p['codigo_interno']})":p for p in prods}
    st.markdown('<div class="card"><div class="card-h">✏️ Editar Produto</div>',unsafe_allow_html=True)
    sel=st.selectbox("Produto",list(pm.keys()),key="eps"); p=pm[sel]
    with st.form("fep"):
        c1,c2=st.columns(2)
        with c1:
            ne=st.text_input("Nome",value=p["nome"])
            cc=next((c["nome"] for c in cats if c["id"]==p.get("categoria_id")),list(cm.keys())[0] if cm else "")
            ce=st.selectbox("Categoria",list(cm.keys()),index=list(cm.keys()).index(cc) if cc in cm else 0)
            upe=_u("Unidade primária",val=p["unidade_primaria"],key="upe"); use=_u("Unidade secundária",val=p["unidade_secundaria"],key="use")
        with c2:
            fe=st.number_input("Fator",value=float(p["fator_conversao"]),min_value=0.001)
            eme=st.number_input("Est. mín (prim)",value=float(p["estoque_minimo_primario"]),min_value=0.0)
            eane=st.text_input("CODIGO DO PRODUTO",value=p.get("ean") or ""); ate=st.checkbox("Ativo",value=p.get("ativo",True))
        de=st.text_area("Descrição",value=p.get("descricao") or "")
        if st.form_submit_button("Salvar →",type="primary"):
            atualizar_produto(p["id"],{"nome":ne.strip(),"categoria_id":cm.get(ce),"unidade_primaria":upe,"unidade_secundaria":use,"fator_conversao":fe,"estoque_minimo_primario":eme,"ean":eane.strip() or None,"descricao":de.strip() or None,"ativo":ate})
            st.success("✅ Produto atualizado!"); st.rerun()
    st.markdown("</div>",unsafe_allow_html=True)

def _hist_aj():
    movs=listar_movimentacoes(limite=100)
    aj=[m for m in movs if "[AJUSTE]" in (m.get("observacao") or "") or m.get("tipo_entrada")=="Ajuste Manual"]
    if not aj: st.info("Nenhum ajuste registrado."); return
    st.markdown('<div class="card"><div class="card-h">Histórico de Ajustes</div>',unsafe_allow_html=True)
    rows=""
    for a in aj:
        prod=a.get("produto") or {}; eu=(a.get("exe") or {}).get("nick","—")
        ds=f"+{qtd_br(a['quantidade_convertida'])}" if a["tipo"]=="entrada" else f"-{qtd_br(a['quantidade_convertida'])}"
        cor="var(--ok)" if a["tipo"]=="entrada" else "var(--err)"; obs=(a.get("observacao") or "").replace("[AJUSTE] ",""); un_lbl=sigla_para_opcao(a.get("unidade_informada","UN"))
        rows+=f'<tr><td style="color:var(--t3);font-size:.73rem;">{datahora_br(a["criado_em"])}</td><td><strong>{prod.get("nome","—")}</strong></td><td style="color:{cor};font-weight:700;font-family:var(--mono);">{ds} {un_lbl}</td><td style="color:var(--t3);font-size:.73rem;">{obs[:50]}{"…" if len(obs)>50 else ""}</td><td style="color:var(--t3);">{eu}</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Variação</th><th>Motivo</th><th>Responsável</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
    st.markdown("</div>",unsafe_allow_html=True)
