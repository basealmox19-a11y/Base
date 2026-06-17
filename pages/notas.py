"""pages/notas.py — Notas Fiscais com anexo automático via mailto"""
import urllib.parse, streamlit as st
from utils.database import (listar_notas_pendentes, listar_notas_enviadas,
    atualizar_movimentacao, get_config)
from utils.auth import sessao
from utils.ui import badge, kpi_html
from utils.fmt import datahora_br
from utils.sanitize import esc, esc_trunc


def tela_notas():
    st.markdown('<div class="pg">', unsafe_allow_html=True)
    st.markdown('<div class="pg-title">📎 Notas Fiscais</div>'
                '<div class="pg-sub">Gerencie e envie ao financeiro</div>',
                unsafe_allow_html=True)
    p = listar_notas_pendentes()
    e = listar_notas_enviadas()
    st.markdown(f"""
    <div class="kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:1.2rem;">
        {kpi_html("Total NF",  len(p)+len(e), "",                 "var(--t2)")}
        {kpi_html("Pendentes", len(p),         "Aguardando envio","var(--warn)")}
        {kpi_html("Enviadas",  len(e),         "Processadas",     "var(--ok)")}
    </div>
    """, unsafe_allow_html=True)
    t1, t2 = st.tabs([f"Pendentes ({len(p)})", f"Enviadas ({len(e)})"])
    with t1: _lista(p, pendente=True)
    with t2: _lista(e, pendente=False)
    st.markdown("</div>", unsafe_allow_html=True)


def _lista(movs, pendente: bool):
    u          = sessao()
    email_dest = get_config("email_financeiro", "financeiro@empresa.com.br")
    email_subj = get_config("email_assunto",    "[NF] Nota Fiscal - SFC Almoxarifado")
    email_body = get_config("email_corpo",      "Prezados,\n\nSegue nota fiscal.\n\nAtenciosamente,")

    if not movs:
        msg = "Nenhuma nota pendente." if pendente else "Nenhuma nota enviada."
        st.markdown(f'<p style="color:var(--t3);font-size:.82rem;padding:1rem 0;">{msg}</p>',
                    unsafe_allow_html=True)
        return

    for m in movs:
        prod    = m.get("produto") or {}
        doc     = m.get("doc")     or {}
        eu      = (m.get("exe") or {}).get("nick","—")
        nfn     = m.get("numero_nf")  or "—"
        forn    = m.get("fornecedor") or "—"
        obs     = m.get("observacao") or ""
        pdf_url = doc.get("caminho_arquivo")
        bx      = badge("Pendente","pendente") if pendente else badge("Enviado","enviado")

        # Extrai CNR da observação (formato "CNR: XXX | ...")
        cnr = ""
        if obs and obs.startswith("CNR:"):
            cnr = obs.split("|")[0].replace("CNR:","").strip()

        st.markdown('<div class="card">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([4, 3, 3])

        with c1:
            st.markdown(f"**NF {esc(nfn)}** — {esc(forn)} &nbsp;{bx}", unsafe_allow_html=True)
            if cnr:
                st.markdown(f"<span style='font-size:.74rem;color:var(--info);'>📋 CNR/Pedido: <strong>{esc(cnr)}</strong></span>",
                            unsafe_allow_html=True)
            st.markdown(f"<span style='font-size:.77rem;color:var(--t3);'>{esc(prod.get('nome','—'))}</span>",
                        unsafe_allow_html=True)
            st.caption(f"Registrada em {datahora_br(m.get('criado_em'))} por {eu}")

        with c2:
            if pdf_url:
                st.link_button("📄 Visualizar PDF", pdf_url)
            else:
                st.markdown("<span style='font-size:.75rem;color:var(--t4);'>Sem arquivo PDF</span>",
                            unsafe_allow_html=True)

        with c3:
            if pendente:
                nome_u = u.get("nome") or u.get("nick","")

                # Corpo do e-mail com todos os dados (NF, CNR, fornecedor, produto, link PDF)
                corpo_linhas = [
                    email_body,
                    "",
                    "=== Dados da Nota Fiscal ===",
                    f"Número NF:       {nfn}",
                    f"CNR / Pedido:    {cnr if cnr else '—'}",
                    f"Fornecedor:      {forn}",
                    f"Produto:         {prod.get('nome','')}",
                ]
                if pdf_url:
                    corpo_linhas += [
                        "",
                        "=== Documento ===",
                        f"Link do arquivo: {pdf_url}",
                        "",
                        "⚠️ Por limitação do cliente de e-mail, faça o download pelo",
                        "link acima e anexe ao e-mail antes de enviar.",
                    ]
                corpo_linhas += ["", f"Atenciosamente,", f"{nome_u}", "SFC Almoxarifado"]
                corpo = "\n".join(corpo_linhas)

                # Assunto com NF e CNR
                assunto = email_subj
                if nfn != "—": assunto += f" — NF {nfn}"
                if cnr:         assunto += f" / CNR {cnr}"

                mailto = (
                    f"mailto:{email_dest}"
                    f"?subject={urllib.parse.quote(assunto)}"
                    f"&body={urllib.parse.quote(corpo)}"
                )

                st.link_button("📧 Abrir no Outlook", mailto)

                if pdf_url:
                    st.markdown("""
                    <div style="font-size:.71rem;color:var(--info);margin:.3rem 0;line-height:1.4;">
                        ℹ️ O link do arquivo está no corpo do e-mail.<br>
                        Baixe e anexe antes de enviar.
                    </div>
                    """, unsafe_allow_html=True)

                if st.button("✅ Enviei — Remover da lista", key=f"env_{m['id']}", use_container_width=True):
                    st.session_state[f"conf_nf_{m['id']}"] = True
                    st.rerun()

            # Pop-up de confirmação
            if st.session_state.get(f"conf_nf_{m['id']}"):
                st.markdown("""
                <div style="background:var(--warn-bg);border:1px solid rgba(217,119,6,.3);
                            border-radius:7px;padding:.7rem .9rem;font-size:.8rem;margin:.4rem 0;">
                    ⚠️ Confirma que o e-mail foi enviado?
                </div>
                """, unsafe_allow_html=True)
                cs, cn = st.columns(2)
                with cs:
                    if st.button("✅ Sim, remover", key=f"sim_nf_{m['id']}",
                                 type="primary", use_container_width=True):
                        atualizar_movimentacao(m["id"], {"envio_financeiro": True})
                        del st.session_state[f"conf_nf_{m['id']}"]
                        st.success("Nota removida!")
                        st.rerun()
                with cn:
                    if st.button("↩ Voltar", key=f"nao_nf_{m['id']}", use_container_width=True):
                        del st.session_state[f"conf_nf_{m['id']}"]
                        st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)
