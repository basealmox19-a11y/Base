"""pages/solicitacoes.py — Solicitações ao almoxarifado + Solicitação de Compra"""
import streamlit as st
from utils.database import (
    listar_produtos, listar_setores, registrar_movimentacao,
    listar_solicitacoes, atualizar_movimentacao, listar_notificacoes_usuario,
    estoque_disponivel, criar_solicitacao_compra, listar_solicitacoes_compra,
    atualizar_solicitacao_compra, get_sb,
)

def _listar_unificadas(status=None) -> list:
    """Une almoxarifado + compras numa lista ordenada por data. Autossuficiente."""
    alm  = listar_solicitacoes(status)
    comp = listar_solicitacoes_compra(status)
    for s in alm:  s["origem"] = "almox"
    for s in comp: s["origem"] = "compra"
    itens = alm + comp
    itens.sort(key=lambda x: x.get("criado_em") or "", reverse=True)
    return itens
from utils.auth import sessao
from utils.ui import badge
from utils.fmt import datahora_br, qtd_br, agora_iso
from utils.unidades import sigla_para_opcao
from utils.sanitize import esc, esc_trunc


# ══ CONSTANTES ══════════════════════════════════════════════════════════════════
STATUS_COMPRA_OPCOES = [
    "Requisição enviada ao CNR",
    "Pedido de Compra Criado",
    "Aguardando Entrega",
    "Recebido",
    "Cancelado",
]

# Cores de badge por status de andamento
_COR_STATUS = {
    "Requisição enviada ao CNR": ("var(--info)",  "📋"),
    "Pedido de Compra Criado":   ("var(--warn)",  "📝"),
    "Aguardando Entrega":        ("var(--warn)",  "🚚"),
    "Recebido":                  ("var(--ok)",    "✅"),
    "Cancelado":                 ("var(--err)",   "🚫"),
}


def _badge_status_compra(status: str) -> str:
    """Retorna HTML de badge colorido para o status de andamento da compra."""
    cor, emoji = _COR_STATUS.get(status, ("var(--t3)", "🔄"))
    return (f'<span style="display:inline-block;font-size:.72rem;font-weight:600;'
            f'color:{cor};background:color-mix(in srgb,{cor} 12%,transparent);'
            f'border:1px solid color-mix(in srgb,{cor} 30%,transparent);'
            f'border-radius:4px;padding:.1rem .45rem;">'
            f'{emoji} {esc(status)}</span>')


# ══ TELA USUÁRIO ════════════════════════════════════════════════════════════════

def tela_solicitacoes_usuario():
    u = sessao()
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📋 Solicitações</div>'
                '<div class="pg-sub">Faça pedidos ao almoxarifado e acompanhe seus status</div>',
                unsafe_allow_html=True)
 
    # Notificações de aprovação
    notifs = listar_notificacoes_usuario(u["nick"])
    for n in notifs:
        prod = (n.get("produto") or {}).get("nome", "—")
        un   = sigla_para_opcao(n.get("unidade_informada", "UN"))
        st.success(f"🔔 **Aprovada!** {qtd_br(n['quantidade_informada'])} {un} de **{prod}** está reservado e pronto para retirada.")
        if st.button("✅ Entendido", key=f"notif_{n['id']}"):
            try: atualizar_movimentacao(n["id"], {"notificacao_lida": True})
            except: pass
            st.rerun()
 
    # ── Notificações: aprovação / rejeição de compra ──────────────────────────
    sc_todas  = listar_solicitacoes_compra()
    sc_minhas = [s for s in sc_todas if s.get("nick_solicitante") == u["nick"]]

    for s in sc_minhas:
        # Notificação de aprovação ou rejeição ainda não lida
        if not s.get("notificacao_compra_lida", True) and s.get("status") in ("aprovado", "rejeitado"):
            if s["status"] == "aprovado":
                st.success(
                    f"🔔 **Pedido aprovado!** _{esc(s['produto_descricao'])}_ — "
                    f"O planejamento seguirá o processo de compra. "
                    f"Acompanhe na aba **Minhas Solicitações**."
                )
            else:
                motivo = s.get("motivo_rejeicao", "")
                st.error(
                    f"❌ **Solicitação reprovada!** _{esc(s['produto_descricao'])}_ — "
                    f"Favor verificar o motivo na aba **Minhas Solicitações**."
                    + (f" Motivo: {esc(motivo)}" if motivo else "")
                )
            if st.button("✅ Entendido", key=f"notif_sc_{s['id']}"):
                try: atualizar_solicitacao_compra(s["id"], {"notificacao_compra_lida": True})
                except: pass
                st.rerun()

        # Notificação de mudança de status de andamento (após aprovação)
        if (s.get("status") == "aprovado"
                and s.get("status_compra")
                and not s.get("notificacao_status_lida", True)):
            sc_status = s.get("status_compra", "")
            st.info(
                f"🔄 **Atualização de compra:** _{esc(s['produto_descricao'])}_ — "
                f"Novo status: **{esc(sc_status)}**. "
                f"Veja detalhes na aba **Minhas Solicitações**."
            )
            if st.button("✅ Entendido", key=f"notif_sc_status_{s['id']}"):
                try: atualizar_solicitacao_compra(s["id"], {"notificacao_status_lida": True})
                except: pass
                st.rerun()

    t1, t2 = st.tabs(["Solicitação ao Almoxarifado", "Minhas Solicitações"])
    with t1: _form_solicitar(u)
    with t2: _minhas(u, sc_minhas)
    st.markdown("</div>", unsafe_allow_html=True)


# ══ TELA ALMOXARIFE / ADMIN ══════════════════════════════════════════════════════

def tela_solicitacoes_almoxarife():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown(
        '<div class="pg-title">📋 Solicitações</div>'
        '<div class="pg-sub">Gerencie aprovações e consulte o histórico</div>',
        unsafe_allow_html=True,
    )
    t1, t2, t3 = st.tabs(["Aprovar / Rejeitar", "Compras em Andamento", "Histórico"])
    with t1: _aprovar_unificado()
    with t2: _compras_em_andamento()
    with t3: _hist_completo()
    st.markdown("</div>", unsafe_allow_html=True)


def tela_solicitacoes_admin():
    """Tela de solicitacoes para o perfil Administrador.
    Acesso completo: pode fazer solicitacoes como usuario
    e tambem gerenciar aprovacoes, compras e historico.
    """
    u = sessao()
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown(
        '<div class="pg-title">📋 Solicitações</div>'
        '<div class="pg-sub">Acesso completo — solicitações, aprovações, compras e histórico</div>',
        unsafe_allow_html=True,
    )
    t1, t2, t3, t4 = st.tabs([
        "Solicitação ao Almoxarifado",
        "Aprovar / Rejeitar",
        "Compras em Andamento",
        "Histórico",
    ])
    with t1: _form_solicitar(u)
    with t2: _aprovar_unificado()
    with t3: _compras_em_andamento()
    with t4: _hist_completo()
    st.markdown("</div>", unsafe_allow_html=True)


# ── Form: Solicitação ao Almoxarifado ────────────────────────────────────────

def _form_solicitar(u):
    if st.session_state.get("sol_enviada_ok"):
        st.success("📨 **Solicitação Enviada.** O retorno de aprovação será dado no seu aplicativo.")
        if st.button("➕ Nova Solicitação ao Almoxarifado", type="primary"):
            del st.session_state["sol_enviada_ok"]
            st.session_state.pop("sol_prod_sel", None)
            st.rerun()
        return

    prods = listar_produtos()
    sets  = listar_setores()
    if not prods:
        st.warning("Nenhum produto cadastrado.")
        return

    pm = {p["nome"]: p for p in prods}
    sn = [s["nome"] for s in sets] or ["Sem setor"]

    st.markdown('<div class="card"><div class="card-h">📝 Solicitação ao Almoxarifado</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        prod_nome = st.selectbox("Produto *", list(pm.keys()), key="sol_prod_sel")
        prod      = pm[prod_nome]
        un_sec    = prod.get("unidade_secundaria", "UN")
        un_lbl    = sigla_para_opcao(un_sec)
        disp      = estoque_disponivel(prod["id"])
        bruto     = float(prod.get("quantidade_total_secundaria", 0))
        reservado = max(0.0, bruto - disp)
        cor_est   = "var(--ok)" if disp > 0 else "var(--err)"
        linha_reservado = (
            f'🔒 Reservado (aguardando retirada): <strong style="color:var(--warn);">{qtd_br(reservado)} {un_lbl}</strong><br>'
            if reservado > 0 else ""
        )
        st.markdown(
            f'<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;'
            f'padding:.55rem .9rem;font-size:.82rem;margin:.4rem 0;line-height:1.7;">'
            f'📦 Estoque total: <strong>{qtd_br(bruto)} {un_lbl}</strong><br>'
            f'{linha_reservado}'
            f'✅ Saldo disponível para solicitar: <strong style="color:{cor_est};">{qtd_br(disp)} {un_lbl}</strong>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if disp > 0:
            qtd = st.number_input(
                f"Quantidade * ({un_lbl})",
                min_value=0.001, max_value=float(disp), value=min(1.0, float(disp)),
                step=1.0, key="sol_qtd",
            )
        else:
            st.number_input(
                f"Quantidade * ({un_lbl})",
                min_value=0.0, max_value=0.0, value=0.0, step=1.0,
                key="sol_qtd", disabled=True,
            )
            qtd = 0.0
            st.warning("⚠️ Sem saldo disponível para este produto agora (tudo já reservado ou esgotado).")
    with c2:
        setor  = st.selectbox("Setor *", sn, key="sol_setor")
        nome_s = st.text_input("Nome do solicitante *", value=u.get("nome") or u.get("nick", ""), key="sol_nome")
        obs    = st.text_area("Observação (opcional)", height=68, key="sol_obs")

    if st.button("📨 Enviar Solicitação →", type="primary", use_container_width=True, key="btn_enviar_sol"):
        if not nome_s.strip():
            st.error("Nome obrigatório.")
        elif qtd <= 0:
            st.error("Não há saldo disponível para solicitar este produto.")
        else:
            disp_agora = estoque_disponivel(prod["id"])  # revalida na hora do envio p/ evitar corrida entre usuários simultâneos
            if qtd > disp_agora:
                st.error(f"❌ Saldo insuficiente. Disponível agora: {qtd_br(disp_agora)} {un_lbl}. A tela será atualizada — tente novamente.")
                st.rerun()
            else:
                registrar_movimentacao({
                    "produto_id":            prod["id"],
                    "tipo":                  "saida",
                    "tipo_saida":            "SOLICITADA",
                    "status":                "pendente",
                    "quantidade_informada":  qtd,
                    "unidade_informada":     un_sec,
                    "quantidade_convertida": qtd,
                    "setor_solicitante":     setor,
                    "nome_solicitante":      nome_s.strip(),
                    "nick_solicitante":      u["nick"],
                    "observacao":            obs.strip() or None,
                    "usuario_solicitante":   u["id"],
                })
                st.session_state["sol_enviada_ok"] = True
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# ── Form: Solicitação de Compra ──────────────────────────────────────────────

def _form_compra(u):
    if st.session_state.get("compra_enviada_ok"):
        st.success("📨 **Solicitação Enviada.** Acompanhe o status pela aba Minhas Solicitações.")
        if st.button("➕ Nova Solicitação de Compra", type="primary"):
            del st.session_state["compra_enviada_ok"]
            st.rerun()
        return

    sets = listar_setores()
    sn   = [s["nome"] for s in sets] or ["Sem setor"]

    st.markdown('<div class="card"><div class="card-h">🛒 Solicitação de Compra</div>', unsafe_allow_html=True)
    st.info("Use este formulário para solicitar a compra de produtos que não estão no estoque.")

    with st.form("form_solicitacao_compra", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            produto_desc = st.text_input("Produto a comprar *", placeholder="Descreva o produto necessário")
            qtd_desc     = st.text_input("Quantidade estimada (opcional)", placeholder="Ex: 2 caixas, 10 unidades")
        with c2:
            setor  = st.selectbox("Setor *", sn)
            nome_s = st.text_input("Seu nome *", value=u.get("nome") or u.get("nick", ""))
            obs    = st.text_area("Justificativa / Observação (opcional)", height=68)
        enviou = st.form_submit_button("📨 Enviar Solicitação de Compra →", type="primary", use_container_width=True)

    if enviou:
        erros = []
        if not produto_desc.strip(): erros.append("Descreva o produto.")
        if not nome_s.strip():       erros.append("Nome obrigatório.")
        if erros:
            for e in erros: st.error(e)
        else:
            obs_final = obs.strip()
            if qtd_desc.strip():
                obs_final = f"Qtd estimada: {qtd_desc.strip()}" + (f" | {obs_final}" if obs_final else "")
            criar_solicitacao_compra({
                "produto_descricao": produto_desc.strip(),
                "nome_solicitante":  nome_s.strip(),
                "setor_solicitante": setor,
                "nick_solicitante":  u.get("nick", ""),
                "usuario_id":        u["id"],
                "status":            "pendente",
                "observacao":        obs_final or None,
                # Demais colunas têm DEFAULT no banco — não enviar no INSERT
            })
            st.session_state["compra_enviada_ok"] = True
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# ── Minhas Solicitações (usuário) ────────────────────────────────────────────

def _minhas(u, sc_minhas: list):
    # ── Solicitações ao almoxarifado ──────────────────────────────────────
    todas  = listar_solicitacoes()
    minhas = [s for s in todas if s.get("nick_solicitante") == u["nick"]]

    st.markdown('<div class="card"><div class="card-h">📦 Minhas Solicitações ao Almoxarifado</div>', unsafe_allow_html=True)
    if not minhas:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma solicitação.</p>', unsafe_allow_html=True)
    else:
        rows = ""
        for m in minhas:
            prod    = m.get("produto") or {}
            b       = badge(m["status"].capitalize(), m["status"])
            un_lbl  = sigla_para_opcao(m.get("unidade_informada", "UN"))
            motivo_html = ""
            if m.get("status") == "rejeitado" and m.get("motivo_rejeicao"):
                motivo_html = (f'<br><span style="font-size:.7rem;color:var(--err);">'
                               f'💬 Motivo: {esc_trunc(m["motivo_rejeicao"], 60)}</span>')
            rows += (f'<tr>'
                     f'<td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td>'
                     f'<td><strong>{esc(prod.get("nome","—"))}</strong></td>'
                     f'<td>{qtd_br(m["quantidade_informada"])} {un_lbl}</td>'
                     f'<td>{esc(m.get("setor_solicitante","—"))}</td>'
                     f'<td>{b}{motivo_html}</td>'
                     f'</tr>')
        st.markdown(
            f'<table class="tbl"><thead><tr>'
            f'<th>Data</th><th>Produto</th><th>Qtd</th><th>Setor</th><th>Status</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Minhas Solicitações de Compra ─────────────────────────────────────
    # Exibe enquanto não houver entrega confirmada pelo almoxarife
    ativas = [s for s in sc_minhas if not s.get("entrega_confirmada", False)]

    st.markdown('<div class="card"><div class="card-h">🛒 Minhas Solicitações de Compra</div>', unsafe_allow_html=True)
    if not ativas:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma solicitação de compra ativa.</p>', unsafe_allow_html=True)
    else:
        for s in ativas:
            b     = badge(s["status"].capitalize(), s["status"])
            cod   = esc(s.get("codigo_requisicao") or "—")
            prod  = esc(s["produto_descricao"])
            setor = esc(s.get("setor_solicitante", "—"))
            data  = datahora_br(s["criado_em"])

            andamento_html = ""
            if s.get("status") == "aprovado" and s.get("status_compra"):
                andamento_html = f'<br>{_badge_status_compra(s["status_compra"])}'
                if s.get("obs_compra"):
                    andamento_html += (
                        f'<br><span style="font-size:.7rem;color:var(--t3);">'
                        f'📝 {esc_trunc(s["obs_compra"], 80)}</span>'
                    )

            motivo_html = ""
            if s.get("status") == "rejeitado" and s.get("motivo_rejeicao"):
                motivo_html = (
                    f'<br><span style="font-size:.7rem;color:var(--err);">'
                    f'💬 Motivo: {esc_trunc(s["motivo_rejeicao"], 60)}</span>'
                )

            st.markdown(
                f'<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:8px;'
                f'padding:.75rem 1rem;margin:.4rem 0;font-size:.83rem;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.4rem;">'
                f'<span style="font-weight:700;">{prod}</span>'
                f'<span style="font-size:.72rem;color:var(--t3);">#{cod}</span>'
                f'</div>'
                f'<div style="color:var(--t3);font-size:.75rem;margin:.15rem 0 .3rem 0;">'
                f'{setor} &nbsp;·&nbsp; {data}'
                f'</div>'
                f'<div>{b}{andamento_html}{motivo_html}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)


# ── Aprovar / Rejeitar (almoxarife/admin) ────────────────────────────────────

def _aprovar_unificado():
    """
    Lista única e intercalada de todos os pedidos pendentes,
    ordenada por data de criação (mais antigo primeiro).
    Cada item tem um badge de tipo — 🏪 Almoxarifado ou 🛒 Compra —
    para identificação rápida.
    """
    u = sessao()

    pend_alm  = listar_solicitacoes("pendente")
    pend_comp = listar_solicitacoes_compra("pendente")

    # Normaliza almoxarifado e compra num formato comum para ordenar juntos
    itens = []
    for s in pend_alm:
        itens.append({"tipo": "almox", "criado_em": s.get("criado_em", ""), "raw": s})
    for s in pend_comp:
        itens.append({"tipo": "compra", "criado_em": s.get("criado_em", ""), "raw": s})

    # Ordena por data de criação — mais antigo no topo
    itens.sort(key=lambda x: x["criado_em"])

    st.markdown('<div class="card"><div class="card-h">🔐 Pendentes de Aprovação</div>', unsafe_allow_html=True)

    if not itens:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma solicitação pendente de aprovação.</p>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        _popup_confirmacao(u)
        return

    for item in itens:
        tipo = item["tipo"]
        s    = item["raw"]

        if tipo == "almox":
            prod   = s.get("produto") or {}
            sol    = s.get("sol")     or {}
            un_lbl = sigla_para_opcao(s.get("unidade_informada", "UN"))
            disp   = estoque_disponivel(prod.get("id", ""))
            cor_disp = "var(--ok)" if disp >= float(s["quantidade_convertida"]) else "var(--err)"

            c1, c2, c3, c4 = st.columns([4, 3, 1, 1])
            with c1:
                # Badge de tipo + nome do produto
                st.markdown(
                    f'<span style="font-size:.7rem;font-weight:600;color:var(--t3);">'
                    f'🏪 Almoxarifado</span><br>'
                    f'<strong>{esc(prod.get("nome","—"))}</strong>',
                    unsafe_allow_html=True,
                )
                st.caption(f"{sol.get('nick','—')} · {s.get('setor_solicitante','—')} · {datahora_br(s['criado_em'])}")
                if s.get("observacao"):
                    st.caption(f"Obs: {esc_trunc(s['observacao'], 60)}")
            with c2:
                st.markdown(f"**{qtd_br(s['quantidade_informada'])} {un_lbl}**")
                st.markdown(
                    f"<span style='font-size:.75rem;color:{cor_disp};'>"
                    f"Disponível: {qtd_br(disp)} {un_lbl}</span>",
                    unsafe_allow_html=True,
                )
            with c3:
                if st.button("✅", key=f"a_{s['id']}", help="Aprovar"):
                    st.session_state["conf_sol"] = {
                        "id": s["id"], "tipo": "almox", "acao": "aprovar",
                        "prod": prod.get("nome", "—"),
                        "qtd": qtd_br(s["quantidade_informada"]), "un": un_lbl,
                        "nick": sol.get("nick", ""),
                    }
                    st.rerun()
            with c4:
                if st.button("❌", key=f"r_{s['id']}", help="Rejeitar"):
                    st.session_state["conf_sol"] = {
                        "id": s["id"], "tipo": "almox", "acao": "rejeitar",
                        "prod": prod.get("nome", "—"),
                        "qtd": qtd_br(s["quantidade_informada"]), "un": un_lbl,
                        "nick": sol.get("nick", ""),
                    }
                    st.rerun()

        else:  # tipo == "compra"
            cod = s.get("codigo_requisicao") or "—"

            c1, c2, c3, c4 = st.columns([4, 3, 1, 1])
            with c1:
                # Badge de tipo + descrição do produto
                st.markdown(
                    f'<span style="font-size:.7rem;font-weight:600;color:var(--info);">'
                    f'🛒 Compra</span><br>'
                    f'<strong>{esc(s["produto_descricao"])}</strong>',
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"{s.get('nome_solicitante','—')} · "
                    f"{s.get('setor_solicitante','—')} · "
                    f"{datahora_br(s['criado_em'])}"
                )
                if s.get("observacao"):
                    st.caption(f"Obs: {esc_trunc(s['observacao'], 60)}")
            with c2:
                st.markdown(
                    f"<span style='font-size:.75rem;color:var(--t3);'>#{esc(cod)}</span>",
                    unsafe_allow_html=True,
                )
            with c3:
                if st.button("✅", key=f"sc_a_{s['id']}", help="Aprovar"):
                    st.session_state["conf_sol"] = {
                        "id": s["id"], "tipo": "compra", "acao": "aprovar",
                        "prod": s["produto_descricao"], "qtd": "", "un": "",
                        "nick": s.get("nick_solicitante", ""),
                    }
                    st.rerun()
            with c4:
                if st.button("❌", key=f"sc_r_{s['id']}", help="Rejeitar"):
                    st.session_state["conf_sol"] = {
                        "id": s["id"], "tipo": "compra", "acao": "rejeitar",
                        "prod": s["produto_descricao"], "qtd": "", "un": "",
                        "nick": s.get("nick_solicitante", ""),
                    }
                    st.rerun()

        st.markdown('<div class="div"></div>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    _popup_confirmacao(u)


# ── Compras em Andamento (almoxarife/admin) ──────────────────────────────────

def _compras_em_andamento():
    """
    Tabela de compras aprovadas com:
    - Código de requisição
    - Lista suspensa de status (4 etapas)
    - Campo de observação livre
    - Botão salvar (gera notificação ao usuário)
    - Arquivamento automático ao marcar 'Recebido' e confirmar
    """
    u = sessao()
    sc_todas  = listar_solicitacoes_compra()
    em_aberto = [s for s in sc_todas
                 if s.get("status") == "aprovado"
                 and not s.get("entrega_confirmada", False)]

    st.markdown('<div class="card"><div class="card-h">🚚 Compras em Andamento</div>', unsafe_allow_html=True)

    if not em_aberto:
        st.markdown(
            '<p style="color:var(--t3);font-size:.82rem;">Nenhuma compra aprovada em andamento.</p>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        _hist_compras_arquivadas(sc_todas)
        return

    # Cabeçalho da tabela
    hc1, hc2, hc3, hc4, hc5 = st.columns([2.5, 2, 3, 3, 1])
    for col, label in zip([hc1, hc2, hc3, hc4, hc5],
                          ["Código / Produto", "Solicitante", "Status de Andamento", "Observação", ""]):
        col.markdown(
            f"<span style='font-size:.72rem;font-weight:700;color:var(--t3);'>{label}</span>",
            unsafe_allow_html=True,
        )
    st.markdown('<div class="div" style="margin:.3rem 0;"></div>', unsafe_allow_html=True)

    for s in em_aberto:
        cod          = s.get("codigo_requisicao") or "—"
        prod         = s["produto_descricao"]
        solicit      = s.get("nome_solicitante", "—")
        setor        = s.get("setor_solicitante", "—")
        status_atual = s.get("status_compra") or STATUS_COMPRA_OPCOES[0]
        obs_atual    = s.get("obs_compra") or ""

        try:    idx = STATUS_COMPRA_OPCOES.index(status_atual)
        except: idx = 0

        c1, c2, c3, c4, c5 = st.columns([2.5, 2, 3, 3, 1])

        with c1:
            st.markdown(
                f"<span style='font-size:.72rem;color:var(--t3);'>#{esc(cod)}</span><br>"
                f"<strong style='font-size:.85rem;'>{esc(prod)}</strong>",
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"<span style='font-size:.8rem;'>{esc(solicit)}</span><br>"
                f"<span style='font-size:.72rem;color:var(--t3);'>{esc(setor)}</span>",
                unsafe_allow_html=True,
            )
        with c3:
            novo_status = st.selectbox(
                "status",
                options=STATUS_COMPRA_OPCOES,
                index=idx,
                key=f"sc_status_{s['id']}",
                label_visibility="collapsed",
            )
        with c4:
            nova_obs = st.text_input(
                "obs",
                value=obs_atual,
                placeholder="Observação livre...",
                key=f"sc_obs_{s['id']}",
                label_visibility="collapsed",
            )
        with c5:
            if st.button("💾", key=f"sc_save_{s['id']}", help="Salvar alterações"):
                status_mudou = novo_status != status_atual
                ok = atualizar_solicitacao_compra(s["id"], {
                    "status_compra":         novo_status,
                    "obs_compra":            nova_obs.strip() or None,
                    # Dispara notificação ao usuário se o status mudou
                    "notificacao_status_lida": False if status_mudou else s.get("notificacao_status_lida", True),
                })
                if ok:
                    st.toast("✅ Atualizado!" if not status_mudou else "✅ Status atualizado! Usuário será notificado.")
                    st.rerun()

        # Botão de confirmar recebimento — aparece apenas quando status = "Recebido"
        if novo_status == "Recebido" or status_atual == "Recebido":
            confirmar_key = f"sc_recebido_{s['id']}"
            if st.button(
                "📦 Confirmar Recebimento e Arquivar",
                key=confirmar_key,
                help="Marca como concluído e remove da lista de andamento",
            ):
                ok = atualizar_solicitacao_compra(s["id"], {
                    "status_compra":      "Recebido",
                    "entrega_confirmada": True,
                    "notificacao_status_lida": False,  # notifica usuário do recebimento
                })
                if ok:
                    st.success("📦 Recebimento confirmado! Item arquivado.")
                    st.rerun()

        # Botão de confirmar cancelamento — aparece apenas quando status = "Cancelado"
        if novo_status == "Cancelado" or status_atual == "Cancelado":
            cancelar_key = f"sc_cancelado_{s['id']}"
            if st.button(
                "🚫 Confirmar Cancelamento e Arquivar",
                key=cancelar_key,
                help="Marca como cancelado e remove da lista de andamento",
            ):
                ok = atualizar_solicitacao_compra(s["id"], {
                    "status_compra":      "Cancelado",
                    "entrega_confirmada": True,
                    "notificacao_status_lida": False,  # notifica usuário do cancelamento
                })
                if ok:
                    st.success("🚫 Cancelamento confirmado! Item arquivado.")
                    st.rerun()

        st.markdown('<div class="div" style="margin:.4rem 0;"></div>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    _hist_compras_arquivadas(sc_todas)


def _hist_compras_arquivadas(sc_todas: list):
    """Expander com histórico das compras já arquivadas (entrega confirmada ou canceladas)."""
    arquivadas = [s for s in sc_todas if s.get("entrega_confirmada", False)]
    with st.expander(f"📁 Histórico — Compras Finalizadas ({len(arquivadas)})"):
        if not arquivadas:
            st.info("Nenhuma compra finalizada ainda.")
            return
        rows = ""
        for s in arquivadas:
            cod  = esc(s.get("codigo_requisicao") or "—")
            aut  = (s.get("autorizador") or {}).get("nick", "—")
            obs_c = esc_trunc(s.get("obs_compra") or "—", 40)
            status_final = s.get("status_compra") or "Recebido"
            rows += (
                f'<tr>'
                f'<td style="color:var(--t3);font-size:.73rem;">{datahora_br(s["criado_em"])}</td>'
                f'<td><span style="font-size:.72rem;color:var(--t3);">#{cod}</span></td>'
                f'<td><strong>{esc(s["produto_descricao"])}</strong></td>'
                f'<td>{esc(s.get("nome_solicitante","—"))}</td>'
                f'<td>{esc(s.get("setor_solicitante","—"))}</td>'
                f'<td>{aut}</td>'
                f'<td>{obs_c}</td>'
                f'<td>{_badge_status_compra(status_final)}</td>'
                f'</tr>'
            )
        st.markdown(
            f'<table class="tbl"><thead><tr>'
            f'<th>Data</th><th>Código</th><th>Produto</th>'
            f'<th>Solicitante</th><th>Setor</th><th>Autorizador</th>'
            f'<th>Obs</th><th>Status</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True,
        )


# ── Pop-up de confirmação unificado ─────────────────────────────────────────

def _popup_confirmacao(u):
    """Pop-up para confirmar aprovação ou rejeição (almoxarifado ou compra)."""
    conf = st.session_state.get("conf_sol")
    if not conf:
        return

    acao     = conf["acao"]
    emoji    = "✅" if acao == "aprovar" else "❌"
    titulo   = "Aprovar" if acao == "aprovar" else "Rejeitar"
    cor      = "var(--ok-bg)"  if acao == "aprovar" else "var(--err-bg)"
    borda    = "rgba(22,163,74,.3)" if acao == "aprovar" else "rgba(220,38,38,.3)"
    tipo     = conf.get("tipo", "almox")
    tipo_lbl = "Solicitação de Compra" if tipo == "compra" else "Solicitação ao Almoxarifado"
    qtd_info = f"<b>Qtd:</b> {conf['qtd']} {conf['un']}<br>" if conf.get("qtd") else ""

    st.markdown(
        f'<div style="background:{cor};border:2px solid {borda};border-radius:10px;'
        f'padding:1.2rem 1.5rem;margin:1rem 0;">'
        f'<div style="font-size:1rem;font-weight:700;margin-bottom:.6rem;">'
        f'{emoji} Confirmar {titulo} — {tipo_lbl}'
        f'</div>'
        f'<div style="font-size:.85rem;color:var(--t2);line-height:1.8;">'
        f'<b>Produto:</b> {esc(conf["prod"])}<br>'
        f'{qtd_info}'
        f'<b>Solicitante:</b> {esc(conf["nick"])}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    motivo_rej = ""
    if acao == "rejeitar":
        motivo_rej = st.text_area("Motivo da rejeição * (será exibido ao solicitante)", key="motivo_rej_input")

    cs, cn, _ = st.columns([1, 1, 4])
    with cs:
        if st.button(f"{emoji} SIM, {titulo.lower()}", type="primary", use_container_width=True):
            if acao == "rejeitar" and not motivo_rej.strip():
                st.error("Informe o motivo.")
                return

            ok = False
            if tipo == "compra":
                dados = {
                    "status":                 "aprovado" if acao == "aprovar" else "rejeitado",
                    "usuario_autorizador":     u["id"],
                    "data_autorizacao":        agora_iso(),
                    "notificacao_compra_lida": False,
                }
                if acao == "aprovar":
                    dados["status_compra"]           = STATUS_COMPRA_OPCOES[0]
                    dados["notificacao_status_lida"]  = True
                if acao == "rejeitar":
                    dados["motivo_rejeicao"] = motivo_rej.strip()

                try:
                    sb = get_sb()
                    resp = sb.table("solicitacoes_compra").update(dados).eq("id", conf["id"]).execute()
                    ok = bool(resp and resp.data)
                except Exception:
                    ok = False
                    st.error("❌ Erro ao atualizar solicitação de compra. Contate o administrador.")
            else:
                dados = {
                    "status":              "aprovado" if acao == "aprovar" else "rejeitado",
                    "usuario_autorizador": u["id"],
                    "data_autorizacao":    agora_iso(),
                    "notificacao_lida":    False,
                }
                if acao == "rejeitar":
                    dados["motivo_rejeicao"] = motivo_rej.strip()

                sb = get_sb()
                resp = sb.table("movimentacoes").update(dados).eq("id", conf["id"]).execute()
                ok = bool(resp and resp.data)

            if ok:
                st.success(f"{'✅ Aprovada' if acao == 'aprovar' else '❌ Rejeitada com motivo registrado'}!")
                del st.session_state["conf_sol"]
                st.rerun()
            else:
                st.error("❌ Não foi possível atualizar. Tente novamente ou verifique os logs.")

    with cn:
        if st.button("↩ Cancelar", use_container_width=True):
            del st.session_state["conf_sol"]
            st.rerun()


# ── Histórico completo (almoxarife/admin) ────────────────────────────────────

def _hist_completo():
    """Histórico unificado: almoxarifado + compras na mesma tabela, ordenados por data."""
    todas = _listar_unificadas()

    st.markdown('<div class="card"><div class="card-h">📋 Histórico — Todas as Solicitações</div>', unsafe_allow_html=True)
    if not todas:
        st.info("Nenhuma solicitação registrada.")
    else:
        rows = ""
        for m in todas:
            origem = m.get("origem", "almox")
            b      = badge(m["status"].capitalize(), m["status"])
            data   = datahora_br(m["criado_em"])
            setor  = esc(m.get("setor_solicitante", "—"))
            solicit = esc(m.get("nome_solicitante", "—"))

            motivo_html = ""
            if m.get("status") == "rejeitado" and m.get("motivo_rejeicao"):
                motivo_html = (f'<br><span style="font-size:.7rem;color:var(--err);">'
                               f'💬 {esc_trunc(m["motivo_rejeicao"], 50)}</span>')

            if origem == "almox":
                prod   = m.get("produto") or {}
                un_lbl = sigla_para_opcao(m.get("unidade_informada", "UN"))
                tipo_badge = '<span style="font-size:.68rem;color:var(--t3);">🏪 Almox</span>'
                descricao  = f'<strong>{esc(prod.get("nome","—"))}</strong>'
                detalhe    = f'{qtd_br(m["quantidade_informada"])} {un_lbl}'
            else:
                cod        = esc(m.get("codigo_requisicao") or "—")
                sc_status  = esc(m.get("status_compra") or "—")
                tipo_badge = '<span style="font-size:.68rem;color:var(--info);">🛒 Compra</span>'
                descricao  = f'<strong>{esc(m.get("produto_descricao","—"))}</strong>'
                detalhe    = f'#{cod} · {sc_status}'

            rows += (
                f'<tr>'
                f'<td style="color:var(--t3);font-size:.73rem;">{data}</td>'
                f'<td>{tipo_badge}<br>{descricao}</td>'
                f'<td style="font-size:.78rem;color:var(--t3);">{detalhe}</td>'
                f'<td>{setor}</td>'
                f'<td>{solicit}</td>'
                f'<td>{b}{motivo_html}</td>'
                f'</tr>'
            )
        st.markdown(
            f'<table class="tbl"><thead><tr>'
            f'<th>Data</th><th>Tipo / Produto</th><th>Detalhe</th>'
            f'<th>Setor</th><th>Solicitante</th><th>Status</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
