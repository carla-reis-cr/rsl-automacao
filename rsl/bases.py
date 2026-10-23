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

BASES = {
    "acm": {
        "nome": "ACM Digital Library",
        "url": "https://dl.acm.org/search/advanced",
        "api": False,
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
        "campos": "Não permite restringir a título/resumo/palavras-chave (busca em todos os metadados)",
    },
    "wiley": {
        "nome": "Wiley Online Library",
        "url": "https://onlinelibrary.wiley.com/search/advanced",
        "api": False,
        "campos": "Definir no piloto: resumo ou todos os metadados",
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
        s = " AND ".join(f"TITLE-ABS-KEY{grupo(g['termos'])}" for g in grupos)
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
        s = " AND ".join(f"TS={grupo(g['termos'])}" for g in grupos)
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
        avisos.append("Na busca avançada, restrinja a Title, Abstract e Author Keyword e escolha 'The ACM Guide to Computing Literature'. "
                      "Confirme no piloto como a ACM trata curingas dentro de aspas.")
        return {"strings": [string_generica(protocolo)], "avisos": avisos, "filtros_no_site": filtros_site}

    if base_id == "ieee":
        avisos.append("Use a 'Command Search'. Restrinja a título, resumo e palavras-chave no piloto; a IEEE limita o número de termos e de curingas por busca.")
        return {"strings": [string_generica(protocolo)], "avisos": avisos, "filtros_no_site": filtros_site}

    if base_id == "sciencedirect":
        # Sem curingas e no máximo 8 conectores booleanos por campo: divide em subconsultas.
        termos_grupos, trocas, revisar = [], [], []
        for g in grupos:
            tg = []
            for t in g["termos"]:
                exp, situacao = expandir_curinga(limpar_termo(t))
                if situacao == "expandido":
                    trocas.append(f"{limpar_termo(t)} → {', '.join(exp)}")
                elif situacao == "revisar":
                    revisar.append(limpar_termo(t))
                tg += [e for e in exp if e not in tg]
            termos_grupos.append(tg)
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
        avisos.append("A SpringerLink busca em todos os metadados; aplique o filtro de idioma e remova itens 'Preview-Only'.")
        return {"strings": [string_generica(protocolo)], "avisos": avisos, "filtros_no_site": filtros_site}

    if base_id == "wiley":
        avisos.append("Defina no piloto se a busca será no resumo ou em todos os metadados e registre a decisão.")
        return {"strings": [string_generica(protocolo)], "avisos": avisos, "filtros_no_site": filtros_site}

    return {"strings": [string_generica(protocolo)], "avisos": avisos, "filtros_no_site": filtros_site}


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
