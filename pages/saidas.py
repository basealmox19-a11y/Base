"""pages/saidas.py — Saída Manual com saldo em tempo real"""
import datetime, streamlit as st
from utils.database import (listar_produtos, listar_setores, registrar_movimentacao,
    listar_solicitacoes, atualizar_movimentacao, buscar_produto_por_id,
    listar_movimentacoes, estoque_disponivel, listar_solicitacoes_compra,
    atualizar_solicitacao_compra, criar_solicitacao_compra)
from utils.auth import sessao, is_admin
from utils.ui import badge
from utils.fmt import datahora_br, qtd_br, agora_iso
from utils.unidades import sigla_para_opcao, SIGLAS, OPCOES, opcao_para_sigla
from utils.sanitize import esc, esc_trunc

def _u(label, val="UN", key=None):
    idx = SIGLAS.index(val) if val in SIGLAS else 0
    kw = {"key": key} if key else {}
    return opcao_para_sigla(st.selectbox(label, OPCOES, index=idx, **kw))


# ══ SOLICITAÇÕES (admin) ══════════════════════════════════════════

def tela_solicitacoes():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📋 Solicitações</div>'
                '<div class="pg-sub">Gerencie todas as solicitações</div>', unsafe_allow_html=True)
    tl = st.tabs(["Solicitação ao Almoxarifado","Aprovar / Rejeitar","Solicitação de Compra","Histórico"])
    with tl[0]: _form_sol()
    with tl[1]: _aprovar()
    with tl[2]: _compras_admin()
    with tl[3]: _hist_sol()
    st.markdown("</div>", unsafe_allow_html=True)


def _form_sol():
    u = sessao(); prods = listar_produtos(); sets = listar_setores()
    if not prods: st.warning("Nenhum produto cadastrado."); return
    pm = {p["nome"]: p for p in prods}; sn = [s["nome"] for s in sets] or ["Sem setor"]
    if st.session_state.get("sol_admin_ok"):
        st.success("📨 **Solicitação Enviada.** O retorno de aprovação será dado no seu aplicativo.")
        if st.button("➕ Nova", type="primary"):
            del st.session_state["sol_admin_ok"]; st.session_state.pop("adm_prod_sel",None); st.rerun()
        return
    st.markdown('<div class="card"><div class="card-h">📝 Solicitação ao Almoxarifado</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        pnome = st.selectbox("Produto *", list(pm.keys()), key="adm_prod_sel"); prod = pm[pnome]
        un_sec = prod.get("unidade_secundaria","UN"); un_lbl = sigla_para_opcao(un_sec)
        disp = estoque_disponivel(prod["id"]); cor = "var(--ok)" if disp>0 else "var(--err)"
        st.markdown(f'<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;padding:.55rem .9rem;font-size:.82rem;margin:.4rem 0;">📦 Saldo disponível: <strong style="color:{cor};">{qtd_br(disp)} {un_lbl}</strong></div>', unsafe_allow_html=True)
        qtd = st.number_input(f"Qtd * ({un_lbl})", min_value=0.001, value=1.0, step=1.0, key="adm_qtd")
    with c2:
        setor = st.selectbox("Setor *", sn, key="adm_setor")
        nome_s = st.text_input("Solicitante *", value=u.get("nome") or u.get("nick",""), key="adm_nome")
        obs = st.text_area("Obs", height=68, key="adm_obs")
    if st.button("📨 Enviar →", type="primary", use_container_width=True, key="btn_adm_sol"):
        if not nome_s.strip(): st.error("Nome obrigatório.")
        else:
            registrar_movimentacao({"produto_id":prod["id"],"tipo":"saida","tipo_saida":"SOLICITADA",
                "status":"pendente","quantidade_informada":qtd,"unidade_informada":un_sec,
                "quantidade_convertida":qtd,"setor_solicitante":setor,"nome_solicitante":nome_s.strip(),
                "nick_solicitante":u["nick"],"observacao":obs.strip() or None,"usuario_solicitante":u["id"]})
            st.session_state["sol_admin_ok"] = True; st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _aprovar():
    u = sessao(); pend = listar_solicitacoes("pendente")
    st.markdown('<div class="card"><div class="card-h">🔐 Pendentes de Aprovação</div>', unsafe_allow_html=True)
    if not pend:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma pendente.</p>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True); return
    conf = st.session_state.get("conf_sol_adm")
    for s in pend:
        prod = s.get("produto") or {}; sol = s.get("sol") or {}
        un_lbl = sigla_para_opcao(s.get("unidade_informada","UN"))
        disp = estoque_disponivel(prod.get("id",""))
        c1,c2,c3,c4 = st.columns([4,3,1,1])
        with c1:
            st.markdown(f"**{prod.get('nome','—')}**")
            st.caption(f"{sol.get('nick','—')} | {s.get('setor_solicitante','—')} | {datahora_br(s['criado_em'])}")
        with c2:
            st.markdown(f"**{qtd_br(s['quantidade_informada'])} {un_lbl}**")
            cor = "var(--ok)" if disp>=float(s['quantidade_convertida']) else "var(--err)"
            st.markdown(f"<span style='font-size:.75rem;color:{cor};'>Disp: {qtd_br(disp)} {un_lbl}</span>", unsafe_allow_html=True)
        with c3:
            if st.button("✅", key=f"aa_{s['id']}"):
                st.session_state["conf_sol_adm"] = {"id":s["id"],"acao":"aprovar","prod":prod.get("nome","—"),"qtd":qtd_br(s["quantidade_informada"]),"un":un_lbl,"nick":sol.get("nick","")}; st.rerun()
        with c4:
            if st.button("❌", key=f"ra_{s['id']}"):
                st.session_state["conf_sol_adm"] = {"id":s["id"],"acao":"rejeitar","prod":prod.get("nome","—"),"qtd":qtd_br(s["quantidade_informada"]),"un":un_lbl,"nick":sol.get("nick","")}; st.rerun()
        st.markdown('<div class="div"></div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    if conf:
        acao = conf["acao"]; emoji = "✅" if acao=="aprovar" else "❌"; titulo = "Aprovar" if acao=="aprovar" else "Rejeitar"
        cor = "var(--ok-bg)" if acao=="aprovar" else "var(--err-bg)"; borda = "rgba(22,163,74,.3)" if acao=="aprovar" else "rgba(220,38,38,.3)"
        st.markdown(f'<div style="background:{cor};border:2px solid {borda};border-radius:10px;padding:1.2rem 1.5rem;margin:1rem 0;"><div style="font-size:1rem;font-weight:700;margin-bottom:.6rem;">{emoji} Confirmar {titulo}</div><div style="font-size:.85rem;color:var(--t2);line-height:1.8;"><b>Produto:</b> {esc(conf["prod"])}<br><b>Qtd:</b> {conf["qtd"]} {conf["un"]}<br><b>Solicitante:</b> {conf["nick"]}</div></div>', unsafe_allow_html=True)
        motivo_rej = ""
        if acao == "rejeitar": motivo_rej = st.text_area("Motivo da rejeição *", key="mrej_adm")
        cs, cn, _ = st.columns([1,1,4])
        with cs:
            if st.button(f"{emoji} SIM, {titulo.lower()}", type="primary", use_container_width=True):
                if acao=="rejeitar" and not motivo_rej.strip(): st.error("Informe o motivo.")
                else:
                    if acao=="aprovar":
                        upd = {"status":"aprovado","usuario_autorizador":u["id"],"data_autorizacao":agora_iso()}
                        try: upd["notificacao_lida"] = False
                        except: pass
                        atualizar_movimentacao(conf["id"], upd); st.success("✅ Aprovada!")
                    else:
                        atualizar_movimentacao(conf["id"],{"status":"rejeitado","motivo_rejeicao":motivo_rej.strip()}); st.success("Rejeitada.")
                    del st.session_state["conf_sol_adm"]; st.rerun()
        with cn:
            if st.button("↩ Cancelar", use_container_width=True):
                del st.session_state["conf_sol_adm"]; st.rerun()


def _hist_sol():
    todas = listar_solicitacoes()
    if not todas: st.info("Nenhuma."); return
    st.markdown('<div class="card">', unsafe_allow_html=True)
    rows = ""
    for m in todas:
        prod = m.get("produto") or {}; b = badge(m["status"].capitalize(), m["status"])
        un_lbl = sigla_para_opcao(m.get("unidade_informada","UN")); aut = (m.get("aut") or {}).get("nick","—")
        rows += (f'<tr><td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td>'
                 f'<td><strong>{esc(prod.get("nome","—"))}</strong></td>'
                 f'<td>{qtd_br(m["quantidade_informada"])} {un_lbl}</td>'
                 f'<td>{esc(m.get("setor_solicitante","—"))}</td>'
                 f'<td>{esc(m.get("nome_solicitante","—"))}</td>'
                 f'<td>{esc(aut)}</td><td>{b}</td></tr>')
    st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Qtd</th><th>Setor</th><th>Solicitante</th><th>Aprovador</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ══ SAÍDA MANUAL ══════════════════════════════════════════════════


def _compras_admin():
    """Solicitações de Compra para o perfil admin."""
    u    = sessao()
    sets = listar_setores()
    sn   = [s["nome"] for s in sets] or ["Sem setor"]

    # Formulário de nova solicitação de compra
    if not st.session_state.get("compra_admin_ok"):
        st.markdown('<div class="card"><div class="card-h">🛒 Nova Solicitação de Compra</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            produto_desc = st.text_input("Produto a comprar *", placeholder="Descreva o produto", key="ca_produto")
            qtd_desc     = st.text_input("Quantidade estimada (opcional)", key="ca_qtd")
        with c2:
            setor  = st.selectbox("Setor *", sn, key="ca_setor")
            nome_s = st.text_input("Solicitante *", value=u.get("nome") or u.get("nick",""), key="ca_nome")
            obs    = st.text_area("Justificativa (opcional)", height=68, key="ca_obs")
        if st.button("📨 Enviar Solicitação de Compra →", type="primary", use_container_width=True, key="btn_ca"):
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
                    "nick_solicitante":  u["nick"],
                    "usuario_id":        u["id"],
                    "status":            "pendente",
                    "observacao":        obs_final or None,
                })
                st.session_state["compra_admin_ok"] = True
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.success("Solicitação Enviada. Acompanhe o status pelo aplicativo.")
        if st.button("➕ Nova Solicitação de Compra", type="primary"):
            del st.session_state["compra_admin_ok"]; st.rerun()

    # Aprovações pendentes de compra
    pend = listar_solicitacoes_compra("pendente")
    if pend:
        st.markdown('<div class="card"><div class="card-h">🔐 Compras Pendentes de Aprovação</div>', unsafe_allow_html=True)
        for s in pend:
            c1,c2,c3,c4 = st.columns([4,3,1,1])
            with c1:
                st.markdown(f"**{esc(s['produto_descricao'])}**", unsafe_allow_html=True)
                st.caption(f"{s.get('nome_solicitante','—')} | {s.get('setor_solicitante','—')} | {datahora_br(s['criado_em'])}")
            with c2:
                st.markdown("<span style='font-size:.8rem;color:var(--info);'> 🛒 Compra solicitada</span>", unsafe_allow_html=True)
            with c3:
                if st.button("✅", key=f"ca_a_{s['id']}"):
                    atualizar_solicitacao_compra(s["id"],{"status":"aprovado","usuario_autorizador":u["id"],"data_autorizacao":agora_iso()})
                    st.success("Aprovada!"); st.rerun()
            with c4:
                if st.button("❌", key=f"ca_r_{s['id']}"):
                    st.session_state[f"rej_compra_{s['id']}"] = True; st.rerun()
            if st.session_state.get(f"rej_compra_{s['id']}"):
                motivo = st.text_area("Motivo da rejeição *", key=f"mot_{s['id']}")
                csa, cna = st.columns(2)
                with csa:
                    if st.button("Confirmar rejeição", key=f"conf_rej_{s['id']}", type="primary"):
                        if not motivo.strip(): st.error("Informe o motivo.")
                        else:
                            atualizar_solicitacao_compra(s["id"],{"status":"rejeitado","motivo_rejeicao":motivo.strip(),"usuario_autorizador":u["id"],"data_autorizacao":agora_iso()})
                            st.session_state.pop(f"rej_compra_{s['id']}", None); st.rerun()
                with cna:
                    if st.button("Cancelar", key=f"canc_{s['id']}"):
                        st.session_state.pop(f"rej_compra_{s['id']}", None); st.rerun()
            st.markdown('<div class="div"></div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Histórico completo de compras
    with st.expander("📋 Histórico de Solicitações de Compra"):
        todas = listar_solicitacoes_compra()
        if not todas: st.info("Nenhuma registrada.")
        else:
            rows = ""
            for s in todas:
                from utils.ui import badge as _badge
                b = _badge(s["status"].capitalize(), s["status"])
                motivo_html = ""
                if s.get("status")=="rejeitado" and s.get("motivo_rejeicao"):
                    from utils.sanitize import esc_trunc
                    motivo_html = f'<br><span style="font-size:.7rem;color:var(--err);">💬 {esc_trunc(s["motivo_rejeicao"],50)}</span>'
                rows += (f'<tr>'
                         f'<td style="color:var(--t3);font-size:.73rem;">{datahora_br(s["criado_em"])}</td>'
                         f'<td><strong>{esc(s["produto_descricao"])}</strong></td>'
                         f'<td>{esc(s.get("nome_solicitante","—"))}</td>'
                         f'<td>{esc(s.get("setor_solicitante","—"))}</td>'
                         f'<td>{b}{motivo_html}</td>'
                         f'</tr>')
            st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Solicitante</th><th>Setor</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


def tela_saida_manual():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📤 Saída Manual</div><div class="pg-sub">Saída direta sem aprovação prévia</div>', unsafe_allow_html=True)
    t1, t2 = st.tabs(["Executar","Histórico"])
    with t1: _form_manual()
    with t2: _tbl(listar_movimentacoes(tipo="saida", tipo_saida="MANUAL"))
    st.markdown("</div>", unsafe_allow_html=True)


def _form_manual():
    u = sessao(); prods = listar_produtos(); sets = listar_setores()
    if not prods: st.warning("Nenhum produto cadastrado."); return
    pm = {f"{p['nome']} ({p['codigo_interno']})": p for p in prods}
    sn = [s["nome"] for s in sets] or ["Sem setor"]

    # Tela de sucesso
    if st.session_state.get("saida_ok"):
        info = st.session_state["saida_ok"]
        st.markdown(f'<div style="background:var(--ok-bg);border:2px solid rgba(22,163,74,.3);border-radius:12px;padding:2rem;text-align:center;margin:1rem 0;"><div style="font-size:2.5rem;margin-bottom:.5rem;">✅</div><div style="font-size:1.2rem;font-weight:700;color:var(--ok);margin-bottom:.5rem;">Saída Registrada com Sucesso!</div><div style="font-size:.85rem;color:var(--t2);margin-bottom:.3rem;"><strong>{qtd_br(info["qtd"])} {sigla_para_opcao(info["un"])}</strong> de <strong>{info["produto"]}</strong></div><div style="font-size:.8rem;color:var(--t3);">Setor: {info["setor"]} &nbsp;|&nbsp; Retirante: {info["retirante"]} &nbsp;|&nbsp; Por: <strong>{u.get("nick","")}</strong></div></div>', unsafe_allow_html=True)
        if st.button("➕ Realizar Nova Saída", type="primary"):
            del st.session_state["saida_ok"]; st.session_state.pop("confirmar_saida",None)
            st.session_state.pop("man_prod_sel",None); st.rerun()
        return

    # Confirmação
    if st.session_state.get("confirmar_saida"):
        d = st.session_state["confirmar_saida"]; prod = d["prod"]; un_lbl = sigla_para_opcao(d["ui"])
        st.markdown(f'<div style="background:var(--warn-bg);border:2px solid rgba(217,119,6,.35);border-radius:10px;padding:1.4rem 1.6rem;margin:1rem 0;"><div style="font-size:1rem;font-weight:700;color:var(--warn);margin-bottom:.8rem;">⚠️ Confirmar Saída</div><div style="font-size:.85rem;color:var(--t2);line-height:1.8;"><b>Produto:</b> {esc(prod["nome"])}<br><b>Quantidade:</b> {qtd_br(d["qtd"])} {un_lbl}<br><b>Setor:</b> {d["setor"]}<br><b>Retirante:</b> {d["nome_r"]}<br><b>Motivo:</b> {d["motivo"]}</div></div>', unsafe_allow_html=True)
        cs, cn, _ = st.columns([1,1,3])
        with cs:
            if st.button("✅ SIM, confirmar", type="primary", use_container_width=True):
                registrar_movimentacao({"produto_id":prod["id"],"tipo":"saida","tipo_saida":"MANUAL",
                    "status":"concluido","quantidade_informada":d["qtd"],"unidade_informada":d["ui"],
                    "quantidade_convertida":d["qtd"],"setor_solicitante":d["setor"],
                    "nome_solicitante":d["nome_r"],"nick_solicitante":u["nick"],
                    "motivo_saida":d["motivo"],"usuario_executor":u["id"],"data_movimentacao":agora_iso()})
                st.session_state["saida_ok"] = {"qtd":d["qtd"],"un":d["ui"],"produto":prod["nome"],"setor":d["setor"],"retirante":d["nome_r"]}
                del st.session_state["confirmar_saida"]; st.rerun()
        with cn:
            if st.button("❌ NÃO, voltar", use_container_width=True):
                del st.session_state["confirmar_saida"]; st.rerun()
        return

    # Formulário com saldo em tempo real
    st.markdown('<div class="card"><div class="card-h">⚡ Saída Direta</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        # Selectbox FORA do form para saldo em tempo real
        sel  = st.selectbox("Produto *", list(pm.keys()), key="man_prod_sel")
        prod = pm[sel]
        un_sec = prod.get("unidade_secundaria","UN"); un_lbl = sigla_para_opcao(un_sec)
        est = float(prod["quantidade_total_secundaria"])
        qtd = st.number_input("Qtd *", min_value=0.001, value=1.0, step=1.0, key="man_qtd")
        cor = "var(--ok)" if est >= qtd else "var(--err)"
        st.markdown(f'<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;padding:.55rem .9rem;font-size:.79rem;margin:.3rem 0;">Saldo: <strong style="color:{cor};">{qtd_br(est)} {un_lbl}</strong>{"&nbsp;⚠️ <span style=color:var(--err)>Insuficiente</span>" if est<qtd else ""}</div>', unsafe_allow_html=True)
    with c2:
        setor  = st.selectbox("Setor *", sn, key="man_setor")
        nome_r = st.text_input("Retirante *", key="man_retirant")
        motivo = st.text_area("Motivo *", height=68, key="man_motivo")

    if st.button("Registrar Saída →", type="primary", use_container_width=True, key="btn_man_saida"):
        erros = []
        if not nome_r.strip(): erros.append("Nome obrigatório.")
        if not motivo.strip(): erros.append("Motivo obrigatório.")
        if est < qtd:          erros.append("Estoque insuficiente.")
        if erros:
            for e in erros: st.error(e)
        else:
            st.session_state["confirmar_saida"] = {"prod":prod,"qtd":qtd,"ui":un_sec,"setor":setor,"nome_r":nome_r.strip(),"motivo":motivo.strip()}
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ══ SAÍDA APROVADA ════════════════════════════════════════════════

def tela_saida_aprovada():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">✅ Saída Aprovada</div><div class="pg-sub">Execute baixas de solicitações aprovadas</div>', unsafe_allow_html=True)
    u = sessao(); aprov = listar_solicitacoes("aprovado")
    st.markdown('<div class="card"><div class="card-h">📋 Aguardando Execução</div>', unsafe_allow_html=True)
    if not aprov:
        st.markdown('<p style="color:var(--t3);font-size:.82rem;">Nenhuma saída aprovada pendente.</p>', unsafe_allow_html=True)
    else:
        for s in aprov:
            prod = s.get("produto") or {}; autor = s.get("aut") or {}
            un_lbl = sigla_para_opcao(s.get("unidade_informada","UN"))
            c1, c2, c3 = st.columns([4,3,2])
            with c1:
                st.markdown(f"**{prod.get('nome','—')}**")
                st.caption(f"Setor: {s.get('setor_solicitante','—')} | Retirante: {s.get('nome_solicitante','—')}")
                aprovador = autor.get("nick","—") or autor.get("nome","—")
                st.caption(f"✅ Aprovado por: **{aprovador}** em {datahora_br(s.get('data_autorizacao'))}")
            with c2: st.markdown(f"**{qtd_br(s['quantidade_informada'])} {un_lbl}**")
            with c3:
                if st.button("⬇️ Executar", key=f"ex_{s['id']}", type="primary", use_container_width=True):
                    p = buscar_produto_por_id(prod.get("id",""))
                    if p and float(p["quantidade_total_secundaria"]) >= float(s["quantidade_convertida"]):
                        atualizar_movimentacao(s["id"],{"status":"concluido","usuario_executor":u["id"],"data_movimentacao":agora_iso()})
                        st.success("✅ Baixa executada!"); st.rerun()
                    else: st.error("Estoque insuficiente.")
            st.markdown('<div class="div"></div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    with st.expander("Histórico de saídas aprovadas"):
        conc = listar_solicitacoes("concluido")
        if not conc: st.info("Nenhum.")
        else:
            rows = ""
            for m in conc:
                prod = m.get("produto") or {}; un_lbl = sigla_para_opcao(m.get("unidade_informada","UN"))
                aut = (m.get("aut") or {}).get("nick","—"); exe = (m.get("exe") or {}).get("nick","—")
                rows += (f'<tr><td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td>'
                         f'<td><strong>{esc(prod.get("nome","—"))}</strong></td>'
                         f'<td>{qtd_br(m["quantidade_informada"])} {un_lbl}</td>'
                         f'<td>{esc(m.get("setor_solicitante","—"))}</td>'
                         f'<td>{esc(m.get("nome_solicitante","—"))}</td>'
                         f'<td style="color:var(--ok);">{aut}</td>'
                         f'<td style="color:var(--info);">{exe}</td></tr>')
            st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Qtd</th><th>Setor</th><th>Retirante</th><th>Aprovador</th><th>Executor</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _tbl(movs):
    if not movs: st.info("Nenhum registro."); return
    st.markdown('<div class="card">', unsafe_allow_html=True)
    rows = ""
    for m in movs:
        prod = m.get("produto") or {}; b = badge(m["status"].capitalize(), m["status"])
        un_lbl = sigla_para_opcao(m.get("unidade_informada","UN"))
        rows += (f'<tr><td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td>'
                 f'<td><strong>{esc(prod.get("nome","—"))}</strong></td>'
                 f'<td>{qtd_br(m["quantidade_informada"])} {un_lbl}</td>'
                 f'<td>{esc(m.get("setor_solicitante","—"))}</td>'
                 f'<td>{esc(m.get("nome_solicitante","—"))}</td>'
                 f'<td>{b}</td></tr>')
    st.markdown(f'<table class="tbl"><thead><tr><th>Data</th><th>Produto</th><th>Qtd</th><th>Setor</th><th>Solicitante</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
