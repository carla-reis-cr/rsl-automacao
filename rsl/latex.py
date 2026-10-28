"""Geração de LaTeX a partir do protocolo (a revisão montada virá depois).

Espelha as seções de `protocolo.renderizar`, mas com tabelas reais (longtable/booktabs),
que o plugin Latex-Exporter do Obsidian não converte.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import bases as B
from .protocolo import criterio_dup

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
    s = re.sub(r"[\\&%$#_{}~^]", lambda m: _ESC[m.group(0)], str(s if s is not None else ""))
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
    L.append(rf"\textbf{{Campos da busca:}} {tex(B.campos_texto(p))}. "
             "Nas bases que não permitem restringir o campo, vale o que consta na tabela abaixo.\n")
    L.append(r"\textbf{Bases e campos de busca} (a confirmar nas buscas piloto):" + "\n")
    linhas = [[tex(B.BASES[b]["nome"]), tex(B.BASES[b]["campos"]),
               "API ou exportação manual" if B.BASES[b]["api"] else f"exportação manual ({B.BASES[b].get('exportacao', 'RIS')})"]
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
        L += _itens(rf"\textbf{{{tex(c['id'])}:}} {tex(c['texto'])}"
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


def _dif(e):
    total = re.sub(r"[.,\s]", "", str(e.get("resultados_site") or ""))
    return int(total) - e["registros"] if total.isdigit() else None


ROTULO_FASES = {"piloto": "piloto", "definitiva": "definitivas"}


def titulo_fases(fases) -> str:
    return " e ".join(ROTULO_FASES[f] for f in ("piloto", "definitiva") if f in fases)


def relatorio_buscas_tex(p: dict, execs: list, controle: list, estado: str, data: str,
                         fases=("piloto", "definitiva")) -> str:
    """Relatório das buscas das fases escolhidas (piloto, definitiva ou ambas), para entregar ao orientador."""
    fases = [f for f in ("piloto", "definitiva") if f in fases] or ["piloto", "definitiva"]
    execs = [e for e in execs if e["fase"] in fases]
    bases = [b for b in B.ORDEM_PADRAO if b in p.get("bases", [])]
    por_base = {b: [e for e in execs if e["base_id"] == b] for b in bases}
    # Bases com busca dividida em blocos (subconsultas, ex.: ScienceDirect): cada bloco é uma execução, e os totais somam os blocos.
    divididas = {b: len(B.strings_da_base(b, p)["strings"]) > 1 for b in bases}

    def vigentes(b, fase):
        """Execuções que valem no total da base na fase: a mais recente; em base dividida, a mais recente de cada bloco."""
        da_fase = [e for e in por_base[b] if e["fase"] == fase]
        if not divididas[b]:
            return da_fase[-1:]
        por_string = {}
        for e in da_fase:
            por_string[tuple(e.get("strings", []))] = e
        return sorted(por_string.values(), key=lambda e: e["id"])

    L = [PREAMBULO, rf"\title{{{tex(p['titulo'])}\\\large Relatório das buscas ({tex(titulo_fases(fases))})}}",
         rf"\date{{{tex(data)} --- protocolo versão {tex(p.get('versao', 1))}, {tex(estado)}}}", r"\author{}",
         r"\begin{document}", r"\maketitle", ""]

    L.append(r"\section{Resumo}")
    contagem = ", ".join(f"{sum(1 for e in execs if e['fase'] == f)} {ROTULO_FASES[f]}" for f in fases)
    texto = f"Este relatório cobre as buscas {tex(titulo_fases(fases))}: {len(execs)} execuções registradas ({contagem}) em {len(bases)} bases previstas no protocolo."
    for f in fases:
        feitas = [b for b in bases if vigentes(b, f)]
        importados = sum(e["registros"] for b in feitas for e in vigentes(b, f))
        texto += (f" Nas buscas {ROTULO_FASES[f]}, {len(feitas)} de {len(bases)} bases têm execução, "
                  f"somando {importados} registros importados (antes da remoção de duplicatas).")
    L.append(texto + "\n")

    def celula(es):
        if not es:
            return ["pendente", "--", "--"]
        datas = sorted({e["data"] for e in es})
        data_txt = datas[-1] if len(datas) == 1 else f"{datas[0]} a {datas[-1]}"
        if len(es) > 1:
            data_txt += f" ({len(es)} blocos)"
        totais = [re.sub(r"[.,\s]", "", str(e.get("resultados_site") or "")) for e in es]
        site = str(sum(int(t) for t in totais)) if all(t.isdigit() for t in totais) else "--"
        return [tex(data_txt), tex(site), tex(sum(e["registros"] for e in es))]

    larg = 0.62 / len(fases)
    colunas = [("Base", 0.26)]
    for f in fases:
        rot = "Piloto" if f == "piloto" else "Definitiva"
        colunas += [(f"{rot}: data", larg * 0.4), ("Site/API", larg * 0.3), ("Importados", larg * 0.3)]
    linhas = [[tex(B.BASES[b]["nome"])] + sum((celula(vigentes(b, f)) for f in fases), []) for b in bases]
    L += _tabela(colunas, linhas)
    nota = ("Quando uma fase foi executada mais de uma vez, a tabela mostra a execução mais recente; "
            "todas estão detalhadas na seção seguinte.")
    em_blocos = [B.BASES[b]["nome"] for b in bases if divididas[b]]
    if em_blocos:
        nota += (f" Em {', '.join(em_blocos)}, a busca foi dividida em blocos (subconsultas) por limite de conectores booleanos: "
                 "cada bloco é uma execução, os totais da tabela somam os blocos e os registros repetidos entre eles "
                 "são removidos na deduplicação.")
    L.append(tex(nota) + "\n")

    L.append(r"\section{Critérios das buscas}")
    L.append(rf"\textbf{{Campos da busca:}} {tex(B.campos_texto(p))}. \textbf{{Filtros:}} {tex(B._filtros_texto(p.get('filtros') or {}))}. "
             "Nas bases que não aceitam o filtro dentro da string, ele foi aplicado na interface do site.\n")
    grupos = [g for g in p.get("grupos", []) if g.get("termos")]
    if grupos:
        L += _tabela([("Eixo", 0.25), ("Termos", 0.67)],
                     [[tex(g["nome"]), tex(B.grupo(g["termos"]))] for g in grupos])
    if p.get("historico_strings"):
        L.append(r"\textbf{Mudanças na string de busca}" + "\n")
        L += _tabela([("Data", 0.2), ("Motivo", 0.72)], [[tex(h.get("data")), tex(h.get("motivo"))] for h in p["historico_strings"]])

    L.append(r"\section{Execuções por base}")
    for b in bases:
        L.append(rf"\subsection{{{tex(B.BASES[b]['nome'])}}}")
        if not por_base[b]:
            L.append(rf"\emph{{Nenhuma busca {tex(titulo_fases(fases))} registrada para esta base.}}" + "\n")
            continue
        for e in por_base[b]:
            metodo = "via API" if e["metodo"] == "api" else "exportação manual"
            L.append(rf"\textbf{{{tex(e['id'])} --- {tex(e['fase'])}}}, busca de {tex(e['data'])} ({metodo}), "
                     f"registrada em {tex(e.get('registrado_em', ''))}, protocolo versão {tex(e.get('versao_protocolo', ''))}.\n")
            itens = [f"Resultados informados pelo site/API: {tex(e.get('resultados_site') or 'não informado')}; "
                     f"registros importados: {tex(e['registros'])}."]
            d = _dif(e)
            if d:
                itens[0] += f" Diferença de {tex(d)} entre o total do site e o importado."
            if e.get("controle_total"):
                itens.append(f"Conjunto de controle: {len(e.get('controle_encontrados', []))} de {e['controle_total']} recuperados.")
            if e.get("observacoes"):
                itens.append(f"Observações: {tex(e['observacoes'])}")
            itens.append("Arquivos (SHA-256): " + "; ".join(
                rf"\texttt{{{tex(a['nome'])}}} ({tex(a['sha256'][:12])}\ldots)" for a in e.get("arquivos", [])))
            L += _itens(itens)
            for i, st in enumerate(e.get("strings", []), 1):
                if len(e["strings"]) > 1:
                    L.append(rf"\textbf{{Subconsulta {i}}}")
                L += [r"\begin{lstlisting}", st, r"\end{lstlisting}"]
            L.append("")

    if controle:
        L.append(r"\section{Conjunto de controle}")
        L.append("Artigos que a busca precisa recuperar; a tabela indica em quais execuções cada um foi encontrado.\n")
        linhas = [[tex(c["id"]), tex(c.get("titulo") or c.get("doi")),
                   ", ".join(tex(e["id"]) for e in execs if c["id"] in e.get("controle_encontrados", [])) or "nenhuma"]
                  for c in controle]
        L += _tabela([("ID", 0.08), ("Artigo", 0.5), ("Encontrado em", 0.34)], linhas)

    L.append(r"\section{Observações e limitações}")
    L += _itens([
        "As contagens do site e as do arquivo exportado podem diferir (limites de exportação em lotes e atualização da base); "
        "quando houve diferença, ela está indicada em cada execução.",
        "A busca via API pode retornar totais diferentes da interface web; os dois valores são registrados quando disponíveis.",
        "A remoção de duplicatas entre bases é feita depois, na etapa de seleção; os totais acima são anteriores a ela.",
        "Cada arquivo importado tem hash SHA-256 e o mesmo arquivo não pode ser registrado duas vezes."])
    L.append(r"\end{document}")
    return "\n".join(L) + "\n"


def _pastas_miktex():
    """Pastas padrão do MiKTeX no Windows: a instalação por usuário nem sempre entra no PATH do app."""
    bases = [os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
    candidatos = []
    for b in bases:
        if b:
            candidatos += [Path(b) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64", Path(b) / "MiKTeX" / "miktex" / "bin" / "x64"]
    return [str(c) for c in candidatos if c.is_dir()]


def compilador():
    """Caminho do compilador LaTeX (pdflatex, xelatex ou tectonic) ou None."""
    pastas = os.pathsep.join(_pastas_miktex() + [os.environ.get("PATH", "")])
    for c in ("pdflatex", "xelatex", "tectonic"):
        achado = shutil.which(c, path=pastas)
        if achado:
            return achado
    return None


def compilar(tex_path: Path) -> Path:
    """Compila o .tex no lugar (duas passadas, para as referências cruzadas) e devolve o caminho do PDF."""
    cmd = compilador()
    if not cmd:
        raise RuntimeError("Para gerar o PDF aqui é preciso BAIXAR E INSTALAR o MiKTeX (miktex.org) neste computador e depois "
                           "fechar e abrir o app de novo. Se não quiser instalar nada: clique em 'baixar .tex', envie o arquivo "
                           "ao Overleaf (overleaf.com, gratuito) e compile lá. Isso não tem relação com o Obsidian.")
    pdf = tex_path.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    tectonic = Path(cmd).stem.lower() == "tectonic"
    # No MiKTeX, --enable-installer baixa sozinho os pacotes que faltam (sem a janela "Package Installation", que travaria o app).
    extra = ["--enable-installer"] if "miktex" in str(cmd).lower() else []
    args = [cmd, tex_path.name] if tectonic else [cmd, *extra, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    for _ in range(1 if tectonic else 2):
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
