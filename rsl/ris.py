"""Leitura e escrita de arquivos RIS."""
import re

TAG = re.compile(r"^([A-Z][A-Z0-9])  -\s?(.*)$")

TIPOS_RIS = {
    "JOUR": "article", "JFULL": "article", "EJOUR": "article", "MGZN": "article",
    "CONF": "conference", "CPAPER": "conference", "PROC": "conference",
    "CHAP": "chapter", "BOOK": "book", "EBOOK": "book", "ECHAP": "chapter",
    "THES": "thesis", "RPRT": "report", "GEN": "other",
}


def ler_texto(dados: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", "replace")


def ler(texto: str):
    """Devolve lista de dicionários normalizados."""
    registros, atual, ultima = [], None, None
    for linha in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = TAG.match(linha.rstrip())
        if not m:
            if atual is not None and ultima and linha.strip():
                atual[ultima][-1] += " " + linha.strip()
            continue
        tag, valor = m.group(1), m.group(2).strip()
        if tag == "TY":
            atual = {"TY": [valor]}
            ultima = "TY"
        elif tag == "ER":
            if atual is not None:
                registros.append(normalizar(atual))
            atual, ultima = None, None
        elif atual is not None:
            atual.setdefault(tag, []).append(valor)
            ultima = tag
    if atual is not None and len(atual) > 1:
        registros.append(normalizar(atual))
    return registros


def _primeiro(r, *tags):
    for t in tags:
        if r.get(t):
            v = r[t][0].strip()
            if v:
                return v
    return ""


def _ano(texto: str) -> str:
    m = re.search(r"(19|20)\d{2}", texto or "")
    return m.group(0) if m else ""


def normalizar(r: dict) -> dict:
    autores = r.get("AU", []) or r.get("A1", []) or r.get("A2", [])
    kws = []
    for k in r.get("KW", []):
        kws += [x.strip() for x in re.split(r";", k) if x.strip()]
    ty = _primeiro(r, "TY").upper()
    return {
        "titulo": _primeiro(r, "TI", "T1", "CT", "BT"),
        "autores": "; ".join(a.strip() for a in autores if a.strip()),
        "ano": _ano(_primeiro(r, "PY", "Y1", "DA", "Y2")),
        "doi": limpar_doi(_primeiro(r, "DO", "DI")) or limpar_doi(" ".join(r.get("UR", []) + r.get("L3", []))),
        "resumo": " ".join(r.get("AB", []) or r.get("N2", [])).strip(),
        "palavras_chave": "; ".join(kws),
        "veiculo": _primeiro(r, "T2", "JO", "JF", "JA", "BT", "T3"),
        "tipo_doc": TIPOS_RIS.get(ty, ty.lower() or "other"),
        "idioma": _primeiro(r, "LA"),
        "url": _primeiro(r, "UR", "L2"),
    }


def limpar_doi(texto: str) -> str:
    if not texto:
        return ""
    m = re.search(r"10\.\d{4,9}/[^\s\"<>]+", texto)
    return m.group(0).rstrip(".,;)").lower() if m else ""


MAPA_SAIDA = {"article": "JOUR", "conference": "CONF", "chapter": "CHAP", "book": "BOOK", "review": "JOUR"}


def escrever(registros) -> str:
    out = []
    for r in registros:
        out.append(f"TY  - {MAPA_SAIDA.get(r.get('tipo_doc'), 'GEN')}")
        if r.get("titulo"):
            out.append(f"TI  - {r['titulo']}")
        for a in [x.strip() for x in (r.get("autores") or "").split(";") if x.strip()]:
            out.append(f"AU  - {a}")
        if r.get("ano"):
            out.append(f"PY  - {r['ano']}")
        if r.get("veiculo"):
            out.append(f"T2  - {r['veiculo']}")
        if r.get("doi"):
            out.append(f"DO  - {r['doi']}")
        if r.get("resumo"):
            out.append(f"AB  - {r['resumo']}")
        for k in [x.strip() for x in (r.get("palavras_chave") or "").split(";") if x.strip()]:
            out.append(f"KW  - {k}")
        if r.get("idioma"):
            out.append(f"LA  - {r['idioma']}")
        if r.get("url"):
            out.append(f"UR  - {r['url']}")
        if r.get("id"):
            out.append(f"ID  - {r['id']}")
        out.append("ER  - ")
        out.append("")
    return "\n".join(out)
