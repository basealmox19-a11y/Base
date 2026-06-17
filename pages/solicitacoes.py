"""pages/solicitacoes.py — Solicitações ao almoxarifado + Solicitação de Compra"""
import datetime, streamlit as st
from utils.database import (listar_produtos, listar_setores, registrar_movimentacao,
    listar_solicitacoes, atualizar_movimentacao, listar_notificacoes_usuario,
    estoque_disponivel, criar_solicitacao_compra, listar_solicitacoes_compra,
    atualizar_solicitacao_compra)
from utils.auth import sessao
from utils.ui import badge
from utils.fmt import datahora_br, qtd_br, agora_iso
from utils.unidades import sigla_para_opcao
from utils.sanitize import esc, esc_trunc


# ══ TELA USUÁRIO ════════════════════════════════════════════════

def tela_solicitacoes_usuario():
    u = sessao()
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📋 Solicitações</div>'
                '<div class="pg-sub">Faça pedidos ao almoxarifado ou solicite compra de produtos</div>',
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

    t1, t2, t3 = st.tabs(["Solicitação ao Almoxarifado", "Solicitação de Compra", "Minhas Solicitações"])
    with t1: _form_solicitar(u)
    with t2: _form_compra(u)
    with t3: _minhas(u)
    st.markdown("</div>", unsafe_allow_html=True)


# ══ TELA ALMOXARIFE ══════════════════════════════════════════════

def tela_solicitacoes_almoxarife():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📋 Solicitações</div>'
                '<div class="pg-sub">Gerencie aprovações e consulte o histórico</div>',
                unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["Aprovações Pendentes", "Solicitações de Compra", "Histórico"])
    with t1: _aprovar()
    with t2: _compras_almoxarife()
    with t3: _hist_completo()
    st.markdown("</div>", unsafe_allow_html=True)


# ── Solicitação ao Almoxarifado ──────────────────────────────────

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

    pm = {p['nome']: p for p in prods}
    sn = [s["nome"] for s in sets] or ["Sem setor"]

    st.markdown('<div class="card"><div class="card-h">📝 Solicitação ao Almoxarifado</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        prod_nome = st.selectbox("Produto *", list(pm.keys()), key="sol_prod_sel")
        prod      = pm[prod_nome]
        un_sec    = prod.get("unidade_secundaria", "UN")
        un_lbl    = sigla_para_opcao(un_sec)
        disp      = estoque_disponivel(prod["id"])
        cor_est   = "var(--ok)" if disp > 0 else "var(--err)"
        st.markdown(f"""
        <div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;
                    padding:.55rem .9rem;font-size:.82rem;margin:.4rem 0;">
            📦 Saldo disponível: <strong style="color:{cor_est};">{qtd_br(disp)} {un_lbl}</strong>
        </div>
        """, unsafe_allow_html=True)
        qtd = st.number_input(f"Quantidade * ({un_lbl})", min_value=0.001, value=1.0, step=1.0, key="sol_qtd")
    with c2:
        setor  = st.selectbox("Setor *", sn, key="sol_setor")
        nome_s = st.text_input("Nome do solicitante *", value=u.get("nome") or u.get("nick",""), key="sol_nome")
        obs    = st.text_area("Observação (opcional)", height=68, key="sol_obs")

    if st.button("📨 Enviar Solicitação →", type="primary", use_container_width=True, key="btn_enviar_sol"):
        if not nome_s.strip():
            st.error("Nome obrigatório.")
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


# ── Solicitação de Compra ────────────────────────────────────────

def _form_compra(u):
    if st.session_state.get("compra_enviada_ok"):
        st.success("Solicitação Enviada. Acompanhe o status pelo aplicativo.")
        if st.button("➕ Nova Solicitação de Compra", type="primary"):
            del st.session_state["compra_enviada_ok"]
            st.rerun()
        return

    sets = listar_setores()
    sn   = [s["nome"] for s in sets] or ["Sem setor"]

    st.markdown('<div class="card"><div class="card-h">🛒 Solicitação de Compra</div>', unsafe_allow_html=True)
    st.info("Use este formulário para solicitar a compra de produtos que não estão no estoque.")

    # Usar st.form garante que todos os valores são lidos juntos ao submeter
    with st.form("form_solicitacao_compra", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            produto_desc = st.text_input("Produto a comprar *", placeholder="Descreva o produto necessário", key="sc_produto")
            qtd_desc     = st.text_input("Quantidade estimada (opcional)", placeholder="Ex: 2 caixas, 10 unidades", key="sc_qtd")
        with c2:
            setor  = st.selectbox("Setor *", sn, key="sc_setor")
            nome_s = st.text_input("Seu nome *", value=u.get("nome") or u.get("nick",""), key="sc_nome")
            obs    = st.text_area("Justificativa / Observação (opcional)", height=68, key="sc_obs")
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
                "nick_solicitante":  u.get("nick",""),
                "usuario_id":        u["id"],
                "status":            "pendente",
                "observacao":        obs_final or None,
            })
            st.session_state["compra_enviada_ok"] = True
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ── Minhas Solicitações ─────────────────────────────────────────

def _minhas(u):
    # Solicitações ao almoxarifado
    todas  = listar_solicitacoes()
    minhas = [s for s in todas if s.get("nick_solicitante") == u["nick"]]

    # Solicitações de compra
    sc_todas  = listar_solicitacoes_compra()
    sc_minhas = [s for s in sc_todas if s.get("nick_solicitante") == u["nick"]]

    st.markdown('<div class="card"><div class="card-h">📦 Minhas Solicitações ao Almoxarifado</div>', unsafe_allow_html=True)
    if not minhas:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma solicitação.</p>', unsafe_allow_html=True)
    else:
        rows = ""
        for m in minhas:
            prod   = m.get("produto") or {}
            b      = badge(m["status"].capitalize(), m["status"])
            un_lbl = sigla_para_opcao(m.get("unidade_informada","UN"))
            # Motivo de rejeição inline
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
        st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Qtd</th>'
                    f'<th>Setor</th><th>Status / Motivo</th></tr></thead><tbody>{rows}</tbody></table>',
                    unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # Solicitações de Compra
    st.markdown('<div class="card"><div class="card-h">🛒 Minhas Solicitações de Compra</div>', unsafe_allow_html=True)
    if not sc_minhas:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma solicitação de compra.</p>', unsafe_allow_html=True)
    else:
        rows = ""
        for s in sc_minhas:
            b = badge(s["status"].capitalize(), s["status"])
            motivo_html = ""
            if s.get("status") == "rejeitado" and s.get("motivo_rejeicao"):
                motivo_html = (f'<br><span style="font-size:.7rem;color:var(--err);">'
                               f'💬 Motivo: {esc_trunc(s["motivo_rejeicao"], 60)}</span>')
            rows += (f'<tr>'
                     f'<td style="color:var(--t3);font-size:.73rem;">{datahora_br(s["criado_em"])}</td>'
                     f'<td><strong>{esc(s["produto_descricao"])}</strong></td>'
                     f'<td>{esc(s.get("setor_solicitante","—"))}</td>'
                     f'<td>{b}{motivo_html}</td>'
                     f'</tr>')
        st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th>'
                    f'<th>Setor</th><th>Status / Motivo</th></tr></thead><tbody>{rows}</tbody></table>',
                    unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Aprovações (almoxarife/admin) ────────────────────────────────

def _aprovar():
    u    = sessao()
    pend = listar_solicitacoes("pendente")

    st.markdown('<div class="card"><div class="card-h">🔐 Pendentes de Aprovação — Almoxarifado</div>', unsafe_allow_html=True)
    if not pend:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma pendente.</p>', unsafe_allow_html=True)
    else:
        conf = st.session_state.get("conf_sol")
        for s in pend:
            prod   = s.get("produto") or {}
            sol    = s.get("sol")     or {}
            un_lbl = sigla_para_opcao(s.get("unidade_informada","UN"))
            disp   = estoque_disponivel(prod.get("id",""))
            c1,c2,c3,c4 = st.columns([4,3,1,1])
            with c1:
                st.markdown(f"**{esc(prod.get('nome','—'))}**", unsafe_allow_html=True)
                st.caption(f"{sol.get('nick','—')} | {s.get('setor_solicitante','—')} | {datahora_br(s['criado_em'])}")
            with c2:
                st.markdown(f"**{qtd_br(s['quantidade_informada'])} {un_lbl}**")
                cor = "var(--ok)" if disp >= float(s['quantidade_convertida']) else "var(--err)"
                st.markdown(f"<span style='font-size:.75rem;color:{cor};'>Disponível: {qtd_br(disp)} {un_lbl}</span>", unsafe_allow_html=True)
            with c3:
                if st.button("✅", key=f"a_{s['id']}", help="Aprovar"):
                    st.session_state["conf_sol"] = {"id":s["id"],"tipo":"almox","acao":"aprovar",
                        "prod":prod.get("nome","—"),"qtd":qtd_br(s["quantidade_informada"]),"un":un_lbl,"nick":sol.get("nick","")}
                    st.rerun()
            with c4:
                if st.button("❌", key=f"r_{s['id']}", help="Rejeitar"):
                    st.session_state["conf_sol"] = {"id":s["id"],"tipo":"almox","acao":"rejeitar",
                        "prod":prod.get("nome","—"),"qtd":qtd_br(s["quantidade_informada"]),"un":un_lbl,"nick":sol.get("nick","")}
                    st.rerun()
            st.markdown('<div class="div"></div>', unsafe_allow_html=True)
        _popup_confirmacao(u)
    st.markdown("</div>", unsafe_allow_html=True)


def _compras_almoxarife():
    """Aprovação de Solicitações de Compra pelo almoxarife/admin."""
    u    = sessao()
    pend = listar_solicitacoes_compra("pendente")

    st.markdown('<div class="card"><div class="card-h">🛒 Solicitações de Compra Pendentes</div>', unsafe_allow_html=True)
    if not pend:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma solicitação de compra pendente.</p>', unsafe_allow_html=True)
    else:
        conf = st.session_state.get("conf_sol")
        for s in pend:
            c1,c2,c3,c4 = st.columns([4,3,1,1])
            with c1:
                st.markdown(f"**{esc(s['produto_descricao'])}**", unsafe_allow_html=True)
                st.caption(f"{s.get('nome_solicitante','—')} | {s.get('setor_solicitante','—')} | {datahora_br(s['criado_em'])}")
                if s.get("observacao"):
                    st.caption(f"Obs: {s['observacao']}")
            with c2:
                st.markdown(f"<span style='font-size:.8rem;color:var(--info);'>🛒 Compra solicitada</span>", unsafe_allow_html=True)
            with c3:
                if st.button("✅", key=f"sc_a_{s['id']}", help="Aprovar"):
                    st.session_state["conf_sol"] = {"id":s["id"],"tipo":"compra","acao":"aprovar",
                        "prod":s["produto_descricao"],"qtd":"","un":"","nick":s.get("nick_solicitante","")}
                    st.rerun()
            with c4:
                if st.button("❌", key=f"sc_r_{s['id']}", help="Rejeitar"):
                    st.session_state["conf_sol"] = {"id":s["id"],"tipo":"compra","acao":"rejeitar",
                        "prod":s["produto_descricao"],"qtd":"","un":"","nick":s.get("nick_solicitante","")}
                    st.rerun()
            st.markdown('<div class="div"></div>', unsafe_allow_html=True)
        _popup_confirmacao(u)
    st.markdown("</div>", unsafe_allow_html=True)

    # Histórico de compras aprovadas/rejeitadas
    with st.expander("Histórico de Solicitações de Compra"):
        todas = listar_solicitacoes_compra()
        finalizadas = [s for s in todas if s["status"] != "pendente"]
        if not finalizadas:
            st.info("Nenhuma finalizada.")
        else:
            rows = ""
            for s in finalizadas:
                b = badge(s["status"].capitalize(), s["status"])
                aut = (s.get("autorizador") or {}).get("nick","—")
                rows += (f'<tr>'
                         f'<td style="color:var(--t3);font-size:.73rem;">{datahora_br(s["criado_em"])}</td>'
                         f'<td><strong>{esc(s["produto_descricao"])}</strong></td>'
                         f'<td>{esc(s.get("nome_solicitante","—"))}</td>'
                         f'<td>{esc(s.get("setor_solicitante","—"))}</td>'
                         f'<td>{aut}</td><td>{b}</td>'
                         f'</tr>')
            st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th>'
                        f'<th>Solicitante</th><th>Setor</th><th>Autorizador</th><th>Status</th>'
                        f'</tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


def _popup_confirmacao(u):
    """Pop-up unificado para aprovar/rejeitar qualquer tipo de solicitação."""
    conf = st.session_state.get("conf_sol")
    if not conf: return

    acao   = conf["acao"]
    emoji  = "✅" if acao=="aprovar" else "❌"
    titulo = "Aprovar" if acao=="aprovar" else "Rejeitar"
    cor    = "var(--ok-bg)" if acao=="aprovar" else "var(--err-bg)"
    borda  = "rgba(22,163,74,.3)" if acao=="aprovar" else "rgba(220,38,38,.3)"
    tipo   = conf.get("tipo","almox")
    tipo_lbl = "Solicitação de Compra" if tipo=="compra" else "Solicitação ao Almoxarifado"

    qtd_info = f"<b>Qtd:</b> {conf['qtd']} {conf['un']}<br>" if conf.get("qtd") else ""

    st.markdown(f"""
    <div style="background:{cor};border:2px solid {borda};border-radius:10px;
                padding:1.2rem 1.5rem;margin:1rem 0;">
        <div style="font-size:1rem;font-weight:700;margin-bottom:.6rem;">
            {emoji} Confirmar {titulo} — {tipo_lbl}
        </div>
        <div style="font-size:.85rem;color:var(--t2);line-height:1.8;">
            <b>Produto:</b> {esc(conf['prod'])}<br>
            {qtd_info}
            <b>Solicitante:</b> {esc(conf['nick'])}
        </div>
    </div>
    """, unsafe_allow_html=True)

    motivo_rej = ""
    if acao == "rejeitar":
        motivo_rej = st.text_area("Motivo da rejeição * (será exibido ao solicitante)", key="motivo_rej_input")

    cs, cn, _ = st.columns([1,1,4])
    with cs:
        if st.button(f"{emoji} SIM, {titulo.lower()}", type="primary", use_container_width=True):
            if acao == "rejeitar" and not motivo_rej.strip():
                st.error("Informe o motivo.")
                return
            if tipo == "compra":
                dados = {"status": "aprovado" if acao=="aprovar" else "rejeitado",
                         "usuario_autorizador": u["id"],
                         "data_autorizacao": agora_iso()}
                if acao == "rejeitar": dados["motivo_rejeicao"] = motivo_rej.strip()
                atualizar_solicitacao_compra(conf["id"], dados)
            else:
                upd = {"status": "aprovado" if acao=="aprovar" else "rejeitado",
                       "usuario_autorizador": u["id"],
                       "data_autorizacao": agora_iso()}
                if acao == "rejeitar": upd["motivo_rejeicao"] = motivo_rej.strip()
                try: upd["notificacao_lida"] = False
                except: pass
                atualizar_movimentacao(conf["id"], upd)
            st.success(f"{'✅ Aprovada' if acao=='aprovar' else 'Rejeitada com motivo registrado'}!")
            del st.session_state["conf_sol"]
            st.rerun()
    with cn:
        if st.button("↩ Cancelar", use_container_width=True):
            del st.session_state["conf_sol"]
            st.rerun()


# ── Histórico completo ───────────────────────────────────────────

def _hist_completo():
    todas = listar_solicitacoes()
    if not todas:
        st.info("Nenhuma solicitação.")
        return
    st.markdown('<div class="card"><div class="card-h">Histórico</div>', unsafe_allow_html=True)
    rows = ""
    for m in todas:
        prod   = m.get("produto") or {}
        b      = badge(m["status"].capitalize(), m["status"])
        un_lbl = sigla_para_opcao(m.get("unidade_informada","UN"))
        motivo_html = ""
        if m.get("status") == "rejeitado" and m.get("motivo_rejeicao"):
            motivo_html = (f'<br><span style="font-size:.7rem;color:var(--err);">'
                           f'💬 {esc_trunc(m["motivo_rejeicao"],50)}</span>')
        rows += (f'<tr>'
                 f'<td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td>'
                 f'<td><strong>{esc(prod.get("nome","—"))}</strong></td>'
                 f'<td>{qtd_br(m["quantidade_informada"])} {un_lbl}</td>'
                 f'<td>{esc(m.get("setor_solicitante","—"))}</td>'
                 f'<td>{esc(m.get("nome_solicitante","—"))}</td>'
                 f'<td>{b}{motivo_html}</td>'
                 f'</tr>')
    st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Qtd</th>'
                f'<th>Setor</th><th>Solicitante</th><th>Status</th>'
                f'</tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
