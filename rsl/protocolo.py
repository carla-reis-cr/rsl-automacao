"""Modelo do protocolo: leitura do formulário, renderização no vault e versões."""
import copy
import re

import yaml

from . import bases as B
from .vault import md_escape_tabela

APLICACOES = {
    "triagem": "título, resumo e palavras-chave (com sugestão da IA)",
    "auto": "aplicado automaticamente pelo app",
    "texto-completo": "somente na leitura completa",
}


def novo(titulo: str) -> dict:
    return {
        "titulo": titulo,
        "versao": 1,
        "versoes": [],
        "diretrizes": "A revisão segue as diretrizes de Kitchenham et al. para revisões sistemáticas em computação, "
                      "considerando os itens aplicáveis do checklist PRISMA 2020.",
        "objetivo": "",
        "cadeia": "",
        "questoes": [],
        "grupos": [{"nome": "", "termos": []}, {"nome": "", "termos": []}],
        "bases": list(B.ORDEM_PADRAO),
        "campos_busca": list(B.CAMPOS_BUSCA),
        "filtros": {"idioma": "English", "tipos": ["article", "conference", "review"], "ano_inicio": None, "ano_fim": None},
        "strings_personalizadas": {},
        "criterios_inclusao": [],
        "criterios_exclusao": [{"id": "EC?", "texto": "O estudo é duplicado", "aplicacao": "auto"}],
        "qualidade": [],
        "pontuacao": "Sim = 1; Parcial = 0,5; Não = 0",
        "nota_corte": "",
        "extracao_extra": "",
    }


# ---------- leitura do formulário (linhas com "|") ----------

def _linhas(texto: str):
    for ln in (texto or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            yield [p.strip() for p in ln.split("|")]


def tipo_questao(qid: str) -> str:
    m = re.match(r"([A-Za-z]+)", qid or "")
    return m.group(1).upper() if m else "Q"


def ler_questoes(texto: str):
    out = []
    for p in _linhas(texto):
        p += [""] * (4 - len(p))
        out.append({"id": p[0], "tipo": tipo_questao(p[0]), "titulo": p[1], "pergunta": p[2], "traducao": p[3]})
    return out


def ler_criterios(texto: str):
    out = []
    for p in _linhas(texto):
        p += [""] * (3 - len(p))
        apl = p[2].lower().strip() or "triagem"
        if apl not in APLICACOES:
            apl = "triagem"
        out.append({"id": p[0], "texto": p[1], "aplicacao": apl})
    return out


def ler_qualidade(texto: str):
    out = []
    for p in _linhas(texto):
        p += [""] * (2 - len(p))
        out.append({"id": p[0], "texto": p[1]})
    return out


def ler_termos(texto: str):
    """Aceita um termo por linha ou um bloco colado como ( "a" OR "b" )."""
    t = (texto or "").replace("\r", "")
    t = re.sub(r"^\s*\(|\)\s*$", "", t.strip())
    partes = re.split(r"\s+OR\s+|\n", t, flags=re.IGNORECASE)
    termos = []
    for p in partes:
        p = p.strip().strip("()").strip()
        p = re.sub(r"\s+AND\s*$", "", p, flags=re.IGNORECASE).strip()
        p = B.limpar_termo(p)
        if p and p.upper() not in ("AND", "OR"):
            termos.append(p)
    return termos


def questoes_txt(qs):
    return "\n".join(" | ".join([q["id"], q.get("titulo", ""), q.get("pergunta", ""), q.get("traducao", "")]).rstrip(" |") for q in qs)


def criterios_txt(cs):
    return "\n".join(f"{c['id']} | {c['texto']}" + (f" | {c['aplicacao']}" if c.get("aplicacao") not in (None, "", "triagem") else "") for c in cs)


def qualidade_txt(qs):
    return "\n".join(f"{q['id']} | {q['texto']}" for q in qs)


def do_formulario(form, atual: dict) -> dict:
    p = copy.deepcopy(atual)
    p["titulo"] = form.get("titulo", "").strip() or p["titulo"]
    for campo in ("diretrizes", "objetivo", "cadeia", "pontuacao", "nota_corte", "extracao_extra"):
        p[campo] = form.get(campo, "").strip()
    p["questoes"] = ler_questoes(form.get("questoes", ""))
    grupos = []
    i = 0
    while f"grupo_nome_{i}" in form:
        nome = form.get(f"grupo_nome_{i}", "").strip()
        termos = ler_termos(form.get(f"grupo_termos_{i}", ""))
        if nome or termos:
            grupos.append({"nome": nome or f"Grupo {len(grupos) + 1}", "termos": termos})
        i += 1
    p["grupos"] = grupos
    p["bases"] = [b for b in B.ORDEM_PADRAO if form.get(f"base_{b}")]
    p["campos_busca"] = [c for c in B.CAMPOS_BUSCA if form.get(f"campo_{c}")] or list(B.CAMPOS_BUSCA)
    anos = lambda v: int(v) if str(v).strip().isdigit() else None
    p["filtros"] = {
        "idioma": form.get("idioma", "").strip(),
        "tipos": [t for t in B.TIPOS_DOC if form.get(f"tipo_{t}")],
        "ano_inicio": anos(form.get("ano_inicio", "")),
        "ano_fim": anos(form.get("ano_fim", "")),
    }
    p["criterios_inclusao"] = ler_criterios(form.get("criterios_inclusao", ""))
    p["criterios_exclusao"] = ler_criterios(form.get("criterios_exclusao", ""))
    p["qualidade"] = ler_qualidade(form.get("qualidade", ""))
    return p


def problemas(p: dict):
    """Pendências que impedem ou fragilizam as etapas seguintes."""
    out = []
    if not p.get("questoes"):
        out.append("Nenhuma questão de pesquisa definida.")
    if len([g for g in p.get("grupos", []) if g.get("termos")]) < 1:
        out.append("Nenhum grupo de termos definido.")
    if not p.get("bases"):
        out.append("Nenhuma base selecionada.")
    if not p.get("criterios_inclusao") and not p.get("criterios_exclusao"):
        out.append("Nenhum critério de seleção definido.")
    ids = [c["id"] for c in p.get("criterios_inclusao", []) + p.get("criterios_exclusao", [])]
    if len(ids) != len(set(ids)):
        out.append("Há critérios com o mesmo código.")
    if p.get("qualidade") and not str(p.get("nota_corte", "")).strip():
        out.append("Nota de corte da avaliação de qualidade não definida.")
    return out


def criterio_dup(p: dict):
    for c in p.get("criterios_exclusao", []):
        if c.get("aplicacao") == "auto":
            return c["id"]
    return "duplicata"


# ---------- renderização ----------

def renderizar(p: dict, estado: str) -> str:
    L = []
    L.append("# Protocolo de Revisão Sistemática da Literatura\n")
    L.append(f"**Título:** *{p['titulo']}*\n")
    L.append(f"> [!info] Gerado pelo RSL Automação a partir de `_dados/protocolo.yaml` — edite pelo app.\n> Versão {p.get('versao', 1)} · {estado}\n")

    L.append("## 1. Objetivo\n")
    L.append((p.get("objetivo") or "_A definir._") + "\n")
    if p.get("cadeia"):
        L.append(f"**Cadeia lógica:** {p['cadeia']}\n")
    L.append(p.get("diretrizes", "") + "\n")

    L.append("## 2. Questões de pesquisa\n")
    if p.get("questoes"):
        L.append("| Código | Questão | Pergunta |\n|---|---|---|")
        for q in p["questoes"]:
            perg = md_escape_tabela(q.get("pergunta", ""))
            if q.get("traducao"):
                perg += f"<br>*({md_escape_tabela(q['traducao'])})*"
            L.append(f"| {q['id']} | **{md_escape_tabela(q.get('titulo', ''))}** | {perg} |")
        L.append("")
    else:
        L.append("_A definir._\n")

    L.append("## 3. Processo de busca\n")
    grupos = [g for g in p.get("grupos", []) if g.get("termos")]
    if grupos:
        L.append("A busca seleciona estudos que contenham pelo menos um termo de cada grupo.\n")
        L.append("| Termo principal | Termos alternativos |\n|---|---|")
        for i, g in enumerate(grupos):
            sufixo = "<br>AND" if i < len(grupos) - 1 else ""
            L.append(f"| {md_escape_tabela(g['nome'])} | {md_escape_tabela(B.grupo(g['termos']))}{sufixo} |")
        L.append("")
    L.append(f"**Campos da busca:** {B.campos_texto(p)}. Nas bases que não permitem restringir o campo, vale o que consta na tabela abaixo.\n")
    L.append("**Bases e campos de busca** (a confirmar nas buscas piloto):\n")
    L.append("| Base | Campos | Execução |\n|---|---|---|")
    for b in p.get("bases", []):
        info = B.BASES[b]
        exe = "API ou exportação manual" if info["api"] else f"exportação manual ({info.get('exportacao', 'RIS')})"
        L.append(f"| {info['nome']} | {md_escape_tabela(info['campos'])} | {exe} |")
    L.append("")
    f = p.get("filtros") or {}
    L.append(f"**Filtros:** {B._filtros_texto(f)}. As strings por base estão em [[Strings por base]].\n")
    if p.get("historico_strings"):
        L.append("**Histórico de mudanças na string**\n")
        L.append("| Data | Motivo |\n|---|---|")
        for h in p["historico_strings"]:
            L.append(f"| {h.get('data', '')} | {md_escape_tabela(h.get('motivo', ''))} |")
        L.append("")

    L.append("## 4. Seleção dos estudos\n")
    L.append("Serão selecionados os estudos que atenderem a todos os critérios de inclusão e a nenhum critério de exclusão.\n")
    for titulo, chave in (("Critérios de inclusão", "criterios_inclusao"), ("Critérios de exclusão", "criterios_exclusao")):
        L.append(f"**{titulo}**\n")
        for c in p.get(chave, []):
            L.append(f"- **{c['id']}:** {c['texto']} _(aplicação: {APLICACOES.get(c.get('aplicacao', 'triagem'))})_")
        L.append("")
    L.append("**Fases**\n")
    L.append("1. **Busca:** execução das strings nas bases (via API quando disponível, ou exportação RIS), com registro da data, string exata, filtros, número de resultados e hash dos arquivos.")
    L.append(f"2. **Remoção de duplicatas** ({criterio_dup(p)}): por DOI e por título normalizado com o mesmo ano.")
    L.append("3. **Triagem por título, resumo e palavras-chave:** decisão humana registro a registro, com apoio de sugestões de IA generativa (ver seção 7).")
    L.append("4. **Leitura completa:** reavaliação dos critérios no texto integral.")
    L.append("5. **Avaliação de qualidade:** checklist abaixo, com nota de corte.\n")

    L.append("## 5. Avaliação de qualidade\n")
    if p.get("qualidade"):
        L.append(f"Pontuação: {p.get('pontuacao', '')}.\n")
        for q in p["qualidade"]:
            L.append(f"- **{q['id']}:** {q['texto']}")
        L.append(f"\nNota de corte: {p.get('nota_corte') or '_a definir_'}.\n")
    else:
        L.append("_A definir._\n")

    L.append("## 6. Extração e síntese\n")
    fqs = [q for q in p.get("questoes", []) if q.get("tipo") not in ("SQ",)]
    if fqs:
        L.append("O formulário de extração (uma nota por estudo em `03 Estudos/`) contém um campo para cada questão:\n")
        for q in fqs:
            L.append(f"- **{q['id']}** — {q.get('titulo', '')}")
        L.append("")
    sqs = [q for q in p.get("questoes", []) if q.get("tipo") == "SQ"]
    if sqs:
        L.append("As questões estatísticas (" + ", ".join(q["id"] for q in sqs) + ") são respondidas a partir dos metadados dos estudos incluídos.\n")
    if p.get("extracao_extra"):
        L.append(p["extracao_extra"] + "\n")

    L.append("## 7. Ferramentas e automação\n")
    L.append("O processo é registrado pelo RSL Automação diretamente neste vault. A triagem por título e resumo usa IA generativa apenas como **sugestão**: "
             "cada registro recebe uma sugestão (incluir, excluir ou dúvida) com o critério e a justificativa, e **a decisão final é sempre humana**. "
             "Antes do uso, a ferramenta é calibrada contra uma amostra triada às cegas pela pesquisadora, com cálculo de concordância (Kappa de Cohen) e sensibilidade. "
             "O modelo, a versão do prompt (hash) e a data de cada sugestão ficam registrados. Ver [[Calibração]] e [[PRISMA]].\n")
    return "\n".join(L)


def carregar_yaml(texto: str) -> dict:
    p = yaml.safe_load(texto) or {}
    base = novo(p.get("titulo", "Sem título"))
    base.update(p)
    return base


def para_yaml(p: dict) -> str:
    return yaml.safe_dump(p, allow_unicode=True, sort_keys=False, width=1000)
