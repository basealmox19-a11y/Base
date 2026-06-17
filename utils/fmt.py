"""utils/fmt.py — Formatação padrão brasileiro — fuso horário de Brasília"""
from datetime import datetime, timezone, timedelta

# Fuso horário de Brasília (UTC-3)
BRT = timezone(timedelta(hours=-3))

def _to_brt(v):
    """Converte qualquer valor de data/hora para datetime em horário de Brasília."""
    if not v: return None
    if isinstance(v, str):
        v = v.strip()
        # Remove microssegundos e normaliza
        try:
            if "+" in v[10:] or v.endswith("Z"):
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return dt.astimezone(BRT)
            else:
                dt = datetime.strptime(v[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                return dt.replace(tzinfo=timezone.utc).astimezone(BRT)
        except:
            return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc).astimezone(BRT)
        return v.astimezone(BRT)
    return None

def datahora_br(v) -> str:
    dt = _to_brt(v)
    if not dt: return "—"
    return dt.strftime("%d/%m/%Y %H:%M")

def data_br(v) -> str:
    if not v: return "—"
    if isinstance(v, str):
        try:
            dt = datetime.strptime(v[:10], "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except: return str(v)[:10]
    try: return v.strftime("%d/%m/%Y")
    except: return str(v)

def agora_brt() -> datetime:
    """Retorna datetime atual no horário de Brasília."""
    return datetime.now(BRT)

def agora_iso() -> str:
    """ISO string do momento atual em Brasília (para salvar no banco)."""
    return agora_brt().isoformat()

def numero_br(v, dec=0) -> str:
    if v is None: return "—"
    try:
        s = f"{float(v):,.{dec}f}"
        return s.replace(",","X").replace(".",",").replace("X",".")
    except: return str(v)

def qtd_br(v) -> str:
    if v is None: return "—"
    try:
        f = float(v)
        if f == int(f): return numero_br(int(f), 0)
        s = numero_br(f, 3)
        if "," in s: s = s.rstrip("0").rstrip(",")
        return s
    except: return str(v)

def moeda_br(v) -> str:
    return f"R$ {numero_br(v, 2)}" if v is not None else "—"
