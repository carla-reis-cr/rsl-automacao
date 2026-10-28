"""Conectores de API das bases (EXPERIMENTAIS — confirme com a sua chave na busca piloto).

Bases com API de busca: Scopus (Elsevier), IEEE Xplore e Web of Science (Starter API).
ACM, ScienceDirect, Springer e Wiley continuam por exportação manual.

Observações importantes para o relato:
- Os totais via API podem diferir dos da interface web; registre os dois quando possível.
- Algumas APIs não devolvem resumos (WoS Starter; Scopus sem acesso institucional).
  Use "Completar resumos" (OpenAlex) antes da triagem.
"""
import time

import requests

TIMEOUT = 60


class ErroAPI(RuntimeError):
    pass


def _get(url, params=None, headers=None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as ex:
        raise ErroAPI(f"Falha de conexão: {ex}") from ex
    if r.status_code == 429:
        raise ErroAPI("Limite de requisições da API atingido (429). Tente mais tarde.")
    if r.status_code >= 400:
        raise ErroAPI(f"A API respondeu {r.status_code}: {r.text[:400]}")
    try:
        return r.json()
    except ValueError as ex:
        raise ErroAPI(f"Resposta inesperada (não é JSON): {r.text[:300]}") from ex


def _txt(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return " ".join(_txt(x) for x in v.values())
    if isinstance(v, list):
        return " ".join(_txt(x) for x in v)
    return str(v)


# ---------------- Scopus ----------------
TIPOS_SCOPUS = {"Article": "article", "Conference Paper": "conference", "Review": "review", "Book Chapter": "chapter"}


def _scopus(query, chaves, maximo, progresso):
    if not chaves.get("scopus"):
        raise ErroAPI("Chave da Scopus não configurada.")
    url = "https://api.elsevier.com/content/search/scopus"
    h = {"X-ELS-APIKey": chaves["scopus"], "Accept": "application/json"}
    if chaves.get("scopus_insttoken"):
        h["X-ELS-Insttoken"] = chaves["scopus_insttoken"]
    avisos, paginas, regs = [], [], []
    view = "COMPLETE"
    cursor, total, usar_cursor = "*", None, True
    while True:
        params = {"query": query, "count": 25, "view": view}
        params.update({"cursor": cursor} if usar_cursor else {"start": len(regs)})
        try:
            dados = _get(url, params, h)
        except ErroAPI as ex:
            if usar_cursor and "cursor parameter is restricted" in str(ex):
                # Chaves sem acesso institucional não podem usar cursor: pagina por 'start' (limite de 5000 da Scopus).
                usar_cursor = False
                maximo = min(maximo, 5000)
                avisos.append("A chave não permite paginação por cursor; usada paginação por 'start' (máximo de 5.000 registros).")
                continue
            if view == "COMPLETE" and ("401" in str(ex) or "403" in str(ex)):
                view = "STANDARD"
                avisos.append("Sem acesso à visão COMPLETE da Scopus: resumos e palavras-chave não vieram. Use 'Completar resumos'.")
                continue
            raise
        paginas.append(dados)
        sr = dados.get("search-results", {})
        total = int(sr.get("opensearch:totalResults", 0) or 0)
        entradas = [e for e in sr.get("entry", []) if "error" not in e]
        for e in entradas:
            autores = "; ".join(a.get("authname", "") for a in e.get("author", []) if a.get("authname")) or e.get("dc:creator", "")
            regs.append({
                "titulo": _txt(e.get("dc:title")), "autores": autores,
                "ano": (e.get("prism:coverDate") or "")[:4], "doi": (e.get("prism:doi") or "").lower(),
                "resumo": _txt(e.get("dc:description")),
                "palavras_chave": "; ".join(k.strip() for k in (e.get("authkeywords") or "").split("|") if k.strip()),
                "veiculo": _txt(e.get("prism:publicationName")),
                "tipo_doc": TIPOS_SCOPUS.get(e.get("subtypeDescription", ""), (e.get("subtypeDescription") or "").lower()),
                "idioma": "", "url": next((l.get("@href", "") for l in e.get("link", []) if l.get("@ref") == "scopus"), ""),
            })
        progresso(len(regs), total)
        prox = (sr.get("cursor") or {}).get("@next")
        if not entradas or (usar_cursor and not prox) or len(regs) >= min(total, maximo):
            break
        cursor = prox
        time.sleep(0.2)
    return total, regs[:maximo], paginas, avisos


# ---------------- IEEE Xplore ----------------
TIPOS_IEEE = {"Journals": "article", "Early Access Articles": "article", "Magazines": "article",
              "Conferences": "conference", "Books": "chapter"}


def _ieee(query, chaves, maximo, progresso, filtros=None):
    if not chaves.get("ieee"):
        raise ErroAPI("Chave da IEEE Xplore não configurada.")
    url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
    paginas, regs, inicio, total = [], [], 1, 0
    f = filtros or {}
    avisos = ["A API da IEEE busca em todos os metadados e não filtra tipo de documento: tipo e campos são conferidos na triagem."]
    periodo = {}
    if f.get("ano_inicio"):
        periodo["start_year"] = int(f["ano_inicio"])
    if f.get("ano_fim"):
        periodo["end_year"] = int(f["ano_fim"])
    while True:
        dados = _get(url, {"apikey": chaves["ieee"], "querytext": query, "max_records": 200,
                           "start_record": inicio, "format": "json", **periodo})
        paginas.append(dados)
        total = int(dados.get("total_records", 0) or 0)
        arts = dados.get("articles", []) or []
        for a in arts:
            termos = (a.get("index_terms", {}).get("author_terms", {}) or {}).get("terms") or \
                     (a.get("author_terms", {}) or {}).get("terms") or []
            regs.append({
                "titulo": _txt(a.get("title")),
                "autores": "; ".join(x.get("full_name", "") for x in (a.get("authors", {}) or {}).get("authors", [])),
                "ano": str(a.get("publication_year", "")), "doi": (a.get("doi") or "").lower(),
                "resumo": _txt(a.get("abstract")), "palavras_chave": "; ".join(termos),
                "veiculo": _txt(a.get("publication_title")),
                "tipo_doc": TIPOS_IEEE.get(a.get("content_type", ""), (a.get("content_type") or "").lower()),
                "idioma": "", "url": a.get("html_url") or a.get("pdf_url") or "",
            })
        progresso(len(regs), total)
        if not arts or len(regs) >= min(total, maximo):
            break
        inicio += 200
        time.sleep(0.5)
    return total, regs[:maximo], paginas, avisos


# ---------------- Web of Science Starter ----------------
TIPOS_WOS = {"Article": "article", "Proceedings Paper": "conference", "Review": "review", "Book Chapter": "chapter"}


def _wos(query, chaves, maximo, progresso):
    if not chaves.get("wos"):
        raise ErroAPI("Chave do Web of Science não configurada.")
    url = "https://api.clarivate.com/apis/wos-starter/v1/documents"
    h = {"X-ApiKey": chaves["wos"], "Accept": "application/json"}
    paginas, regs, pagina, total = [], [], 1, 0
    while True:
        dados = _get(url, {"db": "WOS", "q": query, "limit": 50, "page": pagina}, h)
        paginas.append(dados)
        total = int((dados.get("metadata") or {}).get("total", 0) or 0)
        hits = dados.get("hits", []) or []
        for d in hits:
            tipos = d.get("types") or []
            src = d.get("source") or {}
            regs.append({
                "titulo": _txt(d.get("title")),
                "autores": "; ".join(a.get("displayName", "") or a.get("wosStandard", "")
                                     for a in (d.get("names") or {}).get("authors", [])),
                "ano": str(src.get("publishYear", "")), "doi": ((d.get("identifiers") or {}).get("doi") or "").lower(),
                "resumo": "",
                "palavras_chave": "; ".join((d.get("keywords") or {}).get("authorKeywords", []) or []),
                "veiculo": _txt(src.get("sourceTitle")),
                "tipo_doc": TIPOS_WOS.get(tipos[0], tipos[0].lower()) if tipos else "",
                "idioma": "", "url": (d.get("links") or {}).get("record", ""),
            })
        progresso(len(regs), total)
        if not hits or len(regs) >= min(total, maximo):
            break
        pagina += 1
        time.sleep(1.1)
    return total, regs[:maximo], paginas, ["A WoS Starter API não devolve resumos: use 'Completar resumos' antes da triagem."]


def executar(base_id, query, cfg, progresso=lambda n, t: None, filtros=None):
    chaves = cfg.get("chaves", {})
    maximo = int(cfg.get("api_max_registros", 5000) or 5000)
    if base_id == "scopus":
        return _scopus(query, chaves, maximo, progresso)
    if base_id == "ieee":
        return _ieee(query, chaves, maximo, progresso, filtros)
    if base_id == "wos":
        return _wos(query, chaves, maximo, progresso)
    raise ErroAPI("Esta base não tem API de busca; use a exportação do site (RIS, BibTeX ou CSV).")


def chave_configurada(base_id, cfg) -> bool:
    return bool((cfg.get("chaves") or {}).get({"scopus": "scopus", "ieee": "ieee", "wos": "wos"}.get(base_id, "-")))


# ---------------- OpenAlex (resumos) ----------------

def resumo_openalex(doi: str, email: str = ""):
    params = {"mailto": email} if email else None
    try:
        r = requests.get(f"https://api.openalex.org/works/doi:{doi}", params=params, timeout=30)
    except requests.RequestException:
        return ""
    if r.status_code != 200:
        return ""
    idx = (r.json() or {}).get("abstract_inverted_index") or {}
    if not idx:
        return ""
    posicoes = []
    for palavra, pos in idx.items():
        for p in pos:
            posicoes.append((p, palavra))
    return " ".join(w for _, w in sorted(posicoes))
