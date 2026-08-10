"""utils/auth.py"""
import bcrypt, streamlit as st
from utils.database import buscar_por_nick, contar_usuarios

def hash_senha(s): return bcrypt.hashpw(s.encode(), bcrypt.gensalt()).decode()
def verificar_senha(s, h):
    try: return bcrypt.checkpw(s.encode(), h.encode())
    except: return False

def fazer_login(nick, senha):
    u = buscar_por_nick(nick)
    if not u or not u.get("ativo"): return None
    if not verificar_senha(senha, u["senha_hash"]): return None
    return u

def sessao(): return st.session_state.get("usuario")
def primeiro_acesso(): return contar_usuarios() == 0
def is_admin():
    u = sessao(); return u is not None and u["perfil"] == "admin"
def is_almoxarife():
    u = sessao(); return u is not None and u["perfil"] in ("admin","almoxarife")
def is_usuario_simples():
    u = sessao(); return u is not None and u["perfil"] == "usuario"

def pode(acao):
    u = sessao()
    if not u: return False
    p = u["perfil"]
    m = {
        "dashboard":      ["admin","almoxarife"],
        "entrada":        ["admin","almoxarife"],
        "saida_manual":   ["admin","almoxarife"],
        "saida_aprovada": ["admin","almoxarife"],
        "estoque":        ["admin","almoxarife"],
        "notas":          ["admin","almoxarife"],
        "usuarios":       ["admin"],
        "configuracoes":  ["admin"],
        "solicitar":      ["admin","almoxarife","usuario"],
        "solicitacoes":   ["admin","almoxarife","usuario"],
        "aprovar":        ["admin"],
    }
    return p in m.get(acao, [])
