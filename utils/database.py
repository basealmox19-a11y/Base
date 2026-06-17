"""utils/database.py — Seguro: erros internos nunca expostos ao usuário"""
import os, logging, streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()

# Logger interno — não aparece na UI
_log = logging.getLogger("sfc.database")

def _err_generico():
    """Mensagem de erro genérica sem vazar detalhes internos."""
    st.error("❌ Erro ao acessar o banco de dados. Tente novamente ou contate o administrador.")

@st.cache_resource(show_spinner=False)
def get_sb() -> Client:
    url = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL","")
    key = os.getenv("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_SERVICE_KEY","")
    if not url or not key:
        # Não revela os nomes das variáveis ao usuário
        st.error("❌ Configuração de banco de dados ausente. Contate o administrador.")
        st.stop()
    return create_client(url, key)

def _m(q):
    try: return q.maybe_single().execute().data
    except Exception as e:
        _log.error("_m query error: %s", e)
        return None

# ── USUÁRIOS ─────────────────────────────────────────────────────
def contar_usuarios() -> int:
    try: return get_sb().table("usuarios").select("id",count="exact").execute().count or 0
    except Exception as e:
        _log.error("contar_usuarios: %s", e)
        return 0

def buscar_por_nick(nick: str):
    try: return _m(get_sb().table("usuarios").select("*").eq("nick",nick.strip().lower()))
    except Exception as e:
        _log.error("buscar_por_nick: %s", e)
        return None

def criar_usuario(dados: dict) -> dict:
    try:
        return get_sb().table("usuarios").insert(dados).execute().data[0]
    except Exception as e:
        err = str(e)
        _log.error("criar_usuario: %s", e)
        if "42501" in err or "row-level" in err:
            st.error("❌ Permissão negada. Contate o administrador.")
        elif "42P01" in err or "does not exist" in err:
            st.error("❌ Configuração do banco incompleta. Execute o schema.sql.")
        elif "23505" in err or "unique" in err.lower():
            st.error("❌ Este nick já está em uso. Escolha outro.")
        else:
            st.error("❌ Não foi possível criar o usuário. Tente novamente.")
        st.stop()

def listar_usuarios() -> list:
    try: return get_sb().table("usuarios").select("*").order("nick").execute().data or []
    except Exception as e:
        _log.error("listar_usuarios: %s", e)
        return []

def atualizar_usuario(uid: str, dados: dict):
    try: get_sb().table("usuarios").update(dados).eq("id",uid).execute()
    except Exception as e:
        _log.error("atualizar_usuario: %s", e)
        st.error("❌ Não foi possível atualizar o usuário.")

def excluir_usuario(uid: str):
    try: get_sb().table("usuarios").delete().eq("id",uid).execute()
    except Exception as e:
        _log.error("excluir_usuario: %s", e)
        st.error("❌ Não foi possível excluir o usuário.")

# ── CATEGORIAS ───────────────────────────────────────────────────
def listar_categorias() -> list:
    try: return get_sb().table("categorias").select("*").order("nome").execute().data or []
    except Exception as e:
        _log.error("listar_categorias: %s", e)
        return []

def criar_categoria(nome, desc=""):
    try: return get_sb().table("categorias").insert({"nome":nome,"descricao":desc}).execute().data[0]
    except Exception as e:
        _log.error("criar_categoria: %s", e)
        st.error("❌ Erro ao criar categoria."); return None

# ── SETORES ──────────────────────────────────────────────────────
def listar_setores(apenas_ativos=True) -> list:
    try:
        q = get_sb().table("setores").select("*").order("nome")
        if apenas_ativos: q = q.eq("ativo",True)
        return q.execute().data or []
    except Exception as e:
        _log.error("listar_setores: %s", e)
        return []

def criar_setor(nome):
    try: return get_sb().table("setores").insert({"nome":nome}).execute().data[0]
    except Exception as e:
        _log.error("criar_setor: %s", e)
        st.error("❌ Erro ao criar setor."); return None

def atualizar_setor(sid, dados):
    try: get_sb().table("setores").update(dados).eq("id",sid).execute()
    except Exception as e:
        _log.error("atualizar_setor: %s", e)

# ── PRODUTOS ─────────────────────────────────────────────────────
def listar_produtos(apenas_ativos=True) -> list:
    try:
        q = get_sb().table("produtos").select("*,categorias(nome)").order("nome")
        if apenas_ativos: q = q.eq("ativo",True)
        return q.execute().data or []
    except Exception as e:
        _log.error("listar_produtos: %s", e)
        return []

def buscar_produto_por_ean(ean):
    try: return _m(get_sb().table("produtos").select("*,categorias(nome)").eq("ean",ean.strip()))
    except Exception as e:
        _log.error("buscar_produto_por_ean: %s", e)
        return None

def buscar_produto_por_id(pid):
    try: return _m(get_sb().table("produtos").select("*,categorias(nome)").eq("id",pid))
    except Exception as e:
        _log.error("buscar_produto_por_id: %s", e)
        return None

def buscar_produtos_por_nome(nome) -> list:
    try:
        # Sanitiza entrada — remove caracteres perigosos para a query
        nome_safe = nome.strip().replace("%","").replace("_","")[:100]
        return get_sb().table("produtos").select("*,categorias(nome)").ilike("nome",f"%{nome_safe}%").eq("ativo",True).execute().data or []
    except Exception as e:
        _log.error("buscar_produtos_por_nome: %s", e)
        return []

def criar_produto(dados) -> dict:
    try: return get_sb().table("produtos").insert(dados).execute().data[0]
    except Exception as e:
        _log.error("criar_produto: %s", e)
        st.error("❌ Erro ao criar produto."); st.stop()

def atualizar_produto(pid, dados):
    try: get_sb().table("produtos").update(dados).eq("id",pid).execute()
    except Exception as e:
        _log.error("atualizar_produto: %s", e)
        st.error("❌ Erro ao atualizar produto.")

# ── ESTOQUE COM RESERVAS ─────────────────────────────────────────
def estoque_disponivel(produto_id: str) -> float:
    try:
        prod = buscar_produto_por_id(produto_id)
        if not prod: return 0.0
        total = float(prod.get("quantidade_total_secundaria",0))
        reservas = (get_sb().table("movimentacoes")
                    .select("quantidade_convertida")
                    .eq("produto_id",produto_id)
                    .eq("tipo","saida").eq("tipo_saida","SOLICITADA")
                    .in_("status",["pendente","aprovado"])
                    .execute().data or [])
        res = sum(float(r.get("quantidade_convertida",0)) for r in reservas)
        return max(0.0, total - res)
    except Exception as e:
        _log.error("estoque_disponivel: %s", e)
        return 0.0

# ── DOCUMENTOS ───────────────────────────────────────────────────
def criar_documento(dados) -> dict:
    try: return get_sb().table("documentos").insert(dados).execute().data[0]
    except Exception as e:
        _log.error("criar_documento: %s", e)
        return {}

def upload_pdf(b, nome):
    try:
        sb = get_sb(); path = f"notas/{nome}"
        sb.storage.from_("notas-fiscais").upload(path,b,file_options={"content-type":"application/pdf","upsert":"true"})
        return sb.storage.from_("notas-fiscais").create_signed_url(path,60*60*24*365).get("signedURL")
    except Exception as e:
        _log.error("upload_pdf: %s", e)
        st.warning("⚠️ Não foi possível fazer o upload do arquivo.")
        return None

# ── MOVIMENTAÇÕES ────────────────────────────────────────────────
_SEL = """*,
    produto:produtos(id,nome,codigo_interno,unidade_primaria,unidade_secundaria,fator_conversao,quantidade_total_secundaria),
    sol:usuarios!movimentacoes_usuario_solicitante_fkey(nick,nome),
    aut:usuarios!movimentacoes_usuario_autorizador_fkey(nick,nome),
    exe:usuarios!movimentacoes_usuario_executor_fkey(nick,nome),
    doc:documentos(nome_arquivo,status_envio,caminho_arquivo)"""

def registrar_movimentacao(dados) -> dict:
    try: return get_sb().table("movimentacoes").insert(dados).execute().data[0]
    except Exception as e:
        _log.error("registrar_movimentacao: %s", e)
        st.error("❌ Erro ao registrar movimentação."); st.stop()

def atualizar_movimentacao(mid, dados) -> dict:
    try: return get_sb().table("movimentacoes").update(dados).eq("id",mid).execute().data[0]
    except Exception as e:
        _log.error("atualizar_movimentacao: %s", e)
        st.error("❌ Erro ao atualizar movimentação.")
        return {}

def listar_movimentacoes(tipo=None,status=None,tipo_saida=None,produto_id=None,limite=200) -> list:
    try:
        q = get_sb().table("movimentacoes").select(_SEL).order("criado_em",desc=True).limit(limite)
        if tipo: q = q.eq("tipo",tipo)
        if status: q = q.eq("status",status)
        if tipo_saida: q = q.eq("tipo_saida",tipo_saida)
        if produto_id: q = q.eq("produto_id",produto_id)
        return q.execute().data or []
    except Exception as e:
        _log.error("listar_movimentacoes: %s", e)
        return []

def listar_solicitacoes(status=None) -> list:
    try:
        q = (get_sb().table("movimentacoes").select(_SEL)
             .eq("tipo","saida").eq("tipo_saida","SOLICITADA").order("criado_em",desc=True))
        if status: q = q.eq("status",status)
        return q.execute().data or []
    except Exception as e:
        _log.error("listar_solicitacoes: %s", e)
        return []

def listar_notificacoes_usuario(nick: str) -> list:
    try:
        return (get_sb().table("movimentacoes").select(_SEL)
                .eq("nick_solicitante",nick)
                .eq("tipo_saida","SOLICITADA")
                .eq("status","aprovado")
                .eq("notificacao_lida",False)
                .execute().data or [])
    except Exception as e:
        _log.error("listar_notificacoes_usuario: %s", e)
        return []  # Coluna pode não existir ainda

def listar_notas_pendentes() -> list:
    try:
        return (get_sb().table("movimentacoes").select(_SEL)
                .eq("tipo","entrada").eq("tipo_entrada","Nota Fiscal")
                .eq("envio_financeiro",False).eq("status","concluido")
                .order("criado_em",desc=True).execute().data or [])
    except Exception as e:
        _log.error("listar_notas_pendentes: %s", e)
        return []

def listar_notas_enviadas() -> list:
    try:
        return (get_sb().table("movimentacoes").select(_SEL)
                .eq("tipo","entrada").eq("tipo_entrada","Nota Fiscal")
                .eq("envio_financeiro",True)
                .order("criado_em",desc=True).execute().data or [])
    except Exception as e:
        _log.error("listar_notas_enviadas: %s", e)
        return []

def historico_produto(produto_id, data_ini=None, data_fim=None) -> list:
    try:
        q = (get_sb().table("movimentacoes").select(_SEL)
             .eq("produto_id",produto_id).order("criado_em",desc=False))
        if data_ini: q = q.gte("criado_em",f"{data_ini}T00:00:00")
        if data_fim: q = q.lte("criado_em",f"{data_fim}T23:59:59")
        return q.execute().data or []
    except Exception as e:
        _log.error("historico_produto: %s", e)
        return []

# ── CONFIGURAÇÕES ────────────────────────────────────────────────
def get_config(chave, default="") -> str:
    try:
        r = _m(get_sb().table("configuracoes").select("valor").eq("chave",chave))
        return r["valor"] if r else default
    except Exception as e:
        _log.error("get_config %s: %s", chave, e)
        return default

def set_config(chave, valor):
    try: get_sb().table("configuracoes").upsert({"chave":chave,"valor":valor}).execute()
    except Exception as e:
        _log.error("set_config %s: %s", chave, e)
        st.error("❌ Erro ao salvar configuração.")

def listar_configs() -> dict:
    try: return {c["chave"]:c["valor"] for c in get_sb().table("configuracoes").select("*").execute().data or []}
    except Exception as e:
        _log.error("listar_configs: %s", e)
        return {}

# ── CONSUMO POR PERÍODO ──────────────────────────────────────────
def consumo_por_periodo(data_ini, data_fim, setor=None) -> list:
    try:
        q = (get_sb().table("movimentacoes")
             .select("criado_em,tipo,tipo_entrada,tipo_saida,quantidade_convertida,setor_solicitante,produto:produtos(nome,unidade_secundaria),exe:usuarios!movimentacoes_usuario_executor_fkey(nick)")
             .in_("tipo",["entrada","saida"]).eq("status","concluido")
             .gte("criado_em",f"{data_ini}T00:00:00")
             .lte("criado_em",f"{data_fim}T23:59:59")
             .order("criado_em",desc=False))
        if setor: q = q.eq("setor_solicitante",setor)
        return q.execute().data or []
    except Exception as e:
        _log.error("consumo_por_periodo: %s", e)
        return []

# ── DASHBOARD ────────────────────────────────────────────────────
def stats_dashboard() -> dict:
    _vazio = {"total_produtos":0,"criticos":0,"baixos":0,"ok":0,"pend_solicitacoes":0,
              "pend_notas":0,"total_movimentacoes":0,"consumo_setor":{},"parados":0,"recentes":[],"produtos":[]}
    try:
        sb = get_sb(); prods = listar_produtos()
        criticos=baixos=ok_c=0
        for p in prods:
            est=float(p.get("quantidade_total_secundaria") or 0)
            minp=float(p.get("estoque_minimo_primario") or 0)
            fat=float(p.get("fator_conversao") or 1)
            if est<=0: criticos+=1
            elif est<=minp*fat: baixos+=1
            else: ok_c+=1
        pend_sol=sb.table("movimentacoes").select("id",count="exact").eq("tipo","saida").eq("tipo_saida","SOLICITADA").eq("status","pendente").execute().count or 0
        pend_nf=sb.table("movimentacoes").select("id",count="exact").eq("tipo_entrada","Nota Fiscal").eq("envio_financeiro",False).eq("status","concluido").execute().count or 0
        total_mov=sb.table("movimentacoes").select("id",count="exact").execute().count or 0
        saidas_ok=sb.table("movimentacoes").select("setor_solicitante,quantidade_convertida").eq("tipo","saida").eq("status","concluido").execute().data or []
        consumo={}
        for s in saidas_ok:
            k=s.get("setor_solicitante") or "Sem setor"
            consumo[k]=consumo.get(k,0)+float(s.get("quantidade_convertida") or 0)
        from datetime import datetime,timedelta
        lim=(datetime.utcnow()-timedelta(days=30)).isoformat()
        ids_mov={m["produto_id"] for m in sb.table("movimentacoes").select("produto_id").gte("criado_em",lim).execute().data or []}
        parados=sum(1 for p in prods if p["id"] not in ids_mov)
        recentes=sb.table("movimentacoes").select("criado_em,tipo,quantidade_informada,unidade_informada,status,produtos(nome)").order("criado_em",desc=True).limit(10).execute().data or []
        return {"total_produtos":len(prods),"criticos":criticos,"baixos":baixos,"ok":ok_c,
                "pend_solicitacoes":pend_sol,"pend_notas":pend_nf,"total_movimentacoes":total_mov,
                "consumo_setor":consumo,"parados":parados,"recentes":recentes,"produtos":prods}
    except Exception as e:
        _log.error("stats_dashboard: %s", e)
        return _vazio


# ── SOLICITAÇÕES DE COMPRA ───────────────────────────────────────
_SEL_SC = """*,
    solicitante:usuarios!solicitacoes_compra_usuario_id_fkey(nick,nome),
    autorizador:usuarios!solicitacoes_compra_usuario_autorizador_fkey(nick,nome)"""

def listar_solicitacoes_compra(status=None) -> list:
    try:
        q = get_sb().table("solicitacoes_compra").select(_SEL_SC).order("criado_em", desc=True)
        if status: q = q.eq("status", status)
        return q.execute().data or []
    except Exception as e:
        _log.error("listar_solicitacoes_compra: %s", e)
        return []

def criar_solicitacao_compra(dados: dict) -> dict:
    try: return get_sb().table("solicitacoes_compra").insert(dados).execute().data[0]
    except Exception as e:
        _log.error("criar_solicitacao_compra: %s", e)
        st.error("❌ Erro ao registrar solicitação de compra.")
        st.stop()

def atualizar_solicitacao_compra(scid: str, dados: dict):
    try: get_sb().table("solicitacoes_compra").update(dados).eq("id", scid).execute()
    except Exception as e:
        _log.error("atualizar_solicitacao_compra: %s", e)
        st.error("❌ Erro ao atualizar solicitação de compra.")

def contar_solicitacoes_compra_pendentes() -> int:
    try:
        return get_sb().table("solicitacoes_compra").select("id", count="exact").eq("status","pendente").execute().count or 0
    except Exception as e:
        _log.error("contar_sc_pendentes: %s", e)
        return 0

# ── PREVISÃO DE DEMANDA (crowdsourcing histórico) ────────────────
def historico_consumo_mensal(meses: int = 24) -> list:
    """Retorna consumo mensal agrupado por produto dos últimos N meses."""
    try:
        from datetime import datetime, timedelta
        lim = (datetime.utcnow() - timedelta(days=meses*30)).isoformat()
        dados = (get_sb().table("movimentacoes")
                 .select("criado_em,produto_id,quantidade_convertida,produto:produtos(nome,unidade_secundaria)")
                 .eq("tipo","saida").eq("status","concluido")
                 .gte("criado_em", lim)
                 .order("criado_em", desc=False)
                 .execute().data or [])
        return dados
    except Exception as e:
        _log.error("historico_consumo_mensal: %s", e)
        return []
