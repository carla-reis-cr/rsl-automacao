"""Geração de LaTeX a partir do protocolo (a revisão montada virá depois).

Espelha as seções de `protocolo.renderizar`, mas com tabelas reais (longtable/booktabs),
que o plugin Latex-Exporter do Obsidian não converte.
"""
import re
import shutil
import subprocess
from pathlib import Path

from . import bases as B
from .protocolo import APLICACOES, criterio_dup

_ESC = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}

PREAMBULO = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[brazilian]{babel}
\usepackage[margin=2.5cm]{geometry}
\usepackage{booktabs,longtable,array}
\usepackage{enumitem}
\usepackage{listings}
\usepackage[hidelinks]{hyperref}
\DeclareUnicodeCharacter{2192}{\ensuremath{\rightarrow}}
\lstset{basicstyle=\ttfamily\footnotesize,breaklines=true,breakatwhitespace=false,columns=fullflexible,frame=single}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.6em}
"""


def tex(s) -> str:
    s = re.sub(r"[\\&%$#_{}~^]", lambda m: _ESC[m.group(0)], str(s or ""))
    return re.sub(r'"([^"\n]*)"', r"``\1''", s)


def _tabela(colunas, linhas) -> list:
    """colunas: lista de (cabeçalho, largura relativa à linha, ex.: 0.3)."""
    esp = "".join(f"p{{{w}\\linewidth}}" for _, w in colunas)
    cab = " & ".join(rf"\textbf{{{tex(c)}}}" for c, _ in colunas) + r" \\"
    L = [rf"\begin{{longtable}}{{{esp}}}", r"\toprule", cab, r"\midrule", r"\endhead"]
    for ln in linhas:
        L.append(" & ".join(ln) + r" \\")
    L += [r"\bottomrule", r"\end{longtable}", ""]
    return L


def _itens(itens) -> list:
    return [r"\begin{itemize}[leftmargin=*]"] + [rf"\item {i}" for i in itens] + [r"\end{itemize}", ""]


def protocolo_tex(p: dict, estado: str) -> str:
    L = [PREAMBULO, rf"\title{{{tex(p['titulo'])}\\\large Protocolo de Revisão Sistemática da Literatura}}",
         rf"\date{{Versão {tex(p.get('versao', 1))} --- {tex(estado)}}}", r"\author{}",
         r"\begin{document}", r"\maketitle", ""]

    L.append(r"\section{Objetivo}")
    L.append(tex(p.get("objetivo")) or r"\emph{A definir.}")
    L.append("")
    if p.get("cadeia"):
        L.append(rf"\textbf{{Cadeia lógica:}} {tex(p['cadeia'])}" + "\n")
    L.append(tex(p.get("diretrizes")) + "\n")

    L.append(r"\section{Questões de pesquisa}")
    if p.get("questoes"):
        linhas = []
        for q in p["questoes"]:
            perg = tex(q.get("pergunta"))
            if q.get("traducao"):
                perg += rf" \emph{{({tex(q['traducao'])})}}"
            linhas.append([tex(q["id"]), rf"\textbf{{{tex(q.get('titulo'))}}}", perg])
        L += _tabela([("Código", 0.1), ("Questão", 0.25), ("Pergunta", 0.55)], linhas)
    else:
        L.append(r"\emph{A definir.}" + "\n")

    L.append(r"\section{Processo de busca}")
    grupos = [g for g in p.get("grupos", []) if g.get("termos")]
    if grupos:
        L.append("A busca seleciona estudos que contenham pelo menos um termo de cada grupo.\n")
        linhas = [[tex(g["nome"]), tex(B.grupo(g["termos"])) + (r" \newline \textbf{AND}" if i < len(grupos) - 1 else "")]
                  for i, g in enumerate(grupos)]
        L += _tabela([("Termo principal", 0.25), ("Termos alternativos", 0.67)], linhas)
    L.append(r"\textbf{Bases e campos de busca} (a confirmar nas buscas piloto):" + "\n")
    linhas = [[tex(B.BASES[b]["nome"]), tex(B.BASES[b]["campos"]),
               "API ou exportação manual" if B.BASES[b]["api"] else "exportação manual (RIS)"]
              for b in p.get("bases", [])]
    L += _tabela([("Base", 0.17), ("Campos", 0.5), ("Execução", 0.25)], linhas)
    L.append(rf"\textbf{{Filtros:}} {tex(B._filtros_texto(p.get('filtros') or {}))}. "
             r"As strings de cada base estão no Apêndice~\ref{ap:strings}." + "\n")
    if p.get("historico_strings"):
        L.append(r"\textbf{Histórico de mudanças na string}" + "\n")
        L += _tabela([("Data", 0.2), ("Motivo", 0.72)],
                     [[tex(h.get("data")), tex(h.get("motivo"))] for h in p["historico_strings"]])

    L.append(r"\section{Seleção dos estudos}")
    L.append("Serão selecionados os estudos que atenderem a todos os critérios de inclusão e a nenhum critério de exclusão.\n")
    for titulo, chave in (("Critérios de inclusão", "criterios_inclusao"), ("Critérios de exclusão", "criterios_exclusao")):
        L.append(rf"\textbf{{{titulo}}}" + "\n")
        L += _itens(rf"\textbf{{{tex(c['id'])}:}} {tex(c['texto'])} \emph{{(aplicação: {tex(APLICACOES.get(c.get('aplicacao', 'triagem')))})}}"
                    for c in p.get(chave, []))
    L.append(r"\textbf{Fases}" + "\n")
    L += [r"\begin{enumerate}[leftmargin=*]",
          r"\item \textbf{Busca:} execução das strings nas bases (via API quando disponível, ou exportação RIS), com registro da data, "
          "string exata, filtros, número de resultados e hash dos arquivos.",
          rf"\item \textbf{{Remoção de duplicatas}} ({tex(criterio_dup(p))}): por DOI e por título normalizado com o mesmo ano.",
          r"\item \textbf{Triagem por título, resumo e palavras-chave:} decisão humana registro a registro, com apoio de sugestões "
          r"de IA generativa (ver Seção~\ref{sec:ferramentas}).",
          r"\item \textbf{Leitura completa:} reavaliação dos critérios no texto integral.",
          r"\item \textbf{Avaliação de qualidade:} checklist abaixo, com nota de corte.",
          r"\end{enumerate}", ""]

    L.append(r"\section{Avaliação de qualidade}")
    if p.get("qualidade"):
        L.append(f"Pontuação: {tex(p.get('pontuacao'))}.\n")
        L += _itens(rf"\textbf{{{tex(q['id'])}:}} {tex(q['texto'])}" for q in p["qualidade"])
        corte = tex(p.get("nota_corte")) or r"\emph{a definir}"
        L.append(f"Nota de corte: {corte}.\n")
    else:
        L.append(r"\emph{A definir.}" + "\n")

    L.append(r"\section{Extração e síntese}")
    fqs = [q for q in p.get("questoes", []) if q.get("tipo") != "SQ"]
    if fqs:
        L.append("O formulário de extração contém um campo para cada questão:\n")
        L += _itens(rf"\textbf{{{tex(q['id'])}}} --- {tex(q.get('titulo'))}" for q in fqs)
    sqs = [q for q in p.get("questoes", []) if q.get("tipo") == "SQ"]
    if sqs:
        L.append("As questões estatísticas (" + ", ".join(tex(q["id"]) for q in sqs)
                 + ") são respondidas a partir dos metadados dos estudos incluídos.\n")
    if p.get("extracao_extra"):
        L.append(tex(p["extracao_extra"]) + "\n")

    L.append(r"\section{Ferramentas e automação}\label{sec:ferramentas}")
    L.append("O processo é registrado pelo RSL Automação. A triagem por título e resumo usa IA generativa apenas como "
             r"\textbf{sugestão}: cada registro recebe uma sugestão (incluir, excluir ou dúvida) com o critério e a justificativa, "
             r"e \textbf{a decisão final é sempre humana}. Antes do uso, a ferramenta é calibrada contra uma amostra triada às cegas "
             "pela pesquisadora, com cálculo de concordância (Kappa de Cohen) e sensibilidade. O modelo, a versão do prompt (hash) "
             "e a data de cada sugestão ficam registrados.\n")

    L.append(r"\appendix")
    L.append(r"\section{Strings de busca por base}\label{ap:strings}")
    for b in p.get("bases", []):
        res = B.strings_da_base(b, p)
        L.append(rf"\subsection*{{{tex(B.BASES[b]['nome'])}}}")
        for i, s in enumerate(res["strings"], 1):
            if len(res["strings"]) > 1:
                L.append(rf"\textbf{{Subconsulta {i}}}")
            L += [r"\begin{lstlisting}", s, r"\end{lstlisting}"]
        L.append("")
    L.append(r"\end{document}")
    return "\n".join(L) + "\n"


def compilador():
    return next((c for c in ("pdflatex", "xelatex", "tectonic") if shutil.which(c)), None)


def compilar(tex_path: Path) -> Path:
    """Compila o .tex no lugar (duas passadas, para as referências cruzadas) e devolve o caminho do PDF."""
    cmd = compilador()
    if not cmd:
        raise RuntimeError("Nenhum compilador LaTeX encontrado (pdflatex, xelatex ou tectonic). "
                           "Instale o MiKTeX (miktex.org) ou o TeX Live, reabra o app e tente de novo. "
                           "Enquanto isso, use 'Gerar LaTeX' e compile no Overleaf.")
    pdf = tex_path.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    args = [cmd, tex_path.name] if cmd == "tectonic" else [cmd, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    for _ in range(1 if cmd == "tectonic" else 2):
        try:
            r = subprocess.run(args, cwd=tex_path.parent, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=300)
        except subprocess.TimeoutExpired as ex:
            raise RuntimeError("A compilação do LaTeX passou de 5 minutos (o MiKTeX pode estar aguardando a instalação de um pacote).") from ex
        if r.returncode != 0 or not pdf.exists():
            erros = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith("!") or "rror" in ln]
            raise RuntimeError("Falha ao compilar o LaTeX: " + " | ".join(erros[:4] or [(r.stdout or r.stderr)[-300:]]))
    for ext in (".aux", ".log", ".out", ".toc"):
        tex_path.with_suffix(ext).unlink(missing_ok=True)
    return pdf
