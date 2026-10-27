"""Leitura de arquivos BibTeX (exportação da ACM Digital Library), no mesmo formato normalizado do RIS."""
import re
import unicodedata

from .ris import limpar_doi

TIPOS_BIB = {
    "article": "article", "inproceedings": "conference", "conference": "conference", "proceedings": "conference",
    "incollection": "chapter", "inbook": "chapter", "book": "book",
    "phdthesis": "thesis", "mastersthesis": "thesis", "techreport": "report",
}

ENTRADA = re.compile(r"@(\w+)\s*([{(])", re.ASCII)
CAMPO = re.compile(r"\s*([\w\-]+)\s*=\s*", re.ASCII)
ACENTO_SIMBOLO = re.compile(r"\\([`'^\"~=.])\s*\{?\\?([A-Za-z])\}?")
ACENTO_LETRA = re.compile(r"\\([uvHckr])\s*\{([A-Za-z])\}")
COMBINANTE = {"`": "\u0300", "'": "\u0301", "^": "\u0302", "~": "\u0303", "=": "\u0304", ".": "\u0307", '"': "\u0308",
              "u": "\u0306", "v": "\u030c", "H": "\u030b", "c": "\u0327", "k": "\u0328", "r": "\u030a"}


def _fechar(texto: str, i: int, abre: str, fecha: str) -> int:
    """Índice do delimitador que fecha o aberto em texto[i]; -1 se faltar."""
    nivel = 0
    while i < len(texto):
        c = texto[i]
        if c == "\\":
            i += 2
            continue
        if c == abre:
            nivel += 1
        elif c == fecha:
            nivel -= 1
            if nivel == 0:
                return i
        i += 1
    return -1


def _acento(m) -> str:
    return unicodedata.normalize("NFC", m.group(2) + COMBINANTE[m.group(1)])


def limpar(valor: str) -> str:
    v = ACENTO_SIMBOLO.sub(_acento, valor)
    v = ACENTO_LETRA.sub(_acento, v)
    for tex, car in ((r"\&", "&"), (r"\%", "%"), (r"\_", "_"), (r"\$", "$"), (r"\#", "#"), (r"\ss", "ß"), (r"\o", "ø")):
        v = v.replace(tex, car)
    v = re.sub(r"\\(?:textit|textbf|emph|texttt|url)\s*", "", v)
    v = v.replace("{", "").replace("}", "").replace("~", " ")
    return re.sub(r"\s+", " ", v).strip()


def _valor(corpo: str, i: int):
    """Lê o valor de um campo a partir de i; devolve (texto, próximo índice)."""
    partes = []
    while i < len(corpo):
        while i < len(corpo) and corpo[i].isspace():
            i += 1
        if i >= len(corpo):
            break
        c = corpo[i]
        if c == "{":
            fim = _fechar(corpo, i, "{", "}")
            if fim < 0:
                fim = len(corpo)
            partes.append(corpo[i + 1:fim])
            i = fim + 1
        elif c == '"':
            j = i + 1
            while j < len(corpo) and corpo[j] != '"':
                j += 2 if corpo[j] == "\\" else 1
            partes.append(corpo[i + 1:j])
            i = j + 1
        else:
            m = re.match(r"[^,#}\s]+", corpo[i:])
            partes.append(m.group(0) if m else "")
            i += len(m.group(0)) if m else 1
        while i < len(corpo) and corpo[i].isspace():
            i += 1
        if i < len(corpo) and corpo[i] == "#":
            i += 1
            continue
        break
    return "".join(partes), i


def _campos(corpo: str) -> dict:
    campos = {}
    i = corpo.find(",") + 1  # pula a chave de citação
    while i > 0 and i < len(corpo):
        m = CAMPO.match(corpo, i)
        if not m:
            i += 1
            continue
        valor, i = _valor(corpo, m.end())
        campos[m.group(1).lower()] = valor
        while i < len(corpo) and corpo[i] in ", \t\r\n":
            i += 1
    return campos


def _autores(valor: str) -> str:
    nomes = [limpar(a) for a in re.split(r"\s+and\s+", valor.replace("\n", " ")) if a.strip()]
    return "; ".join(n for n in nomes if n)


def _palavras(valor: str) -> str:
    v = limpar(valor)
    sep = ";" if ";" in v else ","
    return "; ".join(k.strip() for k in v.split(sep) if k.strip())


def ler(texto: str):
    """Devolve lista de dicionários normalizados (mesmas chaves de ris.ler)."""
    registros, i = [], 0
    while True:
        m = ENTRADA.search(texto, i)
        if not m:
            break
        fecha = "}" if m.group(2) == "{" else ")"
        fim = _fechar(texto, m.end() - 1, m.group(2), fecha)
        corpo = texto[m.end():fim if fim >= 0 else len(texto)]
        i = (fim if fim >= 0 else len(texto)) + 1
        tipo = m.group(1).lower()
        if tipo in ("comment", "string", "preamble"):
            continue
        c = _campos(corpo)
        titulo = limpar(c.get("title", ""))
        if not titulo:
            continue
        ano = re.search(r"(19|20)\d{2}", c.get("year", "") or c.get("date", ""))
        registros.append({
            "titulo": titulo,
            "autores": _autores(c.get("author", "") or c.get("editor", "")),
            "ano": ano.group(0) if ano else "",
            "doi": limpar_doi(c.get("doi", "")) or limpar_doi(c.get("url", "")),
            "resumo": limpar(c.get("abstract", "")),
            "palavras_chave": _palavras(c.get("keywords", "")),
            "veiculo": limpar(c.get("journal", "") or c.get("booktitle", "") or c.get("series", "")),
            "tipo_doc": TIPOS_BIB.get(tipo, tipo or "other"),
            "idioma": limpar(c.get("language", "")),
            "url": limpar(c.get("url", "")),
        })
    return registros
