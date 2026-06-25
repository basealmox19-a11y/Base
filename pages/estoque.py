"""pages/estoque.py"""
import streamlit as st
from utils.database import listar_produtos,listar_categorias,atualizar_produto,registrar_movimentacao,listar_movimentacoes
from utils.auth import sessao,is_admin
from utils.ui import badge,status_estoque,kpi_html
from utils.fmt import qtd_br,datahora_br
UNS=["UN","CX","KG","LT","MT","PC","RL","FR","GL","DZ","CT","SC","FD","BL"]

def tela_estoque():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📦 Controle de Estoque</div><div class="pg-sub">Inventário com conversão inteligente de unidades</div>', unsafe_allow_html=True)
    tabs=["Inventário"]
    if is_admin(): tabs+=["Ajuste Manual","Editar Produto"]
    tabs+=["Histórico de Ajustes"]
    tl=st.tabs(tabs)
    with tl[0]: _inv()
    if is_admin():
        with tl[1]: _ajuste()
        with tl[2]: _editar()
        with tl[3]: _hist()
    else:
        with tl[1]: _hist()
    st.markdown("</div>", unsafe_allow_html=True)

def _inv():
    prods=listar_produtos(); cats=listar_categorias()
    if not prods: st.info("Nenhum produto cadastrado."); return
    c1,c2,c3=st.columns([3,2,2])
    with c1: busca=st.text_input("🔍 Buscar",key="eb2")
    with c2: cf=st.selectbox("Categoria",["Todas"]+[c["nome"] for c in cats])
    with c3: sf=st.selectbox("Status",["Todos","OK","Baixo","Crítico"])
    total=len(prods)
    criticos=sum(1 for p in prods if float(p["quantidade_total_secundaria"])<=0)
    baixos=sum(1 for p in prods if 0<float(p["quantidade_total_secundaria"])<=float(p["estoque_minimo_primario"])*float(p["fator_conversao"]))
    ok_c=total-criticos-baixos
    st.markdown(f'<div class="kpis" style="grid-template-columns:repeat(4,1fr);margin:.7rem 0 1rem;">{kpi_html("Total",total,"","var(--t2)")}{kpi_html("OK",ok_c,"","var(--ok)")}{kpi_html("Baixo",baixos,"","var(--warn)")}{kpi_html("Crítico",criticos,"","var(--err)")}</div>', unsafe_allow_html=True)
    fil=prods
    if busca.strip():
        b=busca.lower()
        fil=[p for p in fil if b in p["nome"].lower() or b in p["codigo_interno"].lower() or (p.get("ean") and b in p["ean"].lower())]
    if cf!="Todas": fil=[p for p in fil if p.get("categorias") and p["categorias"]["nome"]==cf]
    if sf!="Todos":
        def _s(p):
            t,_=status_estoque(float(p["quantidade_total_secundaria"]),float(p["estoque_minimo_primario"]),float(p["fator_conversao"])); return t
        fil=[p for p in fil if _s(p)==sf]
    st.markdown(f'<div class="card"><div class="card-h">Produtos ({len(fil)})</div>', unsafe_allow_html=True)
    rows=""
    for p in fil:
        est=float(p["quantidade_total_secundaria"]); minp=float(p["estoque_minimo_primario"]); fat=float(p["fator_conversao"])
        estp=est/fat if fat else 0; txt,cls=status_estoque(est,minp,fat); cat=(p.get("categorias") or {}).get("nome","—")
        rows+=f'<tr><td><strong>{p["nome"]}</strong></td><td class="mono">{p["codigo_interno"]}</td><td class="mono" style="color:var(--t4);">{p.get("ean") or "—"}</td><td style="color:var(--t3);">{cat}</td><td><strong>{qtd_br(est)} {p["unidade_secundaria"]}</strong><br><span style="font-size:.71rem;color:var(--t3);">= {qtd_br(estp)} {p["unidade_primaria"]}</span></td><td style="color:var(--t3);">{qtd_br(minp)} {p["unidade_primaria"]}</td><td>{badge(txt,cls)}</td></tr>'
    vz='<tr><td colspan="7" style="text-align:center;color:var(--t3);padding:2rem;">Nenhum resultado</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Produto</th><th>Código</th><th>EAN</th><th>Categoria</th><th>Estoque</th><th>Mínimo</th><th>Status</th></tr></thead><tbody>{rows or vz}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

def _ajuste():
    u=sessao(); prods=listar_produtos()
    if not prods: st.info("Nenhum produto."); return
    pm={f"{p['nome']} ({p['codigo_interno']})":p for p in prods}
    st.markdown('<div class="card"><div class="card-h">⚙️ Ajuste Manual</div>', unsafe_allow_html=True)
    st.warning("⚠️ Sobrescreve o estoque. Use apenas para correções de inventário.")
    with st.form("faj"):
        sel=st.selectbox("Produto *",list(pm.keys())); prod=pm[sel]
        est=float(prod["quantidade_total_secundaria"]); fat=float(prod["fator_conversao"])
        c1,c2=st.columns(2)
        with c1:
            st.markdown(f'<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;padding:.7rem;margin-bottom:.5rem;"><div style="font-size:.65rem;color:var(--t3);">ATUAL</div><div style="font-size:1.4rem;font-weight:700;">{qtd_br(est)} {prod["unidade_secundaria"]}</div><div style="font-size:.72rem;color:var(--t3);">= {qtd_br(est/fat if fat else 0)} {prod["unidade_primaria"]}</div></div>', unsafe_allow_html=True)
            nova=st.number_input(f"Nova qtd ({prod['unidade_secundaria']}) *",min_value=0.0,value=est,step=1.0)
        with c2: motivo=st.text_area("Motivo *",height=100)
        diff=nova-est; cor="var(--ok)" if diff>=0 else "var(--err)"
        st.markdown(f'<div style="font-size:.78rem;color:var(--t3);padding:.2rem 0;">Variação: <strong style="color:{cor};">{("+" if diff>=0 else "")}{qtd_br(diff)} {prod["unidade_secundaria"]}</strong></div>', unsafe_allow_html=True)
        if st.form_submit_button("Aplicar ↓",type="primary",use_container_width=True):
            if not motivo.strip(): st.error("Motivo obrigatório.")
            else:
                da=abs(diff); tm="entrada" if diff>=0 else "saida"
                registrar_movimentacao({"produto_id":prod["id"],"tipo":tm,"tipo_entrada":"Ajuste Manual","status":"concluido","quantidade_informada":da,"unidade_informada":prod["unidade_secundaria"],"quantidade_convertida":da,"observacao":f"[AJUSTE] {motivo.strip()}","usuario_executor":u["id"]})
                st.success(f"✅ Estoque ajustado para **{qtd_br(nova)} {prod['unidade_secundaria']}**"); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

def _editar():
    prods=listar_produtos(apenas_ativos=False); cats=listar_categorias(); cm={c["nome"]:c["id"] for c in cats}
    if not prods: st.info("Nenhum produto."); return
    pm={f"{p['nome']} ({p['codigo_interno']})":p for p in prods}
    st.markdown('<div class="card"><div class="card-h">✏️ Editar Produto</div>', unsafe_allow_html=True)
    sel=st.selectbox("Produto",list(pm.keys()),key="eps"); p=pm[sel]
    with st.form("fep"):
        c1,c2=st.columns(2)
        with c1:
            ne=st.text_input("Nome",value=p["nome"])
            cc=next((c["nome"] for c in cats if c["id"]==p.get("categoria_id")),list(cm.keys())[0] if cm else "")
            ce=st.selectbox("Categoria",list(cm.keys()),index=list(cm.keys()).index(cc) if cc in cm else 0)
            upe=st.selectbox("Unidade primária (Como você está recebendo? Em caixa? Paletizado?...)",UNS,index=UNS.index(p["unidade_primaria"]) if p["unidade_primaria"] in UNS else 0)
            use=st.selectbox("Unidade secundária (Como as áreas vão consumir? Unidades? A caixa completa?)",UNS,index=UNS.index(p["unidade_secundaria"]) if p["unidade_secundaria"] in UNS else 0)
        with c2:
            fe=st.number_input("Fator",value=float(p["fator_conversao"]),min_value=0.001)
            eme=st.number_input("Est. mín (prim)",value=float(p["estoque_minimo_primario"]),min_value=0.0)
            eane=st.text_input("CÓDIGO DO PRODUTO",value=p.get("ean") or "")
            ate=st.checkbox("Ativo",value=p.get("ativo",True))
        de=st.text_area("Descrição",value=p.get("descricao") or "")
        if st.form_submit_button("Salvar →",type="primary"):
            atualizar_produto(p["id"],{"nome":ne.strip(),"categoria_id":cm.get(ce),"unidade_primaria":upe,"unidade_secundaria":use,"fator_conversao":fe,"estoque_minimo_primario":eme,"ean":eane.strip() or None,"descricao":de.strip() or None,"ativo":ate})
            st.success("✅ Produto atualizado!"); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

def _hist():
    movs=listar_movimentacoes(limite=100)
    aj=[m for m in movs if "[AJUSTE]" in (m.get("observacao") or "") or m.get("tipo_entrada")=="Ajuste Manual"]
    if not aj: st.info("Nenhum ajuste registrado."); return
    st.markdown('<div class="card"><div class="card-h">Histórico de Ajustes</div>', unsafe_allow_html=True)
    rows=""
    for a in aj:
        prod=a.get("produto") or {}; eu=(a.get("exe") or {}).get("nick","—")
        ds=f"+{qtd_br(a['quantidade_convertida'])}" if a["tipo"]=="entrada" else f"-{qtd_br(a['quantidade_convertida'])}"
        cor="var(--ok)" if a["tipo"]=="entrada" else "var(--err)"
        obs=(a.get("observacao") or "").replace("[AJUSTE] ","")
        rows+=f'<tr><td style="color:var(--t3);font-size:.73rem;">{datahora_br(a["criado_em"])}</td><td><strong>{prod.get("nome","—")}</strong></td><td style="color:{cor};font-weight:700;font-family:var(--mono);">{ds} {a["unidade_informada"]}</td><td style="color:var(--t3);font-size:.73rem;">{obs[:50]}{"…" if len(obs)>50 else ""}</td><td style="color:var(--t3);">{eu}</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Variação</th><th>Motivo</th><th>Responsável</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
