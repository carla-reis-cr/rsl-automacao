"""RSL Automação — interface local no navegador.

Rode com:  python app.py   (abre http://127.0.0.1:5077 no navegador)
"""
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import quote

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_file, url_for)

sys.path.insert(0, str(Path(__file__).parent))

from rsl import VERSAO, apis, ia, ris  # noqa: E402
from rsl import bases as B  # noqa: E402
from rsl import config as C  # noqa: E402
from rsl import latex as L  # noqa: E402
from rsl import protocolo as P  # noqa: E402
from rsl import selecao as S  # noqa: E402
from rsl.projeto import Projeto, listar  # noqa: E402
from rsl.vault import agora, hoje  # noqa: E402

AQUI = Path(__file__).parent
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

_api_status = {}


# ---------------- utilidades ----------------

def cfg():
    return C.carregar()


def raiz():
    return C.raiz_revisoes(cfg())


def projeto(slug) -> Projeto:
    try:
        pr = Projeto(raiz(), slug)
    except RuntimeError:
        abort(404)
    if not pr.arq_protocolo.exists():
        abort(404)
    return pr


def obsidian(caminho: Path) -> str:
    return "obsidian://open?path=" + quote(str(caminho))


@app.context_processor
def contexto():
    return {"VERSAO": VERSAO, "BASES": B.BASES, "TIPOS_DOC": B.TIPOS_DOC, "CAMPOS_BUSCA": B.CAMPOS_BUSCA, "obsidian": obsidian,
            "ROTULO": S.ROTULO, "APLICACOES": P.APLICACOES}


@app.errorhandler(RuntimeError)
def erro_runtime(ex):
    flash(str(ex), "erro")
    return redirect(url_for("configuracoes"))


# ---------------- início e configuração ----------------

@app.route("/")
def inicio():
    c = cfg()
    if not c.get("vault"):
        flash("Primeiro, informe a pasta do seu vault do Obsidian.", "info")
        return redirect(url_for("configuracoes"))
    return render_template("index.html", projetos=listar(raiz()), raiz=raiz())


@app.route("/config", methods=["GET", "POST"])
def configuracoes():
    c = cfg()
    if request.method == "POST":
        vault = request.form.get("vault", "").strip().strip('"')
        if vault and not Path(vault).expanduser().is_dir():
            flash("Essa pasta não existe. Copie o caminho do vault (a pasta que contém a pasta oculta .obsidian).", "erro")
            return redirect(url_for("configuracoes"))
        c["vault"] = vault
        c["pasta_revisoes"] = request.form.get("pasta_revisoes", "Revisões").strip() or "Revisões"
        c["claude_cmd"] = request.form.get("claude_cmd", "claude").strip() or "claude"
        c["claude_modelo"] = request.form.get("claude_modelo", "sonnet").strip() or "sonnet"
        c["ia_registros_por_chamada"] = max(1, min(25, int(request.form.get("ia_registros_por_chamada", 10) or 10)))
        c["api_max_registros"] = max(25, int(request.form.get("api_max_registros", 5000) or 5000))
        c["openalex_email"] = request.form.get("openalex_email", "").strip()
        for k in c["chaves"]:
            v = request.form.get(f"chave_{k}", "")
            if request.form.get(f"limpar_{k}"):
                c["chaves"][k] = ""
            elif v.strip():
                c["chaves"][k] = v.strip()
        C.salvar(c)
        flash("Configurações salvas.", "ok")
        return redirect(url_for("inicio") if c["vault"] else url_for("configuracoes"))
    return render_template("config.html", c=c, arquivo=C.ARQUIVO)


@app.route("/config/testar", methods=["POST"])
def testar_claude():
    try:
        flash("Claude Code: " + ia.verificar(cfg()), "ok")
    except Exception as ex:  # noqa: BLE001
        flash(str(ex), "erro")
    return redirect(url_for("configuracoes"))


# ---------------- protocolo ----------------

def _form_protocolo(p):
    return {
        "questoes": P.questoes_txt(p.get("questoes", [])),
        "criterios_inclusao": P.criterios_txt(p.get("criterios_inclusao", [])),
        "criterios_exclusao": P.criterios_txt(p.get("criterios_exclusao", [])),
        "qualidade": P.qualidade_txt(p.get("qualidade", [])),
    }


@app.route("/novo", methods=["GET", "POST"])
def novo():
    if request.method == "POST":
        p = P.do_formulario(request.form, P.novo(request.form.get("titulo", "Nova revisão")))
        pr = Projeto.criar(raiz(), p, request.form.get("slug", "").strip())
        flash("Projeto criado no vault.", "ok")
        return redirect(url_for("painel", slug=pr.slug))
    p = P.novo("")
    return render_template("protocolo.html", p=p, f=_form_protocolo(p), pr=None)


@app.route("/exemplo", methods=["POST"])
def exemplo():
    p = P.carregar_yaml((AQUI / "exemplos" / "ia-educacao-empreendedora.yaml").read_text(encoding="utf-8"))
    pr = Projeto.criar(raiz(), p, "ia-educacao-empreendedora")
    flash("Projeto criado a partir do protocolo de 19/10/2026.", "ok")
    return redirect(url_for("painel", slug=pr.slug))


@app.route("/p/<slug>/protocolo", methods=["GET", "POST"])
def editar_protocolo(slug):
    pr = projeto(slug)
    if request.method == "POST":
        p = P.do_formulario(request.form, pr.protocolo)
        motivo = request.form.get("motivo", "").strip()
        motivo_string = request.form.get("motivo_string", "").strip()
        if motivo_string:
            p["historico_strings"] = list(p.get("historico_strings") or []) + [{"data": hoje(), "motivo": motivo_string}]
        if pr.congelado and not motivo:
            flash("O protocolo está congelado: informe o motivo da emenda.", "erro")
            return render_template("protocolo.html", p=p, f=_form_protocolo(p), pr=pr)
        pr.salvar_protocolo(p, motivo)
        flash("Protocolo salvo e atualizado no vault.", "ok")
        return redirect(url_for("painel", slug=slug))
    return render_template("protocolo.html", p=pr.protocolo, f=_form_protocolo(pr.protocolo), pr=pr)


def _arq_tex(pr) -> Path:
    return pr.p("protocolo") / "LaTeX" / "Protocolo.tex"


def _gravar_tex(pr) -> str:
    texto = L.protocolo_tex(pr.protocolo, pr.estado())
    destino = _arq_tex(pr)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    return texto


@app.route("/p/<slug>/latex")
def latex_ver(slug):
    pr = projeto(slug)
    arq = _arq_tex(pr)
    gerado_agora = not arq.exists()
    if gerado_agora:
        _gravar_tex(pr)
    texto = arq.read_text(encoding="utf-8")
    atualizado = texto == L.protocolo_tex(pr.protocolo, pr.estado())
    return render_template("latex.html", pr=pr, texto=texto, atualizado=atualizado, gerado_agora=gerado_agora,
                           compilador=L.compilador())


@app.route("/p/<slug>/latex/regenerar", methods=["POST"])
def latex_regenerar(slug):
    _gravar_tex(projeto(slug))
    flash("LaTeX do protocolo atualizado.", "ok")
    return redirect(url_for("latex_ver", slug=slug))


@app.route("/p/<slug>/latex/protocolo")
def latex_protocolo(slug):
    texto = _gravar_tex(projeto(slug))
    return Response(texto, mimetype="application/x-tex",
                    headers={"Content-Disposition": f'attachment; filename="Protocolo-{slug}.tex"'})


@app.route("/p/<slug>/latex/protocolo.pdf")
def pdf_protocolo(slug):
    pr = projeto(slug)
    _gravar_tex(pr)
    try:
        pdf = L.compilar(_arq_tex(pr))
    except RuntimeError as ex:
        flash(str(ex), "erro")
        return redirect(url_for("latex_ver", slug=slug))
    return Response(pdf.read_bytes(), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Protocolo-{slug}.pdf"'})


@app.route("/p/<slug>/congelar", methods=["POST"])
def congelar(slug):
    pr = projeto(slug)
    pr.congelar(request.form.get("motivo", "").strip())
    flash("Protocolo congelado. Uma cópia datada foi salva em 00 Protocolo/Versões.", "ok")
    return redirect(url_for("painel", slug=slug))


# ---------------- painel ----------------

@app.route("/p/<slug>")
def painel(slug):
    pr = projeto(slug)
    execs = pr.execucoes
    regs = pr.registros
    cal = S.calib(pr)
    n = S.numeros(pr)
    return render_template("painel.html", pr=pr, p=pr.protocolo, execs=execs, regs=regs, cal=cal, n=n,
                           problemas=P.problemas(pr.protocolo), ia_status=ia.status(slug))


# ---------------- buscas ----------------

@app.route("/p/<slug>/buscas")
def buscas(slug):
    pr = projeto(slug)
    p = pr.protocolo
    strings = {b: B.strings_da_base(b, p) for b in p.get("bases", [])}
    controle_txt = "\n".join(f"{c['doi']} | {c['titulo']}" if c["doi"] else c["titulo"] for c in pr.controle)
    c = cfg()
    execs = pr.execucoes
    por_base = {}
    diferencas = {}
    for e in reversed(execs):
        por_base.setdefault(e["base_id"], []).append(e)
        total = str(e.get("resultados_site") or "").replace(".", "").replace(",", "").replace(" ", "")
        if total.isdigit() and int(total) != e["registros"]:
            diferencas[e["id"]] = int(total) - e["registros"]
    consultas_api = {b: B.consulta_api(b, p, strings[b]) for b in strings}
    n_fase = {f: sum(1 for e in pr.execucoes if e["fase"] == f) for f in ("piloto", "definitiva")}
    return render_template("buscas.html", pr=pr, p=p, compilador=L.compilador(), strings=strings,
                           relatorios=list(reversed(pr.carregar("relatorios", []))), n_fase=n_fase,
                           titulo_fases=L.titulo_fases, consultas_api=consultas_api, execs_base=por_base, diferencas=diferencas,
                           controle={c["id"]: c for c in pr.controle}, controle_txt=controle_txt,
                           api_ok={b: apis.chave_configurada(b, c) for b in B.BASES}, hoje=hoje(),
                           api_status=_api_status.get(slug, {}))


@app.route("/p/<slug>/relatorios", methods=["POST"])
def gerar_relatorio(slug):
    """Gera o relatório das buscas das fases escolhidas e guarda uma cópia no histórico (arquivos não são sobrescritos)."""
    pr = projeto(slug)
    fases = [f for f in ("piloto", "definitiva") if request.form.get(f"fase_{f}")]
    if not fases:
        flash("Marque ao menos uma fase (piloto ou definitiva) para gerar o relatório.", "erro")
        return redirect(url_for("buscas", slug=slug) + "#relatorios")
    execs = [e for e in pr.execucoes if e["fase"] in fases]
    if not execs:
        flash(f"Não há buscas {L.titulo_fases(fases)} registradas para incluir no relatório.", "erro")
        return redirect(url_for("buscas", slug=slug) + "#relatorios")
    historico = pr.carregar("relatorios", [])
    rid = f"REL{len(historico) + 1:03d}"
    pasta = pr.p("buscas") / "relatorios"
    pasta.mkdir(parents=True, exist_ok=True)
    base = f"{rid}_busca-{'-'.join(fases)}_{agora().replace(':', '').replace(' ', '_')}"
    texto = L.relatorio_buscas_tex(pr.protocolo, pr.execucoes, pr.controle, pr.estado(), hoje(), fases)
    (pasta / f"{base}.tex").write_text(texto, encoding="utf-8")
    item = {"id": rid, "fases": fases, "gerado_em": agora(), "tex": f"{base}.tex", "pdf": None,
            "execucoes": [e["id"] for e in execs], "versao_protocolo": pr.protocolo.get("versao", 1)}
    try:
        L.compilar(pasta / f"{base}.tex")
        item["pdf"] = f"{base}.pdf"
        flash(f"Relatório {rid} ({L.titulo_fases(fases)}) gerado, com PDF.", "ok")
    except RuntimeError as ex:
        flash(f"Relatório {rid} salvo em .tex, mas o PDF não foi gerado: {ex}", "erro")
    historico.append(item)
    pr.salvar("relatorios", historico)
    pr.log("Relatório de buscas gerado", f"{rid}: {L.titulo_fases(fases)}; execuções {', '.join(item['execucoes'])}")
    return redirect(url_for("buscas", slug=slug) + "#relatorios")


@app.route("/p/<slug>/relatorios/<rid>.<formato>")
def baixar_relatorio(slug, rid, formato):
    pr = projeto(slug)
    historico = pr.carregar("relatorios", [])
    item = next((r for r in historico if r["id"] == rid), None)
    if not item or formato not in ("tex", "pdf"):
        abort(404)
    pasta = pr.p("buscas") / "relatorios"
    if formato == "pdf" and not item.get("pdf"):
        try:
            L.compilar(pasta / item["tex"])
        except RuntimeError as ex:
            flash(str(ex), "erro")
            return redirect(url_for("buscas", slug=slug) + "#relatorios")
        item["pdf"] = Path(item["tex"]).with_suffix(".pdf").name
        pr.salvar("relatorios", historico)
    arquivo = pasta / item[formato]
    if not arquivo.exists():
        abort(404)
    return send_file(arquivo, as_attachment=True, download_name=f"{slug}_{arquivo.name}")


@app.route("/p/<slug>/execucoes/<eid>/excluir", methods=["POST"])
def excluir_execucao(slug, eid):
    pr = projeto(slug)
    try:
        res = pr.excluir_execucao(eid, request.form.get("motivo", ""))
    except ValueError as ex:
        flash(str(ex), "erro")
        return redirect(url_for("buscas", slug=slug))
    # Sem os registros removidos, a deduplicação, os lotes de triagem e o PRISMA precisam ser refeitos.
    if res["refazer_dedup"] and (pr.p("selecao") / "Deduplicação.md").exists():
        S.deduplicar(pr)
    if res["registros_removidos"]:
        S.renderizar_todos_lotes(pr)
    S.atualizar_prisma(pr)
    flash(f"Importação {eid} excluída ({res['registros_removidos']} registros removidos). "
          f"Nota e arquivos arquivados em 01 Buscas/excluidas/{eid}.", "ok")
    return redirect(url_for("buscas", slug=slug))


@app.route("/p/<slug>/exportacoes/<eid>/<int:i>")
def baixar_exportacao(slug, eid, i):
    pr = projeto(slug)
    e = next((x for x in pr.execucoes if x["id"] == eid), None)
    if not e or not 0 <= i < len(e.get("arquivos", [])):
        abort(404)
    caminho = pr.p("exportacoes") / e["arquivos"][i]["nome"]
    if not caminho.exists():
        abort(404)
    return send_file(caminho, as_attachment=True, download_name=caminho.name)


@app.route("/p/<slug>/strings/<base>", methods=["POST"])
def salvar_string(slug, base):
    pr = projeto(slug)
    p = pr.protocolo
    texto = request.form.get("string", "").strip()
    gerada = "\n\n".join(B.gerar(base, p)["strings"])
    sp = dict(p.get("strings_personalizadas") or {})
    if not texto or texto == gerada:
        sp.pop(base, None)
    else:
        sp[base] = texto
    novo = dict(p)
    novo["strings_personalizadas"] = sp
    motivo = f"Ajuste da string da base {B.BASES[base]['nome']}"
    pr.salvar_protocolo(novo, motivo)
    if not pr.protocolo.get("congelado"):
        pr.decisao(f"String da {B.BASES[base]['nome']} ajustada", motivo)
    flash(f"String da {B.BASES[base]['nome']} salva.", "ok")
    return redirect(url_for("buscas", slug=slug) + f"#base-{base}")


@app.route("/p/<slug>/importar", methods=["POST"])
def importar(slug):
    pr = projeto(slug)
    arquivos = [(f.filename, f.read()) for f in request.files.getlist("arquivos") if f and f.filename]
    if not arquivos:
        flash("Selecione ao menos um arquivo de exportação (RIS, BibTeX ou CSV).", "erro")
        return redirect(url_for("buscas", slug=slug))
    strings = [s.strip() for s in request.form.get("string", "").split("\n\n") if s.strip()]
    try:
        e = pr.registrar_execucao(request.form["base"], request.form["fase"], request.form.get("data") or hoje(),
                                  strings, request.form.get("resultados_site", "").strip(), arquivos, "manual",
                                  request.form.get("observacoes", "").strip())
        S.atualizar_prisma(pr)
        flash(f"Execução {e['id']} registrada: {e['registros']} registros; controle {len(e['controle_encontrados'])}/{e['controle_total']}.", "ok")
    except ValueError as ex:
        flash(str(ex), "erro")
    return redirect(url_for("buscas", slug=slug))


@app.route("/p/<slug>/api/<base>", methods=["POST"])
def executar_api(slug, base):
    pr = projeto(slug)
    if _api_status.get(slug, {}).get("ativa"):
        flash("Já há uma busca via API em andamento.", "erro")
        return redirect(url_for("buscas", slug=slug))
    fase = request.form.get("fase", "piloto")
    consulta = request.form.get("string", "").strip()
    if not consulta:
        flash("String vazia.", "erro")
        return redirect(url_for("buscas", slug=slug))
    c = cfg()
    est = {"ativa": True, "base": B.BASES[base]["nome"], "n": 0, "total": 0, "erro": "", "msg": ""}
    _api_status[slug] = est
    filtros = pr.protocolo.get("filtros") or {}

    def rodar():
        import json as _json
        try:
            def prog(nn, tt):
                est["n"], est["total"] = nn, tt
            total, regs, paginas, avisos = apis.executar(base, consulta, c, prog, filtros)
            data = hoje()
            bruto = _json.dumps({"consulta": consulta, "base": base, "data": data, "paginas": paginas}, ensure_ascii=False).encode("utf-8")
            ris_txt = ris.escrever(regs).encode("utf-8")
            obs = "; ".join(avisos)
            if len(regs) < total:
                obs += f"; limite de {len(regs)} registros aplicado (total da API: {total})"
            proj = Projeto(raiz(), slug)
            e = proj.registrar_execucao(base, fase, data, [consulta], str(total),
                                        [("resposta_api.json", bruto), ("convertido_da_api.ris", ris_txt)],
                                        "api", obs.strip("; "), registros_api=regs)
            S.atualizar_prisma(proj)
            est["msg"] = f"Execução {e['id']} registrada: {len(regs)} registros (total informado pela API: {total})."
        except Exception as ex:  # noqa: BLE001
            est["erro"] = str(ex)
        finally:
            est["ativa"] = False

    threading.Thread(target=rodar, daemon=True).start()
    flash(f"Busca via API iniciada na {B.BASES[base]['nome']}.", "info")
    return redirect(url_for("buscas", slug=slug))


@app.route("/p/<slug>/api-status")
def api_status(slug):
    return jsonify(_api_status.get(slug, {"ativa": False}))


@app.route("/p/<slug>/controle", methods=["POST"])
def controle(slug):
    pr = projeto(slug)
    pr.salvar_controle(request.form.get("controle", ""))
    flash("Conjunto de controle salvo e conferido contra as execuções já registradas.", "ok")
    return redirect(url_for("buscas", slug=slug) + "#controle")


# ---------------- seleção ----------------

@app.route("/p/<slug>/selecao")
def selecao(slug):
    pr = projeto(slug)
    regs = pr.registros
    pl = S.pool(pr, regs)
    cal = S.calib(pr)
    info = {
        "total": len(regs), "unicos": len(pl), "dedup_feita": any("duplicado_de" in r for r in regs),
        "sem_resumo": sum(1 for r in pl if not r.get("resumo")),
        "sem_resumo_com_doi": sum(1 for r in pl if not r.get("resumo") and r.get("doi")),
        "cal_pendentes": len(S.pendentes_calibracao(pr)) if cal.get("ids") else None,
        "sem_sugestao": sum(1 for r in pl if not r.get("calibracao") and not r.get("sug_decisao")),
        "com_sugestao": sum(1 for r in pl if not r.get("calibracao") and r.get("sug_decisao")),
        "triagem_pendentes": sum(1 for r in pl if not r.get("calibracao") and not r.get("dec_decisao")),
        "decididos": sum(1 for r in pl if r.get("dec_decisao")),
    }
    return render_template("selecao.html", pr=pr, p=pr.protocolo, info=info, cal=cal, n=S.numeros(pr),
                           ia_status=ia.status(slug), oa_status=S.status_resumos(slug), hash_atual=ia.prompt_hash(pr.protocolo))


@app.route("/p/<slug>/deduplicar", methods=["POST"])
def deduplicar(slug):
    pr = projeto(slug)
    tot, dup = S.deduplicar(pr)
    S.renderizar_todos_lotes(pr)
    flash(f"Deduplicação concluída: {dup} duplicatas em {tot} registros.", "ok")
    return redirect(url_for("selecao", slug=slug))


@app.route("/p/<slug>/resumos", methods=["POST"])
def resumos(slug):
    try:
        S.completar_resumos(lambda: Projeto(raiz(), slug), slug, cfg().get("openalex_email", ""))
        flash("Buscando resumos no OpenAlex em segundo plano.", "info")
    except RuntimeError as ex:
        flash(str(ex), "erro")
    return redirect(url_for("selecao", slug=slug))


@app.route("/p/<slug>/status")
def status(slug):
    return jsonify({"ia": ia.status(slug), "resumos": S.status_resumos(slug), "api": _api_status.get(slug, {"ativa": False})})


@app.route("/p/<slug>/calibracao/preparar", methods=["POST"])
def preparar_calibracao(slug):
    pr = projeto(slug)
    try:
        cal = S.preparar_calibracao(pr, int(request.form.get("n", 100)), int(request.form.get("semente", 2026)))
        S.renderizar_todos_lotes(pr)
        flash(f"Amostra de {cal['n']} registros sorteada. Trie-a sem ver sugestões.", "ok")
    except ValueError as ex:
        flash(str(ex), "erro")
    return redirect(url_for("selecao", slug=slug))


def _rodar_ia(slug, ids, ao_terminar):
    ia.iniciar(slug, ids, lambda: Projeto(raiz(), slug), cfg(), ao_terminar)


@app.route("/p/<slug>/calibracao/ia", methods=["POST"])
def calibracao_ia(slug):
    pr = projeto(slug)
    if S.pendentes_calibracao(pr):
        flash("Termine a triagem humana da amostra antes de rodar a IA nela.", "erro")
        return redirect(url_for("selecao", slug=slug))
    cal = S.calib(pr)
    regs = {r["id"]: r for r in pr.registros}
    ids = [i for i in cal["ids"] if not regs[i].get("sug_decisao")]
    if not ids:
        S.concluir_calibracao(pr)
        flash("Métricas recalculadas.", "ok")
        return redirect(url_for("selecao", slug=slug))
    try:
        _rodar_ia(slug, ids, lambda est: S.concluir_calibracao(Projeto(raiz(), slug), est))
        flash(f"IA avaliando a amostra ({len(ids)} registros).", "info")
    except RuntimeError as ex:
        flash(str(ex), "erro")
    return redirect(url_for("selecao", slug=slug))


@app.route("/p/<slug>/ia/sugerir", methods=["POST"])
def sugerir(slug):
    pr = projeto(slug)
    cal = S.calib(pr)
    if cal.get("estado") != "avaliada" and not request.form.get("sem_calibracao"):
        flash("Avalie a calibração antes, ou marque a opção de seguir sem calibração (não recomendado).", "erro")
        return redirect(url_for("selecao", slug=slug))
    if request.form.get("sem_calibracao") and cal.get("estado") != "avaliada":
        pr.decisao("Sugestões de IA geradas sem calibração concluída", request.form.get("motivo", "") or "não informado")
    ids = [r["id"] for r in S.pool(pr) if not r.get("calibracao") and not r.get("sug_decisao") and not r.get("dec_decisao")]
    limite = int(request.form.get("limite", 0) or 0)
    if limite:
        ids = ids[:limite]
    if not ids:
        flash("Não há registros pendentes sem sugestão.", "info")
        return redirect(url_for("selecao", slug=slug))

    def fim(est):
        proj = Projeto(raiz(), slug)
        proj.log("Sugestões de IA geradas", f"{est['feitos']} registros; modelo {est.get('modelo', '')}; prompt {ia.prompt_hash(proj.protocolo)}"
                 + (f"; erro: {est['erro']}" if est.get("erro") else ""))
        S.renderizar_todos_lotes(proj)

    try:
        _rodar_ia(slug, ids, fim)
        flash(f"Gerando sugestões para {len(ids)} registros.", "info")
    except RuntimeError as ex:
        flash(str(ex), "erro")
    return redirect(url_for("selecao", slug=slug))


@app.route("/p/<slug>/ia/parar", methods=["POST"])
def parar_ia(slug):
    ia.parar(slug)
    flash("A tarefa vai parar ao fim do lote atual.", "info")
    return redirect(url_for("selecao", slug=slug))


@app.route("/p/<slug>/estudos", methods=["POST"])
def estudos(slug):
    pr = projeto(slug)
    n = S.gerar_notas_estudos(pr)
    S.atualizar_prisma(pr)
    flash(f"{n} nota(s) de estudo criada(s) em 03 Estudos.", "ok")
    return redirect(url_for("selecao", slug=slug))


@app.route("/p/<slug>/prisma", methods=["POST"])
def prisma(slug):
    pr = projeto(slug)
    S.atualizar_prisma(pr)
    S.renderizar_calibracao(pr)
    S.renderizar_todos_lotes(pr)
    flash("PRISMA, calibração e lotes atualizados no vault.", "ok")
    return redirect(request.referrer or url_for("painel", slug=slug))


@app.route("/p/<slug>/exportar/<filtro>.ris")
def exportar(slug, filtro):
    pr = projeto(slug)
    if filtro not in ("unicos", "encaminhados"):
        abort(404)
    return Response(S.exportar_ris(pr, filtro), mimetype="application/x-research-info-systems",
                    headers={"Content-Disposition": f"attachment; filename={slug}_{filtro}_{hoje()}.ris"})


# ---------------- revisão registro a registro ----------------

def _fila(pr, modo, filtro, regs, cal):
    pl = sorted(S.pool(pr, regs), key=lambda r: r["id"])
    if modo == "calibracao":
        fila = [r for r in pl if r["id"] in set(cal.get("ids", []))]
    else:
        fila = [r for r in pl if not r.get("calibracao")]
    if filtro == "pendentes":
        fila = [r for r in fila if not r.get("dec_decisao")]
    elif filtro == "divergentes":
        fila = [r for r in fila if r.get("dec_decisao") and r.get("sug_decisao") and S.sugestao_visivel(r, cal)
                and (r["dec_decisao"] in ("incluir", "duvida")) != (r["sug_decisao"] in ("incluir", "duvida"))]
    elif filtro == "sugestao_excluir":
        fila = [r for r in fila if not r.get("dec_decisao") and r.get("sug_decisao") == "excluir"]
    return fila


@app.route("/p/<slug>/revisar")
def revisar(slug):
    pr = projeto(slug)
    modo = request.args.get("modo", "triagem")
    filtro = request.args.get("filtro", "pendentes")
    regs = pr.registros
    cal = S.calib(pr)
    fila = _fila(pr, modo, filtro, regs, cal)
    rid = request.args.get("id")
    atual = next((r for r in regs if r["id"] == rid), None) if rid else (fila[0] if fila else None)
    pos = next((i for i, r in enumerate(fila) if atual and r["id"] == atual["id"]), None)
    prox = fila[pos + 1]["id"] if pos is not None and pos + 1 < len(fila) else None
    ant = fila[pos - 1]["id"] if pos is not None and pos > 0 else None
    p = pr.protocolo
    return render_template("revisar.html", pr=pr, p=p, r=atual, fila=fila, modo=modo, filtro=filtro, cal=cal,
                           mostrar_sug=bool(atual and S.sugestao_visivel(atual, cal)), prox=prox, ant=ant, pos=pos)


@app.route("/p/<slug>/decidir", methods=["POST"])
def decidir(slug):
    pr = projeto(slug)
    f = request.form
    try:
        S.decidir(pr, f["id"], f["decisao"], f.getlist("criterios"), f.get("nota", ""))
    except ValueError as ex:
        flash(str(ex), "erro")
        return redirect(url_for("revisar", slug=slug, modo=f.get("modo"), filtro=f.get("filtro"), id=f["id"]))
    S.atualizar_prisma(pr)
    destino = f.get("proximo") if f.get("filtro") != "pendentes" else None
    return redirect(url_for("revisar", slug=slug, modo=f.get("modo"), filtro=f.get("filtro"), **({"id": destino} if destino else {})))


def main():
    porta = int(os.environ.get("RSL_PORTA", "5077"))
    if not os.environ.get("RSL_SEM_NAVEGADOR"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{porta}")).start()
    print(f"RSL Automação {VERSAO} em http://127.0.0.1:{porta}  (Ctrl+C para encerrar)")
    app.run(host="127.0.0.1", port=porta, debug=False, threaded=True)


if __name__ == "__main__":
    main()
