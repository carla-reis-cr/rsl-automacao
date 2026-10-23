"""Seleção: deduplicação, resumos, calibração, decisões, notas de lote e de estudo, PRISMA."""
import json
import random
import threading
from collections import Counter
from pathlib import Path

from . import apis, ia, metricas, ris
from . import protocolo as P
from .projeto import norm_titulo
from .vault import (agora, anexar, escrever_atomico, escrever_nota, hoje, ler_frontmatter, md_escape_tabela,
                    nome_arquivo_seguro)

TAM_LOTE = 50
DECISOES = ("incluir", "excluir", "duvida")
ROTULO = {"incluir": "Incluir", "excluir": "Excluir", "duvida": "Dúvida", "": "Pendente", None: "Pendente"}


# ---------------- conjunto em triagem ----------------

def pool(proj, registros=None):
    regs = registros if registros is not None else proj.registros
    return [r for r in regs if not r.get("duplicado_de")]


def calib(proj):
    return proj.carregar("calibracao", {})


def sugestao_visivel(r, cal) -> bool:
    """Na calibração, a sugestão só aparece depois que a amostra foi avaliada."""
    if r.get("calibracao") and cal.get("estado") != "avaliada":
        return False
    return bool(r.get("sug_decisao"))


# ---------------- deduplicação ----------------

def deduplicar(proj):
    with proj.lock:
        regs = proj.registros
        ordem_base = {b: i for i, b in enumerate(proj.protocolo.get("bases", []))}
        ordenados = sorted(regs, key=lambda r: (0 if r.get("dec_decisao") else 1, ordem_base.get(r.get("base_id"), 99), r["id"]))
        por_doi, por_titulo = {}, {}
        pares = []
        for r in ordenados:
            if not r.get("dec_decisao"):
                r["duplicado_de"] = ""
            chave_t = (norm_titulo(r.get("titulo", "")), r.get("ano", ""))
            alvo = None
            if r.get("doi") and r["doi"] in por_doi:
                alvo, motivo = por_doi[r["doi"]], "DOI"
            elif chave_t[0] and chave_t in por_titulo:
                alvo, motivo = por_titulo[chave_t], "título e ano"
            elif chave_t[0] and not chave_t[1]:
                for (t, _a), rid in por_titulo.items():
                    if t == chave_t[0]:
                        alvo, motivo = rid, "título (sem ano)"
                        break
            if alvo and not r.get("dec_decisao"):
                r["duplicado_de"] = alvo
                pares.append((r["id"], alvo, motivo))
                continue
            if r.get("doi"):
                por_doi.setdefault(r["doi"], r["id"])
            if chave_t[0]:
                por_titulo.setdefault(chave_t, r["id"])
        proj.salvar("registros", regs)
        idx = {r["id"]: r for r in regs}
        crit = P.criterio_dup(proj.protocolo)
        L = ["# Deduplicação\n",
             f"Critério {crit}. Regra: mesmo DOI, ou mesmo título normalizado com o mesmo ano. "
             "Mantém-se o registro da base que aparece primeiro na ordem do protocolo.\n",
             f"- Registros identificados (buscas definitivas): **{len(regs)}**",
             f"- Duplicatas removidas: **{len(pares)}**",
             f"- Registros únicos para triagem: **{len(regs) - len(pares)}**",
             f"- Executado em {agora()}\n",
             "| Removido | Base | Mantido | Base | Motivo | Título |", "|---|---|---|---|---|---|"]
        for rid, alvo, motivo in pares:
            a, b = idx[rid], idx[alvo]
            L.append(f"| {rid} | {a.get('base', '')} | {alvo} | {b.get('base', '')} | {motivo} | {md_escape_tabela(a.get('titulo', ''))[:120]} |")
        escrever_nota(proj.p("selecao") / "Deduplicação.md", {"tipo": "deduplicacao", "identificados": len(regs),
                                                               "duplicatas": len(pares)}, "\n".join(L))
        proj.log("Deduplicação", f"{len(pares)} duplicatas de {len(regs)} registros")
        atualizar_prisma(proj)
        return len(regs), len(pares)


# ---------------- completar resumos (OpenAlex) ----------------

_oa = {}


def status_resumos(slug):
    return dict(_oa.get(slug, {"ativa": False}))


def completar_resumos(proj_fn, slug, email):
    if _oa.get(slug, {}).get("ativa"):
        raise RuntimeError("Já está completando resumos.")
    proj = proj_fn()
    alvos = [r["id"] for r in pool(proj) if r.get("doi") and not r.get("resumo")]
    est = {"ativa": True, "feitos": 0, "achados": 0, "total": len(alvos), "erro": ""}
    _oa[slug] = est

    def rodar():
        try:
            achados = {}
            for i, rid in enumerate(alvos, 1):
                pr = proj_fn()
                doi = next((r["doi"] for r in pr.registros if r["id"] == rid), "")
                txt = apis.resumo_openalex(doi, email)
                if txt:
                    achados[rid] = txt
                est["feitos"] = i
                if len(achados) >= 20 or i == len(alvos):
                    with pr.lock:
                        todos = pr.registros
                        for r in todos:
                            if r["id"] in achados:
                                r["resumo"], r["resumo_fonte"] = achados[r["id"]], "openalex"
                        pr.salvar("registros", todos)
                    est["achados"] += len(achados)
                    achados = {}
            proj_fn().log("Resumos completados via OpenAlex", f"{est['achados']} de {len(alvos)} registros sem resumo")
        except Exception as ex:  # noqa: BLE001
            est["erro"] = str(ex)
        finally:
            est["ativa"] = False

    threading.Thread(target=rodar, daemon=True).start()


# ---------------- calibração ----------------

def preparar_calibracao(proj, n: int, semente: int):
    with proj.lock:
        cal = calib(proj)
        if cal.get("ids"):
            raise ValueError("A calibração já foi preparada.")
        regs = proj.registros
        candidatos = [r for r in pool(proj, regs) if not r.get("dec_decisao") and not r.get("sug_decisao")]
        if len(candidatos) < n:
            raise ValueError(f"Há apenas {len(candidatos)} registros disponíveis para a amostra.")
        rng = random.Random(semente)
        ids = sorted(r["id"] for r in rng.sample(candidatos, n))
        for r in regs:
            if r["id"] in ids:
                r["calibracao"] = True
        proj.salvar("registros", regs)
        cal = {"n": n, "semente": semente, "ids": ids, "preparada_em": agora(), "estado": "triagem-humana"}
        proj.salvar("calibracao", cal)
        proj.decisao(f"Calibração da triagem assistida: amostra aleatória de {n} registros (semente {semente})",
                     "medir concordância e sensibilidade da IA antes de usá-la como apoio")
        proj.log("Calibração preparada", f"{n} registros, semente {semente}")
        renderizar_calibracao(proj)
        return cal


def pendentes_calibracao(proj):
    cal = calib(proj)
    regs = {r["id"]: r for r in proj.registros}
    return [i for i in cal.get("ids", []) if not regs.get(i, {}).get("dec_decisao")]


def concluir_calibracao(proj, est=None):
    """Chamado ao fim da tarefa de IA da amostra: calcula métricas e libera as sugestões."""
    with proj.lock:
        cal = calib(proj)
        regs = {r["id"]: r for r in proj.registros}
        itens = [(regs[i]["dec_decisao"], regs[i]["sug_decisao"]) for i in cal.get("ids", [])
                 if regs.get(i, {}).get("dec_decisao") and regs.get(i, {}).get("sug_decisao")]
        if len(itens) < len(cal.get("ids", [])):
            cal["estado"] = "triagem-humana"
            proj.salvar("calibracao", cal)
            renderizar_calibracao(proj)
            return None
        m = metricas.calibracao(itens)
        cal.update({"estado": "avaliada", "avaliada_em": agora(), "metricas": m,
                    "modelo": next((regs[i].get("sug_modelo") for i in cal["ids"] if regs[i].get("sug_modelo")), ""),
                    "prompt_hash": ia.prompt_hash(proj.protocolo)})
        proj.salvar("calibracao", cal)
        proj.log("Calibração avaliada", f"Kappa {m['kappa']:.2f}; sensibilidade {m['sensibilidade'] if m['sensibilidade'] is None else round(m['sensibilidade'], 2)}")
        renderizar_calibracao(proj)
        for lote in {lote_de(proj, i) for i in cal["ids"]}:
            renderizar_lote(proj, lote)
        return m


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def renderizar_calibracao(proj):
    cal = calib(proj)
    p = proj.protocolo
    L = ["# Calibração da triagem assistida\n"]
    if not cal.get("ids"):
        L.append("_Ainda não preparada._")
    else:
        L.append(f"- Amostra aleatória: **{cal['n']}** registros (semente {cal['semente']}), preparada em {cal['preparada_em']}.")
        L.append("- Procedimento: a pesquisadora triou a amostra **sem ver** as sugestões; depois a IA avaliou os mesmos registros.")
        L.append(f"- Estado: **{cal.get('estado')}**\n")
        m = cal.get("metricas")
        if m:
            L.append(f"Modelo: `{cal.get('modelo', '')}` · versão do prompt (hash): `{cal.get('prompt_hash', '')}` · avaliada em {cal.get('avaliada_em', '')}\n")
            L.append("Comparação binária: **encaminhar** (incluir ou dúvida) × **excluir**.\n")
            L.append("| | IA encaminha | IA exclui |\n|---|---|---|")
            L.append(f"| **Humana encaminha** | {m['vp']} | {m['fn']} |")
            L.append(f"| **Humana exclui** | {m['fp']} | {m['vn']} |\n")
            L.append(f"- Concordância: **{_pct(m['concordancia'])}**")
            L.append(f"- Kappa de Cohen: **{m['kappa']:.3f}** ({m['kappa_interpretacao']})" if m["kappa"] is not None else "- Kappa: —")
            L.append(f"- Sensibilidade (estudos encaminhados pela pesquisadora que a IA também encaminhou): **{_pct(m['sensibilidade'])}**")
            L.append(f"- Especificidade: **{_pct(m['especificidade'])}**")
            if m.get("kappa_3") is not None:
                L.append(f"- Kappa considerando as três categorias: {m['kappa_3']:.3f} ({m['kappa_3_interpretacao']})")
            L.append("\n> [!warning] Interpretação\n> A sensibilidade é a métrica mais importante: indica quantos estudos relevantes a IA deixaria escapar. "
                     "Como toda decisão final é humana, a IA serve para apoiar a leitura, não para excluir sozinha.\n")
            regs = {r["id"]: r for r in proj.registros}
            div = [i for i in cal["ids"] if metricas.encaminha(regs[i].get("dec_decisao")) != metricas.encaminha(regs[i].get("sug_decisao"))]
            if div:
                L.append("## Divergências\n")
                L.append("| ID | Humana | IA | Critérios IA | Justificativa IA | Título |\n|---|---|---|---|---|---|")
                for i in div:
                    r = regs[i]
                    L.append(f"| {i} | {ROTULO[r.get('dec_decisao')]} | {ROTULO[r.get('sug_decisao')]} | {', '.join(r.get('sug_criterios') or [])} | "
                             f"{md_escape_tabela(r.get('sug_justificativa', ''))} | {md_escape_tabela(r.get('titulo', ''))[:100]} |")
                L.append("")
    L.append("## Prompt usado\n")
    L.append(f"Hash atual: `{ia.prompt_hash(p)}`\n")
    L.append("```text\n" + ia.montar_prompt(p) + "\n```")
    escrever_nota(proj.p("selecao") / "Calibração.md", {"tipo": "calibracao", "estado": cal.get("estado", "nao-preparada"),
                                                        "n": cal.get("n"), "kappa": (cal.get("metricas") or {}).get("kappa"),
                                                        "sensibilidade": (cal.get("metricas") or {}).get("sensibilidade")}, "\n".join(L))


# ---------------- decisões ----------------

def criterios_validos(p):
    return [c["id"] for c in p.get("criterios_inclusao", []) + p.get("criterios_exclusao", [])]


def decidir(proj, rid, decisao, criterios, nota):
    if decisao not in DECISOES:
        raise ValueError("Decisão inválida.")
    validos = criterios_validos(proj.protocolo)
    criterios = [c for c in criterios if c in validos]
    if decisao == "excluir" and not criterios:
        raise ValueError("Para excluir, marque ao menos um critério.")
    with proj.lock:
        regs = proj.registros
        cal = calib(proj)
        r = next((x for x in regs if x["id"] == rid), None)
        if r is None:
            raise ValueError("Registro não encontrado.")
        if r.get("duplicado_de"):
            raise ValueError("Registro marcado como duplicata.")
        antes = r.get("dec_decisao", "")
        r.update({"dec_decisao": decisao, "dec_criterios": criterios, "dec_nota": nota.strip(), "dec_data": agora()})
        proj.salvar("registros", regs)
        auditoria = {"quando": agora(), "id": rid, "antes": antes, "depois": decisao, "criterios": criterios,
                     "calibracao": bool(r.get("calibracao")), "sugestao_visivel": sugestao_visivel(r, cal),
                     "sugestao": r.get("sug_decisao", "") if sugestao_visivel(r, cal) else ""}
        anexar(proj.p("dados") / "decisoes.jsonl", json.dumps(auditoria, ensure_ascii=False))
    renderizar_lote(proj, lote_de(proj, rid))


def lote_de(proj, rid) -> int:
    ids = sorted(r["id"] for r in pool(proj))
    return ids.index(rid) // TAM_LOTE + 1 if rid in ids else 0


def renderizar_lote(proj, n: int):
    if n <= 0:
        return
    cal = calib(proj)
    regs = sorted(pool(proj), key=lambda r: r["id"])
    fatia = regs[(n - 1) * TAM_LOTE: n * TAM_LOTE]
    if not fatia:
        return
    cont = Counter(r.get("dec_decisao") or "pendente" for r in fatia)
    L = [f"# Triagem — lote {n:03d}\n",
         f"Registros {fatia[0]['id']} a {fatia[-1]['id']}. Gerado pelo app a cada decisão; as decisões são tomadas na interface do app.\n",
         f"Incluídos: {cont.get('incluir', 0)} · Excluídos: {cont.get('excluir', 0)} · Dúvida: {cont.get('duvida', 0)} · Pendentes: {cont.get('pendente', 0)}\n"]
    for r in fatia:
        L.append(f"## {r['id']} · {md_escape_tabela(r.get('titulo', '(sem título)'))}\n")
        L.append(f"- **Autores:** {r.get('autores', '')[:300]}")
        L.append(f"- **Ano:** {r.get('ano', '')} · **Base:** {r.get('base', '')} · **Tipo:** {r.get('tipo_doc', '')} · **DOI:** {r.get('doi', '')}")
        if r.get("palavras_chave"):
            L.append(f"- **Palavras-chave:** {r['palavras_chave']}")
        if r.get("calibracao"):
            L.append("- 🎯 Registro da amostra de calibração")
        L.append("")
        resumo = r.get("resumo") or "_(sem resumo)_"
        fonte = " (via OpenAlex)" if r.get("resumo_fonte") == "openalex" else ""
        L.append(f"> [!abstract]- Resumo{fonte}\n> " + resumo.replace("\n", " ") + "\n")
        if sugestao_visivel(r, cal):
            crit_ia = (" — " + ", ".join(r["sug_criterios"])) if r.get("sug_criterios") else ""
            L.append(f"> [!tip] Sugestão da IA: {ROTULO[r['sug_decisao']]}{crit_ia} (confiança {r.get('sug_confianca', '')})\n"
                     f"> {r.get('sug_justificativa', '')}\n> `{r.get('sug_modelo', '')}` · prompt `{r.get('sug_prompt_hash', '')}` · {r.get('sug_data', '')}\n")
        if r.get("dec_decisao"):
            crit = ", ".join(r.get("dec_criterios") or [])
            L.append(f"**Decisão:** {ROTULO[r['dec_decisao']]}{' — ' + crit if crit else ''} ({r.get('dec_data', '')})")
            if r.get("dec_nota"):
                L.append(f"\n**Nota:** {r['dec_nota']}")
        else:
            L.append("**Decisão:** pendente")
        L.append("\n---\n")
    escrever_nota(proj.p("triagem") / f"Lote {n:03d}.md",
                  {"tipo": "lote-triagem", "lote": n, "incluir": cont.get("incluir", 0), "excluir": cont.get("excluir", 0),
                   "duvida": cont.get("duvida", 0), "pendentes": cont.get("pendente", 0)}, "\n".join(L), preservar_notas=False)


def renderizar_todos_lotes(proj):
    total = len(pool(proj))
    for n in range(1, (total + TAM_LOTE - 1) // TAM_LOTE + 1):
        renderizar_lote(proj, n)


# ---------------- notas de estudo (extração) ----------------

def gerar_notas_estudos(proj):
    p = proj.protocolo
    criados = 0
    existentes = {ler_frontmatter(f.read_text(encoding="utf-8"))[0].get("id") for f in proj.p("estudos").glob("*.md")}
    for r in pool(proj):
        if r.get("dec_decisao") not in ("incluir", "duvida") or r["id"] in existentes:
            continue
        props = {"tipo": "estudo", "id": r["id"], "titulo": r.get("titulo", ""), "autores": r.get("autores", ""),
                 "ano": r.get("ano", ""), "doi": r.get("doi", ""), "base": r.get("base", ""), "veiculo": r.get("veiculo", ""),
                 "triagem": r.get("dec_decisao"), "leitura_completa": "pendente", "motivo_exclusao": ""}
        for q in p.get("qualidade", []):
            props[f"q_{q['id']}"] = ""
        if p.get("qualidade"):
            props["qualidade_total"] = ""
        L = [f"# {r.get('titulo', '')}\n",
             f"{r.get('autores', '')} ({r.get('ano', '')}). *{r.get('veiculo', '')}*. DOI: {r.get('doi', '')}\n",
             "> [!info] Preencha `leitura_completa` com **incluir** ou **excluir** (e `motivo_exclusao` com o critério). "
             "Na avaliação de qualidade, use 1, 0.5 ou 0 em cada questão. O app lê essas propriedades para atualizar o PRISMA.\n",
             "## Leitura completa\n"]
        for c in p.get("criterios_inclusao", []) + p.get("criterios_exclusao", []):
            if c.get("aplicacao") != "auto":
                L.append(f"- [ ] **{c['id']}** {c['texto']}")
        if p.get("qualidade"):
            L.append(f"\n## Avaliação de qualidade\n\nPontuação: {p.get('pontuacao', '')}. Nota de corte: {p.get('nota_corte') or 'a definir'}.\n")
            for q in p["qualidade"]:
                L.append(f"- **{q['id']}** {q['texto']}")
        L.append("\n## Extração\n")
        for q in p.get("questoes", []):
            if q.get("tipo") == "SQ":
                continue
            L.append(f"### {q['id']} — {q.get('titulo', '')}\n")
            L.append(f"> {q.get('pergunta', '')}\n")
            L.append("- Achado: \n- Evidência (trecho): \n- Página: \n")
        nome = nome_arquivo_seguro(f"{r['id']} {r.get('titulo', '')}", 70)
        escrever_nota(proj.p("estudos") / f"{nome}.md", props, "\n".join(L))
        criados += 1
    if criados:
        proj.log("Notas de estudo criadas", f"{criados} estudos encaminhados à leitura completa")
    return criados


def ler_estudos(proj):
    out = []
    for f in proj.p("estudos").glob("*.md"):
        props, _ = ler_frontmatter(f.read_text(encoding="utf-8"))
        if props.get("tipo") == "estudo":
            out.append(props)
    return out


# ---------------- PRISMA ----------------

def _num(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def numeros(proj):
    regs = proj.registros
    execs = [e for e in proj.execucoes if e["fase"] == "definitiva"]
    por_base = Counter()
    for e in execs:
        por_base[e["base_nome"]] += e["registros"]
    pl = pool(proj, regs)
    dec = Counter(r.get("dec_decisao") or "pendente" for r in pl)
    crit = Counter()
    for r in pl:
        if r.get("dec_decisao") == "excluir":
            for c in r.get("dec_criterios") or ["?"]:
                crit[c] += 1
    estudos = ler_estudos(proj)
    lc = Counter(str(e.get("leitura_completa") or "pendente").lower() for e in estudos)
    motivos = Counter(str(e.get("motivo_exclusao") or "não informado") for e in estudos if str(e.get("leitura_completa")).lower() == "excluir")
    corte = None
    try:
        corte = float(str(proj.protocolo.get("nota_corte", "")).split()[0].replace(",", "."))
    except (ValueError, IndexError):
        corte = None
    qids = [q["id"] for q in proj.protocolo.get("qualidade", [])]
    qual_ok = qual_baixa = qual_pend = 0
    for e in estudos:
        if str(e.get("leitura_completa")).lower() != "incluir":
            continue
        tot = _num(e.get("qualidade_total"))
        if tot is None and qids:
            vals = [_num(e.get(f"q_{q}")) for q in qids]
            if all(v is not None for v in vals):
                tot = sum(vals)
        if tot is None or corte is None:
            qual_pend += 1
        elif float(tot) >= corte:
            qual_ok += 1
        else:
            qual_baixa += 1
    return {
        "por_base": dict(por_base), "identificados": sum(por_base.values()),
        "duplicatas": len(regs) - len(pl), "triados": len(pl) - dec.get("pendente", 0), "unicos": len(pl),
        "pendentes": dec.get("pendente", 0), "excluidos": dec.get("excluir", 0), "criterios": dict(crit),
        "encaminhados": dec.get("incluir", 0) + dec.get("duvida", 0), "duvida": dec.get("duvida", 0),
        "notas_estudo": len(estudos), "lc_incluir": lc.get("incluir", 0), "lc_excluir": lc.get("excluir", 0),
        "lc_pendente": lc.get("pendente", 0), "lc_motivos": dict(motivos),
        "qual_ok": qual_ok, "qual_baixa": qual_baixa, "qual_pend": qual_pend, "corte": corte,
    }


def atualizar_prisma(proj):
    n = numeros(proj)
    bases_txt = "<br>".join(f"{b} (n = {v})" for b, v in n["por_base"].items()) or "—"
    crit_txt = "<br>".join(f"{c}: {v}" for c, v in sorted(n["criterios"].items())) or "—"
    mot_txt = "<br>".join(f"{c}: {v}" for c, v in sorted(n["lc_motivos"].items())) or "—"
    pend = f"<br>(pendentes: {n['pendentes']})" if n["pendentes"] else ""
    m = [
        "```mermaid", "flowchart TD",
        f'  A["<b>Identificação</b><br>Registros nas bases (n = {n["identificados"]})<br>{bases_txt}"]',
        f'  A --> X1["Duplicatas removidas (n = {n["duplicatas"]})"]',
        f'  A --> B["<b>Triagem</b><br>Registros triados por título e resumo (n = {n["triados"]} de {n["unicos"]}){pend}"]',
        f'  B --> X2["Excluídos (n = {n["excluidos"]})<br>{crit_txt}"]',
        f'  B --> C["Encaminhados à leitura completa (n = {n["encaminhados"]})<br>incluídos: {n["encaminhados"] - n["duvida"]} · dúvida: {n["duvida"]}"]',
        f'  C --> X3["Excluídos na leitura completa (n = {n["lc_excluir"]})<br>{mot_txt}"]',
        f'  C --> D["<b>Elegibilidade</b><br>Aprovados na leitura completa (n = {n["lc_incluir"]})<br>pendentes: {n["lc_pendente"]}"]',
        f'  D --> X4["Abaixo da nota de corte de qualidade (n = {n["qual_baixa"]})"]',
        f'  D --> E["<b>Incluídos</b><br>Estudos na revisão (n = {n["qual_ok"]})<br>qualidade pendente: {n["qual_pend"]}"]',
        "```",
    ]
    L = ["# Fluxo PRISMA 2020\n", f"Atualizado em {agora()}. Números calculados a partir das buscas definitivas, das decisões de triagem e das notas de estudo.\n"]
    L += m
    L.append("\n## Números\n")
    L.append("| Etapa | n |\n|---|---|")
    for rot, chave in (("Identificados nas bases", "identificados"), ("Duplicatas removidas", "duplicatas"),
                       ("Únicos para triagem", "unicos"), ("Triados", "triados"), ("Pendentes de triagem", "pendentes"),
                       ("Excluídos na triagem", "excluidos"), ("Encaminhados à leitura completa", "encaminhados"),
                       ("Excluídos na leitura completa", "lc_excluir"), ("Aprovados na leitura completa", "lc_incluir"),
                       ("Abaixo da nota de corte", "qual_baixa"), ("Incluídos na revisão", "qual_ok")):
        L.append(f"| {rot} | {n[chave]} |")
    L.append("\nRegistros marcados como inelegíveis por ferramentas de automação: **0** (a IA apenas sugere; nenhuma exclusão é automática).")
    escrever_nota(proj.p("selecao") / "PRISMA.md", {"tipo": "prisma", "identificados": n["identificados"], "duplicatas": n["duplicatas"],
                                                     "triados": n["triados"], "excluidos_triagem": n["excluidos"],
                                                     "encaminhados": n["encaminhados"], "incluidos": n["qual_ok"]}, "\n".join(L))
    return n


# ---------------- exportação ----------------

def exportar_ris(proj, filtro: str) -> str:
    regs = pool(proj)
    if filtro == "encaminhados":
        regs = [r for r in regs if r.get("dec_decisao") in ("incluir", "duvida")]
    return ris.escrever(regs)
