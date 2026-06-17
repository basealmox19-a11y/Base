"""pages/auth.py — Login, Primeiro Acesso, Troca de Senha e Expiração a cada 2 meses"""
import re, streamlit as st
from datetime import datetime, timezone, timedelta
from utils.auth import hash_senha, fazer_login, primeiro_acesso
from utils.database import criar_usuario, buscar_por_nick, atualizar_usuario
from utils.ui import navegar

_CSS = "<style>[data-testid='block-container']{padding-top:0!important;}</style>"
_RE  = re.compile(r'^(?=.*[A-Z])(?=.*[!@#$%^&*()\-_=+\[\]{};:\'",.<>/?\\|`~]).{6,}$')

EXPIRY_DIAS = 60  # 2 meses

def _forte(s: str) -> bool:
    return bool(_RE.match(s))

def _senha_expirada(u: dict) -> bool:
    """Verifica se a senha passou de 2 meses desde a última troca."""
    alterada = u.get("senha_alterada_em")
    if not alterada:
        return False  # campo não existe ainda no schema (compatibilidade)
    try:
        if isinstance(alterada, str):
            alterada = datetime.fromisoformat(alterada.replace("Z", "+00:00"))
        agora = datetime.now(timezone.utc)
        return (agora - alterada) > timedelta(days=EXPIRY_DIAS)
    except:
        return False


def tela_login():
    st.markdown(_CSS, unsafe_allow_html=True)
    _, c, _ = st.columns([1, 1.1, 1])
    with c:
        st.markdown("<div style='height:15vh'></div>", unsafe_allow_html=True)
        st.markdown('<div class="auth-logo">SFC · ALM</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-tag">Sistema de Controle de Almoxarifado</div>', unsafe_allow_html=True)
        st.markdown('<div class="div"></div>', unsafe_allow_html=True)

        with st.form("lf"):
            nick  = st.text_input("Login (nick)", placeholder="ex: joao")
            senha = st.text_input("Senha", type="password", placeholder="••••••••")
            ok    = st.form_submit_button("Entrar →", type="primary", use_container_width=True)

        if ok:
            if not nick or not senha:
                st.error("Preencha login e senha.")
            else:
                u = fazer_login(nick.strip().lower(), senha)
                if u:
                    st.session_state["usuario"] = u
                    # Verifica se é primeiro acesso
                    if u.get("primeiro_acesso", False):
                        st.session_state["forcar_troca_senha"] = "primeiro"
                    # Verifica se a senha expirou (2 meses)
                    elif _senha_expirada(u):
                        st.session_state["forcar_troca_senha"] = "expirada"
                    navegar("dashboard")
                else:
                    st.error("Login ou senha incorretos, ou usuário inativo.")

        st.markdown(
            '<div style="text-align:center;margin-top:1rem;font-size:.7rem;color:var(--t4);">'
            'SFC Almoxarifado © 2025</div>',
            unsafe_allow_html=True)


def tela_primeiro_acesso():
    """Criação do primeiro administrador do sistema."""
    st.markdown(_CSS, unsafe_allow_html=True)
    _, c, _ = st.columns([1, 1.2, 1])
    with c:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
        st.markdown('<div class="auth-logo">SFC · ALM</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-tag">Configuração Inicial</div>', unsafe_allow_html=True)
        st.markdown("""
        <div style="background:var(--warn-bg);border:1px solid rgba(217,119,6,.3);
                    border-radius:7px;padding:.75rem 1rem;margin-bottom:1.2rem;font-size:.8rem;color:var(--warn);">
            ⚙️ Crie o primeiro administrador do sistema.
        </div>
        """, unsafe_allow_html=True)

        with st.form("paf"):
            nick   = st.text_input("Nick (login) *", placeholder="ex: admin")
            ca, cb = st.columns(2)
            with ca: senha  = st.text_input("Senha *", type="password")
            with cb: senha2 = st.text_input("Confirmar *", type="password")
            nome   = st.text_input("Nome completo (opcional)")
            criar  = st.form_submit_button("Criar Administrador →", type="primary", use_container_width=True)

        if criar:
            erros = []
            if not nick.strip(): erros.append("Nick obrigatório.")
            if not _forte(senha):  erros.append("Senha: mín. 6 chars, 1 maiúscula, 1 caractere especial.")
            if senha != senha2:    erros.append("Senhas não coincidem.")
            if not erros and buscar_por_nick(nick.strip().lower()):
                erros.append("Nick já existe.")
            if erros:
                for e in erros: st.error(e)
            else:
                dados = {
                    "nick":            nick.strip().lower(),
                    "senha_hash":      hash_senha(senha),
                    "perfil":          "admin",
                    "ativo":           True,
                    "primeiro_acesso": False,
                }
                if nome.strip(): dados["nome"] = nome.strip()
                # Salva data da criação da senha (se coluna existir)
                try: dados["senha_alterada_em"] = datetime.now(timezone.utc).isoformat()
                except: pass
                criar_usuario(dados)
                st.success(f"✅ Administrador **{nick.strip().lower()}** criado! Faça login.")
                st.session_state["pagina"] = "login"
                st.rerun()


def tela_trocar_senha():
    """Tela de troca de senha — primeiro acesso ou expiração bimestral."""
    u      = st.session_state.get("usuario", {})
    motivo = st.session_state.get("forcar_troca_senha", "primeiro")

    st.markdown(_CSS, unsafe_allow_html=True)
    _, c, _ = st.columns([1, 1.2, 1])
    with c:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
        st.markdown('<div class="auth-logo">SFC · ALM</div>', unsafe_allow_html=True)

        if motivo == "expirada":
            st.markdown('<div class="auth-tag">Renovação de Senha</div>', unsafe_allow_html=True)
            st.markdown(f"""
            <div style="background:var(--warn-bg);border:1px solid rgba(217,119,6,.25);
                        border-radius:7px;padding:.75rem 1rem;margin-bottom:1.2rem;font-size:.8rem;color:var(--warn);">
                🔒 Olá, <strong>{u.get('nick','')}</strong>! Sua senha tem mais de 2 meses.<br>
                Por segurança, defina uma nova senha para continuar.
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown('<div class="auth-tag">Primeiro Acesso — Defina sua senha</div>', unsafe_allow_html=True)
            st.markdown(f"""
            <div style="background:var(--info-bg);border:1px solid rgba(37,99,235,.25);
                        border-radius:7px;padding:.75rem 1rem;margin-bottom:1.2rem;font-size:.8rem;color:var(--info);">
                👋 Olá, <strong>{u.get('nick','')}</strong>! Defina sua senha pessoal antes de continuar.
            </div>
            """, unsafe_allow_html=True)

        st.markdown("""
        <div style="font-size:.77rem;color:var(--t3);margin-bottom:.8rem;">
            Requisitos: mínimo <strong>6 caracteres</strong>,
            pelo menos <strong>1 letra maiúscula</strong> e
            <strong>1 caractere especial</strong> (!@#$%...).
        </div>
        """, unsafe_allow_html=True)

        with st.form("fts"):
            nova  = st.text_input("Nova senha *", type="password")
            nova2 = st.text_input("Confirmar *", type="password")
            salvar = st.form_submit_button("Salvar e Entrar →", type="primary", use_container_width=True)

        if salvar:
            erros = []
            if not _forte(nova):  erros.append("Senha fraca: mín. 6 chars, 1 maiúscula, 1 especial.")
            if nova != nova2:     erros.append("Senhas não coincidem.")
            if erros:
                for e in erros: st.error(e)
            else:
                upd = {
                    "senha_hash":    hash_senha(nova),
                    "primeiro_acesso": False,
                }
                # Salva data de troca de senha (requer coluna senha_alterada_em)
                try:
                    upd["senha_alterada_em"] = datetime.now(timezone.utc).isoformat()
                except:
                    pass
                atualizar_usuario(u["id"], upd)
                u["primeiro_acesso"]  = False
                u["senha_alterada_em"] = datetime.now(timezone.utc).isoformat()
                st.session_state["usuario"] = u
                st.session_state.pop("forcar_troca_senha", None)
                st.success("✅ Senha definida com sucesso!")
                st.rerun()
