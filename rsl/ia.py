"""Sugestões de triagem com IA generativa via Claude Code (modo não interativo).

Usa o comando `claude -p` já autenticado na conta da pesquisadora (plano Pro/Max),
sem ferramentas, com um prompt de sistema montado a partir dos critérios do protocolo.
A IA apenas SUGERE; a decisão é sempre humana.
"""
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .vault import agora, sha256_texto

ESQUEMA = {
    "type": "object",
    "properties": {
        "avaliacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "sugestao": {"type": "string", "enum": ["incluir", "excluir", "duvida"]},
                    "criterios": {"type": "array", "items": {"type": "string"}},
                    "justificativa": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                },
                "required": ["id", "sugestao", "criterios", "justificativa", "confianca"],
            },
        }
    },
    "required": ["avaliacoes"],
}


def criterios_triagem(p):
    ic = [c for c in p.get("criterios_inclusao", []) if c.get("aplicacao", "triagem") == "triagem"]
    ec = [c for c in p.get("criterios_exclusao", []) if c.get("aplicacao", "triagem") == "triagem"]
    return ic, ec


def montar_prompt(p) -> str:
    ic, ec = criterios_triagem(p)
    qs = "\n".join(f"- {q['id']}: {q.get('pergunta') or q.get('titulo')}" for q in p.get("questoes", []))
    L = [
        "Você apoia a triagem por título, resumo e palavras-chave de uma revisão sistemática da literatura "
        "conduzida segundo as diretrizes de Kitchenham et al. e relatada conforme o PRISMA 2020.",
        "",
        f"Título da revisão: {p.get('titulo', '')}",
        f"Objetivo: {p.get('objetivo', '')}",
        "",
        "Questões de pesquisa:",
        qs or "- (não informadas)",
        "",
        "Critérios de INCLUSÃO (o estudo precisa atender a TODOS):",
        "\n".join(f"- {c['id']}: {c['texto']}" for c in ic) or "- (nenhum nesta fase)",
        "",
        "Critérios de EXCLUSÃO (basta atender a UM para excluir):",
        "\n".join(f"- {c['id']}: {c['texto']}" for c in ec) or "- (nenhum nesta fase)",
        "",
        "Regras:",
        "1. Avalie apenas o que está no registro (título, resumo, palavras-chave, tipo de documento, veículo, idioma). Não presuma conteúdo ausente.",
        "2. Use 'excluir' somente quando houver evidência clara no registro. Em 'criterios', liste os códigos que justificam a exclusão: "
        "um critério de inclusão NÃO atendido (ex.: IC2) ou um critério de exclusão atendido (ex.: EC1).",
        "3. Use 'duvida' quando faltar informação (por exemplo, sem resumo) ou quando o registro for limítrofe. "
        "A triagem nesta fase é inclusiva: na dúvida, o estudo segue para a leitura completa.",
        "4. Use 'incluir' quando o registro indicar que atende a todos os critérios de inclusão e a nenhum de exclusão; nesse caso 'criterios' pode ficar vazio.",
        "5. 'justificativa': até duas frases em português, citando o trecho ou a característica do registro que fundamenta a sugestão.",
        "6. 'confianca': alta, media ou baixa.",
        "7. Devolva exatamente uma avaliação para cada registro recebido, com o mesmo 'id'.",
    ]
    return "\n".join(L)


def prompt_hash(p) -> str:
    return sha256_texto(montar_prompt(p))[:12]


def resolver_cmd(cmd: str) -> str:
    achado = shutil.which(cmd) or shutil.which(cmd + ".cmd") or shutil.which(cmd + ".exe")
    if not achado:
        raise RuntimeError(f"Comando '{cmd}' não encontrado. Instale o Claude Code e faça login (comando 'claude').")
    return achado


def verificar(cfg) -> str:
    cmd = resolver_cmd(cfg.get("claude_cmd", "claude"))
    r = subprocess.run([cmd, "auth", "status", "--text"], capture_output=True, text=True, encoding="utf-8", timeout=60)
    return (r.stdout or r.stderr).strip()


def _entrada(r):
    return {
        "id": r["id"], "titulo": r.get("titulo", ""), "resumo": r.get("resumo", "") or "(sem resumo)",
        "palavras_chave": r.get("palavras_chave", ""), "tipo_documento": r.get("tipo_doc", ""),
        "veiculo": r.get("veiculo", ""), "idioma": r.get("idioma", ""), "ano": r.get("ano", ""),
    }


def avaliar_lote(registros, p, cfg):
    cmd = resolver_cmd(cfg.get("claude_cmd", "claude"))
    with tempfile.TemporaryDirectory(prefix="rsl-ia-") as tmp:
        prompt_arq = Path(tmp) / "prompt.txt"
        prompt_arq.write_text(montar_prompt(p), encoding="utf-8")
        args = [cmd, "-p", "--output-format", "json", "--tools=", "--disallowedTools", "mcp__*",
                "--no-session-persistence", "--model", cfg.get("claude_modelo", "sonnet"),
                "--system-prompt-file", str(prompt_arq), "--json-schema", json.dumps(ESQUEMA),
                "Avalie os registros recebidos na entrada padrão (lista JSON) segundo os critérios."]
        entrada = json.dumps([_entrada(r) for r in registros], ensure_ascii=False)
        try:
            r = subprocess.run(args, input=entrada, capture_output=True, text=True, encoding="utf-8",
                               cwd=tmp, timeout=600)
        except subprocess.TimeoutExpired as ex:
            raise RuntimeError("O Claude Code não respondeu em 10 minutos.") from ex
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"Resposta inesperada do Claude Code: {(r.stdout or r.stderr)[:500]}")
    if out.get("is_error"):
        raise RuntimeError(f"Claude Code: {str(out.get('result', ''))[:500]}")
    dados = out.get("structured_output")
    if not dados:
        try:
            dados = json.loads(out.get("result", ""))
        except ValueError:
            raise RuntimeError("O Claude Code não devolveu as avaliações no formato esperado.")
    modelo = next(iter((out.get("modelUsage") or {}).keys()), cfg.get("claude_modelo", "sonnet"))
    ids = {x["id"] for x in registros}
    avals = {a["id"]: a for a in dados.get("avaliacoes", []) if a.get("id") in ids}
    return avals, {"modelo": modelo, "custo_estimado_usd": out.get("total_cost_usd")}


# ---------------- tarefa em segundo plano ----------------

_tarefas = {}


def status(slug):
    return dict(_tarefas.get(slug, {"ativa": False}))


def parar(slug):
    if slug in _tarefas:
        _tarefas[slug]["parar"] = True


def iniciar(slug, ids, carregar_proj, cfg, ao_terminar=None):
    """Roda as sugestões para os ids informados, salvando a cada lote."""
    if _tarefas.get(slug, {}).get("ativa"):
        raise RuntimeError("Já há uma tarefa de IA em andamento neste projeto.")
    est = {"ativa": True, "feitos": 0, "total": len(ids), "erro": "", "inicio": agora(), "parar": False, "modelo": ""}
    _tarefas[slug] = est

    def rodar():
        tam = max(1, int(cfg.get("ia_registros_por_chamada", 10) or 10))
        try:
            for i in range(0, len(ids), tam):
                if est["parar"]:
                    est["erro"] = "Interrompido pela usuária."
                    break
                proj = carregar_proj()
                p = proj.protocolo
                h = prompt_hash(p)
                lote_ids = ids[i:i + tam]
                with proj.lock:
                    regs = [r for r in proj.registros if r["id"] in lote_ids]
                avals, meta = avaliar_lote(regs, p, cfg)
                est["modelo"] = meta["modelo"]
                with proj.lock:
                    todos = proj.registros
                    for r in todos:
                        a = avals.get(r["id"])
                        if a:
                            r.update({"sug_decisao": a["sugestao"], "sug_criterios": a.get("criterios", []),
                                      "sug_justificativa": a.get("justificativa", ""), "sug_confianca": a.get("confianca", ""),
                                      "sug_modelo": meta["modelo"], "sug_prompt_hash": h, "sug_data": agora()})
                    proj.salvar("registros", todos)
                est["feitos"] += len(avals)
                faltaram = len(lote_ids) - len(avals)
                if faltaram:
                    est["erro"] = f"{faltaram} registro(s) voltaram sem avaliação; rode novamente para completá-los."
        except Exception as ex:  # noqa: BLE001 — mostrar qualquer falha na interface
            est["erro"] = str(ex)
        finally:
            est["ativa"] = False
            est["fim"] = agora()
            if ao_terminar:
                try:
                    ao_terminar(est)
                except Exception as ex:  # noqa: BLE001
                    est["erro"] = (est["erro"] + " | " if est["erro"] else "") + f"Falha ao atualizar notas: {ex}"

    threading.Thread(target=rodar, daemon=True).start()
