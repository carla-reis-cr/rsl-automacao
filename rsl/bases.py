"""Bases bibliográficas: sintaxe de string de busca e capacidades.

As strings geradas são um PONTO DE PARTIDA a partir da tabela de termos do protocolo.
Cada base tem particularidades que devem ser confirmadas nas buscas piloto; a string
efetivamente executada é a que fica registrada em cada execução.
"""
import re

TIPOS_DOC = {
    "article": "Artigo de periódico",
    "conference": "Artigo de conferência",
    "review": "Revisão",
    "chapter": "Capítulo de livro",
}

CAMPOS_BUSCA = {
    "titulo": "título",
    "resumo": "resumo",
    "palavras": "palavras-chave do autor",
}

BASES = {
    "acm": {
        "nome": "ACM Digital Library",
        "url": "https://dl.acm.org/search/advanced",
        "api": False,
        "exportacao": "BibTeX",
        "campos": "Título, resumo e palavras-chave (considerar 'ACM Guide to Computing Literature')",
    },
    "ieee": {
        "nome": "IEEE Xplore",
        "url": "https://ieeexplore.ieee.org/search/advanced/command",
        "api": True,
        "campos": "Título, resumo e palavras-chave",
    },
    "sciencedirect": {
        "nome": "ScienceDirect",
        "url": "https://www.sciencedirect.com/search",
        "api": False,
        "campos": "Title, abstract or author-specified keywords (máx. 8 conectores booleanos por campo)",
    },
    "springer": {
        "nome": "SpringerLink",
        "url": "https://link.springer.com/advanced-search",
        "api": True,
        "exportacao": "CSV",
        "campos": "Não permite restringir a título/resumo/palavras-chave (busca em todos os metadados)",
    },
    "wiley": {
        "nome": "Wiley Online Library",
        "url": "https://onlinelibrary.wiley.com/search/advanced",
        "api": False,
        "campos": "Title, Abstract e Keywords (uma linha de busca por campo, ligadas por OR)",
    },
    "scopus": {
        "nome": "Scopus",
        "url": "https://www.scopus.com/search/form.uri?display=advanced",
        "api": True,
        "campos": "TITLE-ABS-KEY",
    },
    "wos": {
        "nome": "Web of Science",
        "url": "https://www.webofscience.com/wos/woscc/advanced-search",
        "api": True,
        "campos": "TS (tópico: título, resumo e palavras-chave)",
    },
}

ORDEM_PADRAO = ["acm", "ieee", "sciencedirect", "springer", "wiley", "scopus", "wos"]


def limpar_termo(termo: str) -> str:
    t = termo.strip().strip(",;")
    if len(t) >= 2 and t[0] in "\"'“”" and t[-1] in "\"'“”":
        t = t[1:-1]
    return t.strip()


def termo(t: str, curinga: bool = True) -> str:
    t = limpar_termo(t)
    if not curinga:
        t = t.replace("*", "").replace("?", "")
    return f'"{t}"'


def grupo(termos, curinga: bool = True) -> str:
    return "(" + " OR ".join(termo(t, curinga) for t in termos if limpar_termo(t)) + ")"


EXPANSOES = {
    "competenc": ["competence", "competency"], "abilit": ["ability"], "behavio": ["behavior", "behaviour"],
    "technolog": ["technology"], "educat": ["education"], "organi": ["organization", "organisation"],
    "analy": ["analysis", "analytics"], "personali": ["personalization", "personalisation"],
    "optimi": ["optimization", "optimisation"], "model": ["model"], "agent": ["agent"], "skill": ["skill"],
    "student": ["student"], "learner": ["learner"], "system": ["system"], "tool": ["tool"], "network": ["network"],
}


def expandir_curinga(t: str):
    """Para bases sem curinga: devolve (termos, situação) com situação em {'sem', 'expandido', 'revisar'}."""
    if "*" not in t and "?" not in t:
        return [t], "sem"
    base = t.replace("?", "").rstrip("*")
    if "*" in base:
        return [base.replace("*", "")], "revisar"
    palavras = base.split()
    ultima = palavras[-1].lower() if palavras else ""
    if ultima in EXPANSOES:
        return [" ".join(palavras[:-1] + [e]) for e in EXPANSOES[ultima]], "expandido"
    return [base], ("sem" if ultima in {w for v in EXPANSOES.values() for w in v} else "revisar")


def melhor_divisao(tamanhos, limite_termos=9):
    """Escolhe o tamanho das fatias de cada grupo (soma <= 9 termos = 8 conectores) com menos subconsultas."""
    import itertools
    import math
    n = len(tamanhos)
    melhor, melhor_custo = None, None
    faixa = range(1, limite_termos - n + 2)
    for combo in itertools.product(faixa, repeat=n):
        if sum(combo) > limite_termos:
            continue
        combo = tuple(min(k, t) for k, t in zip(combo, tamanhos))
        custo = math.prod(math.ceil(t / k) for t, k in zip(tamanhos, combo))
        if melhor_custo is None or custo < melhor_custo:
            melhor, melhor_custo = combo, custo
    return list(melhor or [1] * n)


def _grupos_validos(protocolo):
    return [g for g in protocolo.get("grupos", []) if any(limpar_termo(t) for t in g.get("termos", []))]


def _expandir_grupos(grupos):
    """Escreve por extenso os curingas de cada grupo: (termos por grupo, trocas feitas, termos a revisar)."""
    termos_grupos, trocas, revisar = [], [], []
    for g in grupos:
        tg = []
        for t in g["termos"]:
            if not limpar_termo(t):
                continue
            exp, situacao = expandir_curinga(limpar_termo(t))
            if situacao == "expandido":
                trocas.append(f"{limpar_termo(t)} → {', '.join(exp)}")
            elif situacao == "revisar":
                revisar.append(limpar_termo(t))
            tg += [e for e in exp if e not in tg]
        termos_grupos.append(tg)
    return termos_grupos, trocas, revisar


def campos_busca(protocolo: dict) -> list:
    """Campos em que a busca é feita (título, resumo, palavras-chave); sem definição, todos."""
    definidos = protocolo.get("campos_busca")
    campos = [c for c in CAMPOS_BUSCA if c in (definidos or CAMPOS_BUSCA)]
    return campos or list(CAMPOS_BUSCA)


def campos_texto(protocolo: dict) -> str:
    nomes = [CAMPOS_BUSCA[c] for c in campos_busca(protocolo)]
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _filtros_texto(f: dict) -> str:
    partes = []
    if f.get("idioma"):
        partes.append(f"idioma: {f['idioma']}")
    if f.get("tipos"):
        partes.append("tipos: " + ", ".join(TIPOS_DOC.get(t, t) for t in f["tipos"]))
    if f.get("ano_inicio") or f.get("ano_fim"):
        partes.append(f"anos: {f.get('ano_inicio') or '…'}–{f.get('ano_fim') or '…'}")
    return "; ".join(partes) if partes else "nenhum"


def string_generica(protocolo, curinga=True) -> str:
    return " AND ".join(grupo(g["termos"], curinga) for g in _grupos_validos(protocolo))


def gerar(base_id: str, protocolo: dict) -> dict:
    """Devolve {'strings': [...], 'avisos': [...], 'filtros_no_site': str}."""
    grupos = _grupos_validos(protocolo)
    f = protocolo.get("filtros", {}) or {}
    avisos = []
    filtros_site = _filtros_texto(f)
    if not grupos:
        return {"strings": [], "avisos": ["Defina os grupos de termos no protocolo."], "filtros_no_site": filtros_site}

    if base_id == "scopus":
        campos = campos_busca(protocolo)
        rot = {"titulo": "TITLE", "resumo": "ABS", "palavras": "KEY"}
        if len(campos) == len(CAMPOS_BUSCA):
            em_campos = lambda g: f"TITLE-ABS-KEY{g}"
        else:
            em_campos = lambda g: "(" + " OR ".join(f"{rot[c]}{g}" for c in campos) + ")"
        s = " AND ".join(em_campos(grupo(g["termos"])) for g in grupos)
        if f.get("idioma"):
            s += f" AND LANGUAGE({f['idioma'].lower()})"
        mapa = {"article": "ar", "conference": "cp", "review": "re", "chapter": "ch"}
        tipos = [mapa[t] for t in f.get("tipos", []) if t in mapa]
        if tipos:
            s += " AND (" + " OR ".join(f"DOCTYPE({t})" for t in tipos) + ")"
        if f.get("ano_inicio"):
            s += f" AND PUBYEAR > {int(f['ano_inicio']) - 1}"
        if f.get("ano_fim"):
            s += f" AND PUBYEAR < {int(f['ano_fim']) + 1}"
        return {"strings": [s], "avisos": avisos, "filtros_no_site": "já incluídos na string"}

    if base_id == "wos":
        campos = campos_busca(protocolo)
        rot = {"titulo": "TI", "resumo": "AB", "palavras": "AK"}
        if len(campos) == len(CAMPOS_BUSCA):
            em_campos = lambda g: f"TS={g}"
        else:
            em_campos = lambda g: "(" + " OR ".join(f"{rot[c]}={g}" for c in campos) + ")"
        s = " AND ".join(em_campos(grupo(g["termos"])) for g in grupos)
        if f.get("idioma"):
            s += f" AND LA=({f['idioma'].capitalize()})"
        mapa = {"article": "Article", "conference": "Proceedings Paper", "review": "Review", "chapter": "Book Chapter"}
        tipos = [mapa[t] for t in f.get("tipos", []) if t in mapa]
        if tipos:
            s += " AND DT=(" + " OR ".join(tipos) + ")"
        if f.get("ano_inicio") or f.get("ano_fim"):
            s += f" AND PY=({f.get('ano_inicio') or 1900}-{f.get('ano_fim') or 2100})"
        return {"strings": [s], "avisos": avisos, "filtros_no_site": "já incluídos na string"}

    if base_id == "acm":
        # A ACM ignora o curinga dentro de aspas (vira busca literal): as variações vão por extenso.
        termos_grupos, trocas, revisar = _expandir_grupos(grupos)
        # Formato do campo "Edit Query": cada eixo busca nos campos do protocolo; eixos ligados por AND.
        rot = {"titulo": "Title", "resumo": "Abstract", "palavras": "Keyword"}
        campos = [rot[c] for c in campos_busca(protocolo)]
        eixos = []
        for tg in termos_grupos:
            g = grupo(tg, curinga=False)
            eixos.append("(" + " OR ".join(f"{campo}:{g}" for campo in campos) + ")")
        s = " AND ".join(eixos)
        avisos.append("Cole a string inteira no campo 'Edit Query' da Advanced Search (já traz " + ", ".join(campos) + ") "
                      "e escolha 'The ACM Guide to Computing Literature'.")
        if revisar:
            avisos.append("Curinga removido sem expansão conhecida (revise e complete a palavra): " + ", ".join(revisar) + ".")
        return {"strings": [s], "avisos": avisos, "filtros_no_site": filtros_site}

    if base_id == "ieee":
        # Command Search: cada eixo procurado nos campos do protocolo (nomes de campo a confirmar na busca piloto).
        rot = {"titulo": "Document Title", "resumo": "Abstract", "palavras": "Author Keywords"}
        campos = [rot[c] for c in campos_busca(protocolo)]
        eixos = ["(" + " OR ".join(f'"{campo}":{grupo(g["termos"])}' for campo in campos) + ")" for g in grupos]
        avisos.append("Use a 'Command Search'. Os nomes de campo (" + ", ".join(campos) + ") devem ser confirmados na busca piloto; "
                      "a IEEE limita o número de termos e de curingas por busca. Ano e tipo de documento ficam nos filtros do site.")
        return {"strings": [" AND ".join(eixos)], "avisos": avisos, "filtros_no_site": filtros_site}

    if base_id == "sciencedirect":
        # Sem curingas e no máximo 8 conectores booleanos por campo: divide em subconsultas.
        termos_grupos, trocas, revisar = _expandir_grupos(grupos)
        tamanhos = melhor_divisao([len(tg) for tg in termos_grupos])
        fatias = [[tg[i:i + k] for i in range(0, len(tg), k)] for tg, k in zip(termos_grupos, tamanhos)]
        combinacoes = [[]]
        for fs in fatias:
            combinacoes = [c + [f] for c in combinacoes for f in fs]
        strings = [" AND ".join(grupo(c, curinga=False) for c in comb) for comb in combinacoes]
        if len(strings) > 1:
            avisos.append(f"Dividida em {len(strings)} subconsultas (limite de 8 conectores por campo). O resultado é a união; "
                          "as duplicatas entre subconsultas são removidas na deduplicação.")
        if trocas:
            avisos.append("A ScienceDirect não aceita curingas; termos expandidos: " + "; ".join(trocas) + ". Confira se cobrem as variações.")
        if revisar:
            avisos.append("Curinga removido sem expansão conhecida (revise e complete a palavra): " + ", ".join(revisar) + ".")
        return {"strings": strings, "avisos": avisos, "filtros_no_site": filtros_site}

    if base_id == "springer":
        avisos.append("A busca pela interface da SpringerLink não aceita filtros dentro da string: aplique idioma, tipo e período nos filtros do site "
                      "e remova itens 'Preview-Only'. Na busca via API, idioma e período vão como restrições na consulta.")
        return {"strings": [string_generica(protocolo)], "avisos": avisos, "filtros_no_site": filtros_site}

    if base_id == "wiley":
        # Cada campo é uma linha da Advanced Search (sem prefixo "Campo:" na string) e o curinga não vale dentro de aspas.
        termos_grupos, trocas, revisar = _expandir_grupos(grupos)
        s = " AND ".join(grupo(tg, curinga=False) for tg in termos_grupos)
        rot = {"titulo": "Title", "resumo": "Abstract", "palavras": "Keywords"}
        campos = [rot[c] for c in campos_busca(protocolo)]
        avisos.append("Na Advanced Search, use uma linha por campo (" + ", ".join(campos) + "), cada uma com esta string, "
                      "ligadas por OR. Como a Wiley não agrupa linhas, os dois eixos precisam aparecer no mesmo campo.")
        if revisar:
            avisos.append("Curinga removido sem expansão conhecida (revise e complete a palavra): " + ", ".join(revisar) + ".")
        return {"strings": [s], "avisos": avisos, "filtros_no_site": filtros_site}

    return {"strings": [string_generica(protocolo)], "avisos": avisos, "filtros_no_site": filtros_site}


def consulta_api(base_id: str, protocolo: dict, res: dict) -> str:
    """Consulta enviada à API da base (mostrada ao usuário antes de executar).

    Scopus e WoS já trazem os filtros na string. Na IEEE a API busca em todos os metadados (sem sintaxe de campo) e recebe
    o período como parâmetro. Na Springer, idioma e período entram como restrições da própria consulta.
    """
    if base_id == "ieee" and not res.get("personalizada"):
        return string_generica(protocolo)
    consulta = " ".join(res["strings"])
    if base_id == "springer":
        f = protocolo.get("filtros", {}) or {}
        extras = []
        if str(f.get("idioma", "")).lower().startswith("en") and "language:" not in consulta:
            extras.append("language:en")
        if f.get("ano_inicio") and "onlinedatefrom:" not in consulta:
            extras.append(f"onlinedatefrom:{int(f['ano_inicio'])}-01-01")
        if f.get("ano_fim") and "onlinedateto:" not in consulta:
            extras.append(f"onlinedateto:{int(f['ano_fim'])}-12-31")
        if extras:
            consulta = f"({consulta}) AND " + " AND ".join(extras)
    return consulta


def strings_da_base(base_id: str, protocolo: dict) -> dict:
    """Aplica a string personalizada salva no protocolo, se houver."""
    res = gerar(base_id, protocolo)
    personal = (protocolo.get("strings_personalizadas") or {}).get(base_id)
    if personal and personal.strip():
        res = dict(res)
        res["gerada"] = res["strings"]
        res["strings"] = [s.strip() for s in re.split(r"\n\s*\n", personal.strip()) if s.strip()]
        res["personalizada"] = True
    return res
