"""pages/usuarios.py"""
import streamlit as st
from utils.database import listar_usuarios,criar_usuario,atualizar_usuario,buscar_por_nick,excluir_usuario
from utils.auth import hash_senha,sessao
from utils.ui import badge,kpi_html
from utils.fmt import datahora_br
from utils.sanitize import esc, esc_trunc

PERFIS=["admin","almoxarife","usuario"]
P_LABEL={"admin":"Administrador","almoxarife":"Almoxarife","usuario":"Usuário"}
P_COR={"admin":"var(--err)","almoxarife":"var(--warn)","usuario":"var(--info)"}


def tela_usuarios():
    st.markdown('<div class="pg">',unsafe_allow_html=True)
    st.markdown('<div class="pg-title">👥 Gestão de Usuários</div><div class="pg-sub">Cadastre e gerencie acessos</div>',unsafe_allow_html=True)
    t1,t2=st.tabs(["Usuários Cadastrados","Novo Usuário"])
    with t1: _listar()
    with t2: _cadastrar()
    st.markdown("</div>",unsafe_allow_html=True)

def _listar():
    ul=sessao(); us=listar_usuarios()
    at=sum(1 for u in us if u["ativo"]); it=len(us)-at
    st.markdown(f'<div class="kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:1rem;">{kpi_html("Total",len(us),"","var(--t2)")}{kpi_html("Ativos",at,"","var(--ok)")}{kpi_html("Inativos",it,"","var(--t3)")}</div>',unsafe_allow_html=True)
    st.markdown('<div class="card"><div class="card-h">Lista de Usuários</div>',unsafe_allow_html=True)
    rows=""
    for u in us:
        bx=badge("Ativo","ok") if u["ativo"] else badge("Inativo","cancelado")
        cor=P_COR.get(u["perfil"],"var(--t3)")
        rows+=f'<tr><td class="mono">{u["nick"]}</td><td style="color:var(--t3);">{u.get("nome") or "—"}</td><td style="color:{cor};font-weight:600;font-size:.76rem;">{P_LABEL.get(u["perfil"],"—")}</td><td style="color:var(--t3);">{u.get("email") or "—"}</td><td>{bx}</td><td style="color:var(--t3);font-size:.73rem;">{datahora_br(u["criado_em"])}</td></tr>'
    st.markdown(f'<table class="tbl"><thead><tr><th>Nick</th><th>Nome</th><th>Perfil</th><th>E-mail</th><th>Status</th><th>Criado em</th></tr></thead><tbody>{rows}</tbody></table>',unsafe_allow_html=True)
    st.markdown("</div>",unsafe_allow_html=True)
    outros=[u for u in us if u["id"]!=ul["id"]]
    if not outros: return
    with st.expander("✏️ Editar usuário"):
        um={f"{u['nick']} ({P_LABEL.get(u['perfil'],'')})":u for u in outros}
        sel=st.selectbox("Selecione",list(um.keys()),key="seu"); us_=um[sel]
        with st.form("feu"):
            c1,c2=st.columns(2)
            with c1: ne=st.text_input("Nome",value=us_.get("nome") or ""); ee=st.text_input("E-mail",value=us_.get("email") or "")
            with c2:
                pe=st.selectbox("Perfil",PERFIS,index=PERFIS.index(us_["perfil"]) if us_["perfil"] in PERFIS else 2,format_func=lambda x:P_LABEL[x])
                ae=st.selectbox("Status",["ativo","inativo"],index=0 if us_["ativo"] else 1)
                nsp=st.text_input("Nova senha (em branco=manter)",type="password")
            if st.form_submit_button("Salvar →",type="primary"):
                d={"nome":ne.strip() or None,"email":ee.strip() or None,"perfil":pe,"ativo":ae=="ativo"}
                if nsp.strip():
                    if len(nsp)<4: st.error("Mín. 4 chars."); st.stop()
                    d["senha_hash"]=hash_senha(nsp)
                atualizar_usuario(us_["id"],d); st.success(f"✅ {us_['nick']} atualizado!"); st.rerun()
    with st.expander("⚙️ Ações administrativas (Reset de Senha / Excluir)"):
        st.warning("⚠️ Ações irreversíveis.")
        um2={f"{u['nick']} ({P_LABEL.get(u['perfil'],'')})":u for u in outros}
        sel2=st.selectbox("Selecione o usuário",list(um2.keys()),key="sel2"); u2=um2[sel2]
        cr,ce=st.columns(2)
        with cr:
            st.markdown("**🔑 Reset de Senha**"); st.caption(f"Volta senha de **{u2['nick']}** para a senha padrão do sistema.")
            if st.button("Resetar senha",key="btn_reset",use_container_width=True):
                st.session_state["conf_reset"]=u2; st.rerun()
        with ce:
            st.markdown("**🗑️ Excluir Usuário**"); st.caption(f"Remove **todos** os dados de **{u2['nick']}**")
            if st.button("Excluir usuário",key="btn_excluir",use_container_width=True):
                st.session_state["conf_excluir"]=u2; st.rerun()
    if st.session_state.get("conf_reset"):
        ur=st.session_state["conf_reset"]
        st.markdown(f'<div style="background:var(--warn-bg);border:2px solid rgba(217,119,6,.35);border-radius:10px;padding:1.2rem;margin:.8rem 0;"><strong>🔑 Confirmar Reset</strong><br><span style="font-size:.85rem;">Senha de <strong>{ur["nick"]}</strong> → <code>{SENHA_PADRAO}</code></span></div>',unsafe_allow_html=True)
        cs,cn,_=st.columns([1,1,4])
        with cs:
            if st.button("✅ Sim, resetar",type="primary",use_container_width=True):
                atualizar_usuario(ur["id"],{"senha_hash":hash_senha(_get_reset_senha())})
                st.success(f"✅ Senha de {ur['nick']} resetada."); del st.session_state["conf_reset"]; st.rerun()
        with cn:
            if st.button("↩ Cancelar",key="cn_reset",use_container_width=True):
                del st.session_state["conf_reset"]; st.rerun()
    if st.session_state.get("conf_excluir"):
        ue=st.session_state["conf_excluir"]
        st.markdown(f'<div style="background:var(--err-bg);border:2px solid rgba(220,38,38,.3);border-radius:10px;padding:1.2rem;margin:.8rem 0;"><strong>🗑️ Confirmar Exclusão</strong><br><span style="font-size:.85rem;">Usuário <strong>{ue["nick"]}</strong> será <strong>permanentemente excluído</strong>.</span></div>',unsafe_allow_html=True)
        cs,cn,_=st.columns([1,1,4])
        with cs:
            if st.button("🗑️ Sim, excluir",type="primary",use_container_width=True):
                excluir_usuario(ue["id"]); st.success("Ação Executada com Sucesso!"); del st.session_state["conf_excluir"]; st.rerun()
        with cn:
            if st.button("↩ Cancelar",key="cn_excluir",use_container_width=True):
                del st.session_state["conf_excluir"]; st.rerun()

def _cadastrar():
    st.markdown('<div class="card"><div class="card-h">➕ Novo Usuário</div>',unsafe_allow_html=True)
    st.info("Senha temporária — usuário deverá trocar no primeiro acesso.")
    if st.session_state.get("usuario_criado_ok"):
        st.success("🎉 Cadastro Realizado Com Sucesso!")
        if st.button("➕ Cadastrar outro",type="primary"):
            del st.session_state["usuario_criado_ok"]; st.rerun()
        st.markdown("</div>",unsafe_allow_html=True); return
    with st.form("fnu",clear_on_submit=True):
        c1,c2=st.columns(2)
        with c1:
            nick=st.text_input("Nick *",placeholder="ex: maria.silva")
            nome=st.text_input("Nome completo (opcional)"); email=st.text_input("E-mail (opcional)")
        with c2:
            perfil=st.selectbox("Perfil *",PERFIS,format_func=lambda x:P_LABEL[x])
            senha=st.text_input("Senha temporária *",type="password"); senha2=st.text_input("Confirmar *",type="password")
        if st.form_submit_button("Criar Usuário →",type="primary",use_container_width=True):
            erros=[]
            if not nick.strip(): erros.append("Nick obrigatório.")
            if len(senha)<4: erros.append("Senha mín. 4 chars.")
            if senha!=senha2: erros.append("Senhas não coincidem.")
            if not erros and buscar_por_nick(nick.strip().lower()): erros.append("Nick já cadastrado.")
            if erros:
                for e in erros: st.error(e)
            else:
                d={"nick":nick.strip().lower(),"senha_hash":hash_senha(senha),"perfil":perfil,"ativo":True,"primeiro_acesso":True}
                if nome.strip(): d["nome"]=nome.strip()
                if email.strip(): d["email"]=email.strip()
                criar_usuario(d); st.session_state["usuario_criado_ok"]=True; st.rerun()
    st.markdown("</div>",unsafe_allow_html=True)
