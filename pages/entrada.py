"""pages/entrada.py — Entrada com Reabastecimento, CNR obrigatório e sucesso visual"""
import streamlit as st
from utils.database import (buscar_produto_por_ean, buscar_produtos_por_nome,
    criar_produto, registrar_movimentacao, criar_documento,
    upload_pdf, listar_categorias, listar_movimentacoes, buscar_produto_por_id,
    listar_produtos, atualizar_produto)
from utils.auth import sessao
from utils.ui import badge
from utils.fmt import datahora_br, qtd_br, agora_iso
from utils.unidades import SIGLAS, OPCOES, sigla_para_opcao, opcao_para_sigla
from utils.sanitize import esc, esc_trunc

TIPOS = ["Nota Fiscal","FL","Entrada Interna","Ajuste Manual"]

def _u(label, val="UN", key=None):
    idx = SIGLAS.index(val) if val in SIGLAS else 0
    kw = {"key": key} if key else {}
    return opcao_para_sigla(st.selectbox(label, OPCOES, index=idx, **kw))

def tela_entrada():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📥 Entrada de Produtos</div>'
                '<div class="pg-sub">Registre entradas, reabastecimentos ou cadastre novos produtos</div>',
                unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["Nova Entrada","♻️ Reabastecimento de Estoque","Histórico"])
    with t1: _nova_entrada()
    with t2: _reabastecimento()
    with t3: _hist()
    st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# NOVA ENTRADA (busca por EAN/nome + cadastro de produto)
# ══════════════════════════════════════════════════════════════════

def _nova_entrada():
    u    = sessao()
    cats = listar_categorias()
    cm   = {c["nome"]: c["id"] for c in cats}
    prod = st.session_state.get("ps")

    # Tela de sucesso
    if st.session_state.get("entrada_ok"):
        st.success("✅ Entrada Registrada com Sucesso.")
        if st.button("➕ Nova Entrada", type="primary", key="btn_nova_ent"):
            del st.session_state["entrada_ok"]
            st.session_state.pop("ps", None)
            st.session_state.pop("en", None)
            st.rerun()
        return

    # Busca
    st.markdown('<div class="card"><div class="card-h">🔍 Identificar Produto</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([3,1,1])
    with c1: termo = st.text_input("Codigo do produto ou nome", placeholder="Bipe ou digite", key="eb")
    with c2:
        st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
        be = st.button("Buscar EAN ou código", use_container_width=True)
    with c3:
        st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
        bn = st.button("Buscar Nome", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if be and termo.strip():
        p = buscar_produto_por_ean(termo.strip())
        if p:
            st.session_state["ps"] = p; st.session_state.pop("en", None); prod = p
            st.success(f"✅ {p['nome']} — {p['codigo_interno']}")
        else:
            st.warning("Código não encontrado. Cadastre o produto abaixo.")
            st.session_state.pop("ps", None); st.session_state["en"] = termo.strip()

    if bn and termo.strip():
        res = buscar_produtos_por_nome(termo.strip())
        if res:
            opts = {f"{r['nome']} ({r['codigo_interno']})": r for r in res}
            sel  = st.selectbox("Selecione", list(opts.keys()), key="snr")
            if st.button("Usar este produto →"):
                st.session_state["ps"] = opts[sel]; st.session_state.pop("en", None); st.rerun()
        else:
            st.warning("Não encontrado.")
            st.session_state.pop("ps", None)

    # Produto encontrado — formulário de entrada
    if prod:
        _form_entrada(prod, u, cm)
        return

    # Cadastrar Produto (com EAN opcional)
    with st.expander("➕ Cadastrar Produto"):
        with st.form("fnp"):
            st.markdown('<div style="font-size:.78rem;color:var(--t3);margin-bottom:.5rem;">'
                        'O EAN é opcional mas facilita buscas futuras.</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                nm    = st.text_input("Nome do produto *")
                cat   = st.selectbox("Categoria", list(cm.keys()))
                up_n  = _u("Unidade primária (Como você está recebendo? Em caixa? Paletizado?...)", val="CX", key="upn")
                us_n  = _u("Unidade secundária (Como as áreas vão consumir? Unidades? A caixa completa?)", val="UN", key="usn")
            with c2:
                fat_n = st.number_input("Fator de Conversão (1 primária = ? secundárias)", value=1.0, min_value=0.001, step=1.0)
                em_n  = st.number_input("Estoque mínimo (unidade primária)", value=0.0, min_value=0.0)
                ean_n = st.text_input("EAN ou Código SFC (Opcional)",
                                       value=st.session_state.get("en",""),
                                       placeholder="Deixe em branco se não tiver")
            desc_n = st.text_area("Descrição (opcional)", height=60)
            if st.form_submit_button("Cadastrar Produto →", type="primary", use_container_width=True):
                if not nm.strip():
                    st.error("Nome obrigatório.")
                else:
                    d = {"nome": nm.strip(), "categoria_id": cm.get(cat),
                         "unidade_primaria": up_n, "unidade_secundaria": us_n,
                         "fator_conversao": fat_n, "estoque_minimo_primario": em_n,
                         "descricao": desc_n.strip() or None}
                    if ean_n.strip(): d["ean"] = ean_n.strip()
                    novo = criar_produto(d)
                    st.session_state["ps"] = novo
                    st.session_state.pop("en", None)
                    st.success(f"✅ Produto **{novo['nome']}** cadastrado — {novo['codigo_interno']}")
                    st.rerun()


def _form_entrada(prod, u, cm):
    """Formulário de registro de entrada para produto já localizado."""
    est    = float(prod.get("quantidade_total_secundaria", 0))
    fat    = float(prod.get("fator_conversao", 1))
    up     = prod.get("unidade_primaria", "UN")
    us     = prod.get("unidade_secundaria", "UN")
    up_lbl = sigla_para_opcao(up)
    us_lbl = sigla_para_opcao(us)

    st.markdown(f"""
    <div style="background:var(--ok-bg);border:1px solid rgba(22,163,74,.25);
                border-radius:8px;padding:.8rem 1.1rem;margin:.5rem 0;font-size:.84rem;">
        ✅ <strong>{prod['nome']}</strong>
        &nbsp;<span class="mono" style="color:var(--t3);">{prod['codigo_interno']}</span>
        {" &nbsp;|&nbsp; EAN: "+prod['ean'] if prod.get("ean") else ""}
        &nbsp;|&nbsp; Estoque: <strong style="color:var(--ok);">{qtd_br(est)} {us_lbl}</strong>
        <span style="color:var(--t3);font-size:.75rem;"> (= {qtd_br(est/fat if fat else 0)} {up_lbl})</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="card-h">📥 Registrar Entrada</div>', unsafe_allow_html=True)

    # Tipo de entrada fora do form para condicionar campos obrigatórios
    te = st.selectbox("Tipo de entrada *", TIPOS, key="te_nova")

    with st.form("fer"):
        c1, c2 = st.columns(2)
        with c1:
            qtd = st.number_input("Quantidade *", min_value=0.001, value=1.0, step=1.0)
            ui  = _u("Unidade informada", val=up, key="ui_ent")
        with c2:
            # NF: campos obrigatórios
            nfn  = st.text_input("Número NF" + (" *" if te=="Nota Fiscal" else " (opcional)"),
                                  placeholder="Ex: 001234")
            cnr  = st.text_input("Número CNR / Pedido" + (" *" if te=="Nota Fiscal" else " (opcional)"),
                                  placeholder="Ex: CNR-2025-001",
                                  help="Preenchido automaticamente no e-mail da NF")
            forn = st.text_input("Fornecedor" + (" *" if te=="Nota Fiscal" else " (opcional)"),
                                  placeholder="Ex: Distribuidora ABC Ltda")
            obs  = st.text_area("Observação", height=50)

        qc     = qtd * fat
        ui_lbl = sigla_para_opcao(ui)

        aviso_unidade = ""
        if ui != up:
            aviso_unidade = f"""
            <div style="background:var(--warn-bg);border:1px solid rgba(217,119,6,.3);
                        border-radius:7px;padding:.55rem .9rem;margin:.4rem 0;font-size:.78rem;
                        color:var(--warn);">
                ⚠️ Unidade informada (<strong>{ui_lbl}</strong>) é diferente da cadastrada
                (<strong>{up_lbl}</strong>). Ao confirmar, o cadastro do produto será
                atualizado para <strong>{ui_lbl}</strong>.
            </div>
            """

        st.markdown(f"""
        <div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;
                    padding:.65rem .9rem;margin:.4rem 0;font-size:.8rem;">
            📦 <strong>{qtd_br(qtd)} {ui_lbl}</strong>
            <span style="color:var(--t3);"> = </span>
            <strong style="color:var(--red);">{qtd_br(qc)} {us_lbl}</strong>
            <span style="color:var(--t3);"> serão adicionados ao estoque</span>
        </div>
        {aviso_unidade}
        """, unsafe_allow_html=True)

        # PDF upload removido — envio por e-mail é feito via Outlook

        if st.form_submit_button("✅ Confirmar Entrada", type="primary", use_container_width=True):
            erros = []
            if te == "Nota Fiscal":
                if not nfn.strip():  erros.append("Número da NF obrigatório para Nota Fiscal.")
                if not forn.strip(): erros.append("Fornecedor obrigatório para Nota Fiscal.")
                if not cnr.strip():  erros.append("Número do Pedido/CNR obrigatório para Nota Fiscal.")
            if erros:
                for e in erros: st.error(e)
            else:
                # Inclui CNR na observação
                obs_final = obs.strip()
                if cnr.strip():
                    obs_final = f"CNR: {cnr.strip()}" + (f" | {obs_final}" if obs_final else "")

                # NF sem PDF — registra mas não cria pendência de upload
                registrar_movimentacao({
                    "produto_id":            prod["id"],
                    "tipo":                  "entrada",
                    "tipo_entrada":          te,
                    "status":                "concluido",
                    "quantidade_informada":  qtd,
                    "unidade_informada":     ui,
                    "quantidade_convertida": qc,
                    "envio_financeiro":      True,  # não cria pendência de envio
                    "fornecedor":            forn.strip() or None,
                    "numero_nf":             nfn.strip() or None,
                    "observacao":            obs_final or None,
                    "usuario_executor":      u["id"],
                    "data_movimentacao":     agora_iso(),
                })

                # Se a unidade informada na entrada for diferente da cadastrada no
                # produto, atualiza o cadastro para manter o saldo/unidade consistentes
                if ui != up:
                    atualizar_produto(prod["id"], {"unidade_primaria": ui})

                st.session_state["entrada_ok"] = True

                p_novo = buscar_produto_por_id(prod["id"])
                if p_novo: st.session_state["ps"] = p_novo
                st.rerun()

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 Buscar outro produto", use_container_width=True):
            for k in ["ps","en"]: st.session_state.pop(k, None)
            st.rerun()
    with col_b:
        if st.button("➕ Nova entrada deste produto", use_container_width=True):
            p_novo = buscar_produto_por_id(prod["id"])
            if p_novo: st.session_state["ps"] = p_novo
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# REABASTECIMENTO DE ESTOQUE
# ══════════════════════════════════════════════════════════════════

def _reabastecimento():
    u     = sessao()
    cats  = listar_categorias()
    cm    = {c["nome"]: c["id"] for c in cats}
    prods = listar_produtos()

    if not prods:
        st.info("Nenhum produto cadastrado.")
        return

    # Tela de sucesso
    if st.session_state.get("reab_ok"):
        info = st.session_state["reab_ok"]
        st.markdown(f"""
        <div style="background:var(--ok-bg);border:2px solid rgba(22,163,74,.3);
                    border-radius:12px;padding:2rem;text-align:center;margin:1rem 0;">
            <div style="font-size:2rem;margin-bottom:.5rem;">📦</div>
            <div style="font-size:1.2rem;font-weight:700;color:var(--ok);margin-bottom:.5rem;">
                Estoque Reabastecido!
            </div>
            <div style="font-size:.85rem;color:var(--t2);">
                <strong>+{qtd_br(info['qc'])} {info['us_lbl']}</strong>
                adicionados a <strong>{info['nome']}</strong><br>
                <span style="color:var(--t3);font-size:.78rem;">
                    {info['data']} &nbsp;|&nbsp; por: <strong>{info['nick']}</strong>
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("♻️ Novo Reabastecimento", type="primary", key="btn_novo_reab"):
            del st.session_state["reab_ok"]
            st.session_state.pop("reab_prod_sel", None)
            st.rerun()
        return

    pm = {f"{p['nome']} ({p['codigo_interno']})": p for p in prods}

    st.markdown('<div class="card"><div class="card-h">♻️ Reabastecimento de Estoque</div>',
                unsafe_allow_html=True)
    st.info("Selecione um produto já cadastrado e registre a nova entrada de estoque.")

    # Produto selecionado — fora do form para saldo em tempo real
    prod_sel = st.selectbox("Produto *", list(pm.keys()), key="reab_prod_sel")
    prod     = pm[prod_sel]
    est      = float(prod.get("quantidade_total_secundaria", 0))
    fat      = float(prod.get("fator_conversao", 1))
    up       = prod.get("unidade_primaria", "UN")
    us       = prod.get("unidade_secundaria", "UN")
    up_lbl   = sigla_para_opcao(up)
    us_lbl   = sigla_para_opcao(us)

    st.markdown(f"""
    <div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;
                padding:.7rem 1rem;margin:.4rem 0;font-size:.83rem;">
        📦 Estoque atual:
        <strong style="color:var(--ok);">{qtd_br(est)} {us_lbl}</strong>
        <span style="color:var(--t3);"> (= {qtd_br(est/fat if fat else 0)} {up_lbl})</span>
    </div>
    """, unsafe_allow_html=True)

    # Tipo fora do form para condicionar obrigatoriedade NF
    te = st.selectbox("Tipo de entrada *", TIPOS, key="te_reab")

    with st.form("freab"):
        c1, c2 = st.columns(2)
        with c1:
            qtd = st.number_input("Quantidade *", min_value=0.001, value=1.0, step=1.0)
            ui  = _u("Unidade informada", val=up, key="ui_reab")
        with c2:
            nfn  = st.text_input("Número NF" + (" *" if te=="Nota Fiscal" else " (opcional)"),
                                  placeholder="Ex: 001234")
            cnr  = st.text_input("Número CNR / Pedido" + (" *" if te=="Nota Fiscal" else " (opcional)"),
                                  placeholder="Ex: CNR-2025-001")
            forn = st.text_input("Fornecedor" + (" *" if te=="Nota Fiscal" else " (opcional)"),
                                  placeholder="Ex: Distribuidora ABC Ltda")
            obs  = st.text_area("Observação", height=50)

        qc     = qtd * fat
        ui_lbl = sigla_para_opcao(ui)

        aviso_unidade = ""
        if ui != up:
            aviso_unidade = f"""
            <div style="background:var(--warn-bg);border:1px solid rgba(217,119,6,.3);
                        border-radius:7px;padding:.55rem .9rem;margin:.4rem 0;font-size:.78rem;
                        color:var(--warn);">
                ⚠️ Unidade informada (<strong>{ui_lbl}</strong>) é diferente da cadastrada
                (<strong>{up_lbl}</strong>). Ao confirmar, o cadastro do produto será
                atualizado para <strong>{ui_lbl}</strong>.
            </div>
            """

        st.markdown(f"""
        <div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;
                    padding:.65rem .9rem;margin:.4rem 0;font-size:.8rem;">
            ➕ <strong>{qtd_br(qtd)} {ui_lbl}</strong>
            <span style="color:var(--t3);"> = +</span>
            <strong style="color:var(--ok);">{qtd_br(qc)} {us_lbl}</strong>
            &nbsp;→&nbsp; Novo saldo:
            <strong style="color:var(--red);">{qtd_br(est+qc)} {us_lbl}</strong>
        </div>
        {aviso_unidade}
        """, unsafe_allow_html=True)

        # PDF upload removido

        if st.form_submit_button("✅ Confirmar Reabastecimento", type="primary", use_container_width=True):
            erros = []
            if te == "Nota Fiscal":
                if not nfn.strip():  erros.append("Número da NF obrigatório.")
                if not forn.strip(): erros.append("Fornecedor obrigatório.")
                if not cnr.strip():  erros.append("Número do Pedido/CNR obrigatório.")
            if erros:
                for e in erros: st.error(e)
            else:
                obs_final = obs.strip()
                if cnr.strip():
                    obs_final = f"CNR: {cnr.strip()}" + (f" | {obs_final}" if obs_final else "")

                from utils.fmt import agora_brt
                agora = agora_brt()

                registrar_movimentacao({
                    "produto_id":            prod["id"],
                    "tipo":                  "entrada",
                    "tipo_entrada":          te,
                    "status":                "concluido",
                    "quantidade_informada":  qtd,
                    "unidade_informada":     ui,
                    "quantidade_convertida": qc,
                    "envio_financeiro":      True,
                    "fornecedor":            forn.strip() or None,
                    "numero_nf":             nfn.strip() or None,
                    "observacao":            obs_final or None,
                    "usuario_executor":      u["id"],
                    "data_movimentacao":     agora.isoformat(),
                })

                # Atualiza a unidade primária cadastrada caso tenha sido alterada
                if ui != up:
                    atualizar_produto(prod["id"], {"unidade_primaria": ui})

                st.session_state["reab_ok"] = {
                    "nome":   prod["nome"],
                    "qc":     qc,
                    "us_lbl": us_lbl,
                    "nick":   u.get("nick",""),
                    "data":   agora.strftime("%d/%m/%Y %H:%M"),
                }
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# HISTÓRICO
# ══════════════════════════════════════════════════════════════════

def _hist():
    movs = listar_movimentacoes(tipo="entrada", limite=100)
    if not movs:
        st.info("Nenhuma entrada registrada.")
        return
    st.markdown('<div class="card"><div class="card-h">Histórico de Entradas</div>',
                unsafe_allow_html=True)
    rows = ""
    for m in movs:
        prod   = (m.get("produto") or {}).get("nome","—")
        cod    = (m.get("produto") or {}).get("codigo_interno","—")
        eu     = (m.get("exe") or {}).get("nick","—")
        tp     = badge(m.get("tipo_entrada","—"), "concluido")
        un_lbl = sigla_para_opcao(m.get("unidade_informada","UN"))
        nf     = m.get("numero_nf") or "—"
        obs    = m.get("observacao") or "—"
        rows  += (f'<tr>'
                  f'<td style="color:var(--t3);font-size:.73rem;">{datahora_br(m["criado_em"])}</td>'
                  f'<td><strong>{prod}</strong></td>'
                  f'<td class="mono">{cod}</td>'
                  f'<td style="font-weight:600;">{qtd_br(m["quantidade_informada"])} {un_lbl}</td>'
                  f'<td>{tp}</td>'
                  f'<td style="color:var(--t3);">{nf}</td>'
                  f'<td style="color:var(--t3);font-size:.72rem;">{obs[:30]}{"…" if len(obs)>30 else ""}</td>'
                  f'<td style="color:var(--t3);">{eu}</td>'
                  f'</tr>')
    st.markdown(
        f'<table class="tbl"><thead><tr>'
        f'<th>Data/Hora</th><th>Produto</th><th>Código</th>'
        f'<th>Qtd</th><th>Tipo</th><th>NF</th><th>Obs/CNR</th><th>Executor</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>',
        unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
