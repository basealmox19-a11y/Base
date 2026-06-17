"""utils/unidades.py"""
UNIDADES_MAP = {
    "UN":"UN (Unidade)","CX":"CX (Caixa)","KG":"KG (Quilograma)","LT":"LT (Litro)",
    "MT":"MT (Metro)","PC":"PC (Peça)","RL":"RL (Rolo)","FR":"FR (Frasco)",
    "GL":"GL (Galão)","DZ":"DZ (Dúzia)","CT":"CT (Centena)","SC":"SC (Saco)",
    "FD":"FD (Fardo)","BL":"BL (Bloco)","PT":"PT (Pacote)","PR":"PR (Par)",
    "TB":"TB (Tubo)","CJ":"CJ (Conjunto)","FL":"FL (Folha)","GR":"GR (Grama)",
    "PLT:"PLT (Palete)",
}
SIGLAS = list(UNIDADES_MAP.keys())
OPCOES = list(UNIDADES_MAP.values())

def sigla_para_opcao(sigla: str) -> str:
    return UNIDADES_MAP.get(sigla, sigla)

def opcao_para_sigla(opcao: str) -> str:
    if opcao in UNIDADES_MAP: return opcao
    for sig, nome in UNIDADES_MAP.items():
        if nome == opcao: return sig
    return opcao.split(" ")[0]
