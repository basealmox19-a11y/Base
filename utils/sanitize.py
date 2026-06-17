"""utils/sanitize.py — Proteção contra XSS em dados do banco exibidos em HTML"""
import html

def esc(value) -> str:
    """Escapa qualquer string do banco antes de inserir em HTML unsafe_allow_html.
    Converte < > & " ' em entidades HTML para prevenir XSS.
    """
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)

def esc_trunc(value, max_len: int = 50) -> str:
    """Escapa e trunca. Útil para campos longos em tabelas."""
    s = esc(value)
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s
