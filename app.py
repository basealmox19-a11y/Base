"""app.py — SFC Almoxarifado"""
import streamlit as st
st.set_page_config(page_title="SFC Almoxarifado",page_icon="📦",layout="wide",initial_sidebar_state="collapsed")

from utils.ui import inject_css, topbar, pagina_atual, navegar
from utils.auth import sessao, primeiro_acesso

from pages.auth import tela_login, tela_primeiro_acesso, tela_trocar_senha
from pages.dashboard import tela_dashboard
from pages.entrada import tela_entrada
from pages.saidas import tela_solicitacoes, tela_saida_manual, tela_saida_aprovada
from pages.solicitacoes import tela_solicitacoes_usuario, tela_solicitacoes_almoxarife
from pages.estoque import tela_estoque
from pages.notas import tela_notas
from pages.usuarios import tela_usuarios
from pages.configuracoes import tela_configuracoes

def main():
    inject_css()
    u=sessao()
    if not u:
        if primeiro_acesso(): tela_primeiro_acesso()
        else: tela_login()
        return
    if st.session_state.get("forcar_troca_senha") or u.get("primeiro_acesso",False):
        tela_trocar_senha(); return
    perfil=u["perfil"]
    if perfil=="usuario": _rota_usuario(u)
    elif perfil=="almoxarife": _rota_almoxarife(u)
    else: _rota_admin(u)

def _rota_usuario(u):
    ini=(u.get("nick") or "?")[0].upper()
    st.markdown(f'<div class="bar"><div class="brand">SFC &nbsp;|&nbsp; ALM</div><div style="display:flex;align-items:center;gap:.5rem;color:rgba(255,255,255,.9);font-size:.76rem;"><span style="color:rgba(255,255,255,.55);font-size:.68rem;">Usuário</span><div class="av">{ini}</div><span style="font-weight:600;">{u.get("nick","")}</span></div></div>',unsafe_allow_html=True)
    st.markdown('<div class="subnav">',unsafe_allow_html=True)
    cols=st.columns(3)
    with cols[0]:
        st.markdown('<div class="nav-on">',unsafe_allow_html=True)
        st.button("📋 Solicitações",key="nav_sol_usr")
        st.markdown("</div>",unsafe_allow_html=True)
    with cols[2]:
        st.markdown('<div class="nav-sair">',unsafe_allow_html=True)
        if st.button("Sair →",key="nav_sair_usr"): st.session_state.clear(); st.rerun()
        st.markdown("</div>",unsafe_allow_html=True)
    st.markdown("</div>",unsafe_allow_html=True)
    tela_solicitacoes_usuario()

def _rota_almoxarife(u):
    pagina=pagina_atual()
    MENU=[("Dashboard","dashboard"),("Entrada","entrada"),("Solicitações","solicitacoes"),
          ("Saída Manual","saida_manual"),("Saída Aprovada","saida_aprovada"),
          ("Estoque","estoque"),("Notas Fiscais","notas")]
    ini=(u.get("nick") or "?")[0].upper()
    st.markdown(f'<div class="bar"><div class="brand">SFC &nbsp;|&nbsp; ALM</div><div style="display:flex;align-items:center;gap:.5rem;color:rgba(255,255,255,.9);font-size:.76rem;"><span style="color:rgba(255,255,255,.55);font-size:.68rem;">Almoxarife</span><div class="av">{ini}</div><span style="font-weight:600;">{u.get("nick","")}</span></div></div>',unsafe_allow_html=True)
    st.markdown('<div class="subnav">',unsafe_allow_html=True)
    cols=st.columns(len(MENU)+1)
    for i,(label,dest) in enumerate(MENU):
        with cols[i]:
            st.markdown(f'<div class="{"nav-on" if pagina==dest else ""}">',unsafe_allow_html=True)
            if st.button(label,key=f"nav_{dest}"): navegar(dest)
            st.markdown("</div>",unsafe_allow_html=True)
    with cols[-1]:
        st.markdown('<div class="nav-sair">',unsafe_allow_html=True)
        if st.button("Sair →",key="nav_sair"): st.session_state.clear(); st.rerun()
        st.markdown("</div>",unsafe_allow_html=True)
    st.markdown("</div>",unsafe_allow_html=True)
    rotas={"dashboard":tela_dashboard,"entrada":tela_entrada,"solicitacoes":tela_solicitacoes_almoxarife,
           "saida_manual":tela_saida_manual,"saida_aprovada":tela_saida_aprovada,"estoque":tela_estoque,"notas":tela_notas}
    rotas.get(pagina,tela_dashboard)()

def _rota_admin(u):
    pagina=pagina_atual()
    topbar(pagina,u)
    rotas={"dashboard":tela_dashboard,"entrada":tela_entrada,"solicitacoes":tela_solicitacoes,
           "saida_manual":tela_saida_manual,"saida_aprovada":tela_saida_aprovada,"estoque":tela_estoque,
           "notas":tela_notas,"usuarios":tela_usuarios,"configuracoes":tela_configuracoes}
    rotas.get(pagina,tela_dashboard)()

if __name__=="__main__": main()
