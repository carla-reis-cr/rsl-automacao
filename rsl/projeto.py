"""Projeto de revisão: estrutura no vault, protocolo, execuções de busca e conjunto de controle."""
import re
import threading
import unicodedata
from pathlib import Path

from . import VERSAO
from . import bases as B
from . import protocolo as P
from . import bibtex, csvref, ris
from .vault import (agora, anexar, escrever_atomico, escrever_nota, hoje, ler_json, md_escape_tabela,
                    nome_arquivo_seguro, salvar_json, sha256_arquivo, sha256_texto, slugify)

EXT_REFERENCIAS = (".ris", ".bib", ".csv")

PASTAS = {
    "protocolo": "00 Protocolo",
    "buscas": "01 Buscas",
    "exportacoes": "01 Buscas/exportacoes",
    "selecao": "02 Seleção",
    "triagem": "02 Seleção/Triagem",
    "estudos": "03 Estudos",
    "sintese": "04 Síntese",
    "manuscrito": "05 Manuscrito",
    "dados": "_dados",
}

_travas = {}


def trava(chave: str) -> threading.RLock:
    if chave not in _travas:
        _travas[chave] = threading.RLock()
    return _travas[chave]


def norm_titulo(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def listar(raiz: Path):
    if not raiz.exists():
        return []
    out = []
    for d in sorted(raiz.iterdir()):
        if (d / PASTAS["dados"] / "protocolo.yaml").exists():
            try:
                out.append(Projeto(raiz, d.name))
            except Exception:
                continue
    return out


class Projeto:
    def __init__(self, raiz: Path, slug: str):
        self.raiz = Path(raiz)
        self.slug = slug
        self.pasta = self.raiz / slug
        self.lock = trava(str(self.pasta))
        self._protocolo = None

    # ---------- caminhos ----------
    def p(self, chave: str) -> Path:
        return self.pasta / PASTAS[chave]

    @property
    def arq_protocolo(self) -> Path:
        return self.p("dados") / "protocolo.yaml"

    def caminho_vault(self, caminho: Path) -> str:
        """Caminho relativo à raiz do vault (para links e consultas)."""
        try:
            return str(caminho.relative_to(self.raiz.parent)).replace("\\", "/")
        except ValueError:
            return str(caminho)

    # ---------- criação ----------
    @classmethod
    def criar(cls, raiz: Path, protocolo: dict, slug: str = ""):
        slug = slug or slugify(protocolo["titulo"], 50)
        base, n = slug, 2
        while (Path(raiz) / slug).exists():
            slug = f"{base}-{n}"
            n += 1
        proj = cls(raiz, slug)
        proj.criar_estrutura()
        proj.salvar_protocolo(protocolo, motivo="Criação do protocolo", primeira=True)
        return proj

    def criar_estrutura(self):
        for chave in PASTAS:
            self.p(chave).mkdir(parents=True, exist_ok=True)
        hist = self.p("protocolo") / "Histórico de decisões.md"
        if not hist.exists():
            escrever_atomico(hist, "---\ntipo: historico\n---\n\n# Histórico de decisões\n\n"
                             "Decisões metodológicas e emendas ao protocolo, em ordem cronológica. "
                             "O app registra as automáticas; acrescente as suas no mesmo formato.\n\n"
                             "| Data | Decisão | Motivo |\n|---|---|---|\n")
        for pasta, texto in (("sintese", "# Síntese\n\nCategorias emergentes, taxonomia e comparações.\n"),
                             ("manuscrito", "# Manuscrito\n\nVersões, feedback da orientação e submissão.\n")):
            leia = self.p(pasta) / "Leia-me.md"
            if not leia.exists():
                escrever_atomico(leia, texto)

    # ---------- protocolo ----------
    @property
    def protocolo(self) -> dict:
        if self._protocolo is None:
            self._protocolo = P.carregar_yaml(self.arq_protocolo.read_text(encoding="utf-8"))
        return self._protocolo

    @property
    def titulo(self):
        return self.protocolo.get("titulo", self.slug)

    @property
    def congelado(self) -> bool:
        return bool(self.protocolo.get("congelado"))

    def estado(self) -> str:
        p = self.protocolo
        if p.get("congelado"):
            return f"congelado em {p.get('congelado_em', '')}"
        if p.get("versoes"):
            return "em revisão (emenda após versão congelada)"
        return "rascunho"

    def salvar_protocolo(self, novo: dict, motivo: str = "", primeira: bool = False):
        with self.lock:
            antigo = None if primeira else self.protocolo
            if antigo is not None:
                mudou = P.para_yaml({k: v for k, v in novo.items() if k not in ("versao", "versoes", "congelado", "congelado_em")}) != \
                        P.para_yaml({k: v for k, v in antigo.items() if k not in ("versao", "versoes", "congelado", "congelado_em")})
                if not mudou:
                    return
                if antigo.get("congelado"):
                    novo["versao"] = int(antigo.get("versao", 1)) + 1
                    novo["congelado"] = False
                    self.decisao(f"Emenda ao protocolo (versão {novo['versao']})", motivo or "não informado")
            escrever_atomico(self.arq_protocolo, P.para_yaml(novo))
            self._protocolo = None
            self.renderizar_protocolo()
            self.renderizar_strings()
            self.log("Protocolo salvo", motivo or "edição")

    def renderizar_protocolo(self):
        p = self.protocolo
        props = {"tipo": "protocolo", "titulo": p["titulo"], "versao": p.get("versao", 1),
                 "estado": "congelado" if p.get("congelado") else "rascunho",
                 "hash": sha256_texto(P.para_yaml(p))[:12]}
        escrever_nota(self.p("protocolo") / "Protocolo.md", props, P.renderizar(p, self.estado()))

    def congelar(self, motivo: str):
        with self.lock:
            p = self.protocolo
            if p.get("congelado"):
                return
            p["congelado"] = True
            p["congelado_em"] = hoje()
            texto = P.renderizar(p, f"congelado em {hoje()}")
            nome = f"Protocolo v{p.get('versao', 1)} {hoje()}.md"
            destino = self.p("protocolo") / "Versões" / nome
            escrever_atomico(destino, f"---\ntipo: protocolo-versao\nversao: {p.get('versao', 1)}\ndata: {hoje()}\nhash: {sha256_texto(texto)[:12]}\n---\n\n" + texto)
            p.setdefault("versoes", []).append({"versao": p.get("versao", 1), "data": hoje(), "arquivo": nome,
                                                "hash": sha256_texto(texto)[:12]})
            escrever_atomico(self.arq_protocolo, P.para_yaml(p))
            self._protocolo = None
            self.renderizar_protocolo()
            self.decisao(f"Protocolo congelado (versão {p.get('versao', 1)}) — [[{nome[:-3]}]]", motivo or "antes das buscas definitivas")
            self.log("Protocolo congelado", f"versão {p.get('versao', 1)}")

    def renderizar_strings(self):
        p = self.protocolo
        L = ["# Strings por base\n",
             "Geradas a partir dos grupos de termos do protocolo. São um ponto de partida: ajuste no piloto e registre cada ajuste. "
             "A string efetivamente executada fica gravada em cada nota de execução.\n"]
        for b in p.get("bases", []):
            info = B.BASES[b]
            res = B.strings_da_base(b, p)
            L.append(f"## {info['nome']}\n")
            L.append(f"- **Endereço:** {info['url']}")
            L.append(f"- **Campos:** {info['campos']}")
            L.append(f"- **Filtros a aplicar no site:** {res['filtros_no_site']}")
            if res.get("personalizada"):
                L.append("- **String personalizada** (editada no app)")
            for a in res["avisos"]:
                L.append(f"- ⚠️ {a}")
            L.append("")
            for i, s in enumerate(res["strings"], 1):
                if len(res["strings"]) > 1:
                    L.append(f"**Subconsulta {i}**")
                L.append(f"```\n{s}\n```")
            L.append("")
        escrever_nota(self.p("buscas") / "Strings por base.md", {"tipo": "strings", "versao_protocolo": p.get("versao", 1)}, "\n".join(L))

    # ---------- registros de processo ----------
    def log(self, acao: str, detalhe: str = ""):
        anexar(self.p("protocolo") / "Registro de execuções.md",
               f"| {agora()} | {md_escape_tabela(acao)} | {md_escape_tabela(detalhe)} | {VERSAO} |",
               cabecalho="---\ntipo: log\n---\n\n# Registro de execuções\n\nGerado automaticamente pelo RSL Automação.\n\n"
                         "| Quando | Ação | Detalhe | Versão do app |\n|---|---|---|---|")

    def decisao(self, decisao: str, motivo: str):
        anexar(self.p("protocolo") / "Histórico de decisões.md",
               f"| {hoje()} | {md_escape_tabela(decisao)} | {md_escape_tabela(motivo)} |")

    # ---------- dados ----------
    def carregar(self, nome: str, padrao):
        return ler_json(self.p("dados") / f"{nome}.json", padrao)

    def salvar(self, nome: str, dados):
        salvar_json(self.p("dados") / f"{nome}.json", dados)

    @property
    def registros(self):
        return self.carregar("registros", [])

    @property
    def execucoes(self):
        return self.carregar("execucoes", [])

    @property
    def controle(self):
        return self.carregar("controle", [])

    # ---------- conjunto de controle ----------
    def salvar_controle(self, texto: str):
        itens = []
        for i, ln in enumerate([l for l in texto.splitlines() if l.strip()], 1):
            partes = [x.strip() for x in ln.split("|")]
            doi = ris.limpar_doi(partes[0]) if partes else ""
            titulo = partes[1] if len(partes) > 1 else (partes[0] if not doi else "")
            itens.append({"id": f"C{i:02d}", "doi": doi, "titulo": titulo})
        with self.lock:
            self.salvar("controle", itens)
            execs = self.execucoes
            for e in execs:
                e["controle_encontrados"] = self._casar_controle(self._registros_da_execucao(e), itens)
                e["controle_total"] = len(itens)
            self.salvar("execucoes", execs)
            for e in execs:
                self.renderizar_execucao(e)
            self.renderizar_controle()
            self.renderizar_indice_buscas()
            self.log("Conjunto de controle atualizado", f"{len(itens)} artigos")

    @staticmethod
    def _ler_exportacao(nome, conteudo):
        """Lê um arquivo de exportação (RIS, BibTeX ou CSV da Springer); None se a extensão não for de referências."""
        ext = Path(nome).suffix.lower()
        if ext == ".bib":
            return bibtex.ler(ris.ler_texto(conteudo))
        if ext == ".csv":
            return csvref.ler(ris.ler_texto(conteudo))
        if ext == ".ris":
            return ris.ler(ris.ler_texto(conteudo))
        return None

    def _registros_da_execucao(self, e):
        regs = []
        for arq in e.get("arquivos", []):
            caminho = self.p("exportacoes") / arq["nome"]
            if caminho.exists():
                regs += self._ler_exportacao(arq["nome"], caminho.read_bytes()) or []
        return regs

    @staticmethod
    def _casar_controle(regs, controle):
        dois = {r.get("doi") for r in regs if r.get("doi")}
        titulos = {norm_titulo(r.get("titulo", "")) for r in regs if r.get("titulo")}
        achados = []
        for c in controle:
            if (c.get("doi") and c["doi"] in dois) or (c.get("titulo") and norm_titulo(c["titulo"]) in titulos):
                achados.append(c["id"])
        return achados

    def renderizar_controle(self):
        controle = self.controle
        execs = [e for e in self.execucoes]
        L = ["# Conjunto de controle\n",
             "Artigos que a busca precisa recuperar. Edite a lista pelo app (página Buscas). "
             "A tabela mostra em quais execuções cada um foi encontrado.\n"]
        if not controle:
            L.append("_Nenhum artigo cadastrado._")
        else:
            cab = "| ID | DOI | Título | " + " | ".join(e["id"] for e in execs) + " |"
            L.append(cab)
            L.append("|" + "---|" * (3 + len(execs)))
            for c in controle:
                marcas = " | ".join("✅" if c["id"] in e.get("controle_encontrados", []) else "—" for e in execs)
                L.append(f"| {c['id']} | {md_escape_tabela(c['doi'])} | {md_escape_tabela(c['titulo'])} | {marcas} |")
            if execs:
                L.append("\nExecuções: " + "; ".join(f"{e['id']} = {e['base_nome']} ({e['fase']}, {e['data']})" for e in execs))
        escrever_nota(self.p("protocolo") / "Conjunto de controle.md", {"tipo": "controle", "total": len(controle)}, "\n".join(L))

    # ---------- execuções de busca ----------
    def registrar_execucao(self, base_id, fase, data, strings, resultados_site, arquivos, metodo="manual",
                           observacoes="", registros_api=None):
        """arquivos: lista de (nome_original, bytes). registros_api: registros já normalizados (API)."""
        with self.lock:
            execs = self.execucoes
            hashes_existentes = {a["sha256"] for e in execs for a in e.get("arquivos", []) if a["nome"].lower().endswith(EXT_REFERENCIAS)}
            num = len(execs) + 1
            eid = f"E{num:03d}"
            base_nome = B.BASES.get(base_id, {}).get("nome", base_id)
            prefixo = f"{eid}_{slugify(base_nome, 20)}_{fase}_{data}"
            salvos, regs = [], []
            for i, (nome, conteudo) in enumerate(arquivos, 1):
                ext = Path(nome).suffix.lower() or ".ris"
                destino_nome = f"{prefixo}{'_' + str(i) if len(arquivos) > 1 else ''}{ext}"
                destino = self.p("exportacoes") / destino_nome
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(conteudo)
                h = sha256_arquivo(destino)
                if ext in EXT_REFERENCIAS and metodo == "manual" and h in hashes_existentes:
                    destino.unlink()
                    for s in salvos:
                        (self.p("exportacoes") / s["nome"]).unlink(missing_ok=True)
                    raise ValueError(f"O arquivo '{nome}' já foi importado antes (mesmo conteúdo).")
                salvos.append({"nome": destino_nome, "original": nome, "sha256": h})
                if ext in EXT_REFERENCIAS and registros_api is None:
                    lidos = self._ler_exportacao(destino_nome, conteudo)
                    if not lidos:
                        raise ValueError(f"Nenhum registro encontrado em '{nome}'. Confira se é um arquivo RIS, BibTeX ou CSV da SpringerLink.")
                    regs += lidos
            if registros_api is not None:
                regs = registros_api
            controle = self.controle
            e = {
                "id": eid, "base_id": base_id, "base_nome": base_nome, "fase": fase, "data": data,
                "metodo": metodo, "strings": strings, "resultados_site": resultados_site,
                "registros": len(regs), "arquivos": salvos, "observacoes": observacoes,
                "controle_encontrados": self._casar_controle(regs, controle), "controle_total": len(controle),
                "versao_protocolo": self.protocolo.get("versao", 1), "registrado_em": agora(),
            }
            execs.append(e)
            self.salvar("execucoes", execs)
            if fase == "definitiva":
                todos = self.registros
                prox = len(todos) + 1
                for r in regs:
                    novo = {k: r.get(k, "") for k in ("titulo", "autores", "ano", "doi", "resumo", "palavras_chave",
                                                        "veiculo", "tipo_doc", "idioma", "url")}
                    novo.update({"id": f"R{prox:05d}", "base_id": base_id, "base": base_nome, "execucao": eid,
                                 "resumo_fonte": "base" if novo["resumo"] else ""})
                    todos.append(novo)
                    prox += 1
                self.salvar("registros", todos)
            self.renderizar_execucao(e)
            self.renderizar_controle()
            self.renderizar_indice_buscas()
            self.log(f"Busca {fase} registrada ({eid})",
                     f"{base_nome}; {len(regs)} registros; método {metodo}")
            if fase == "definitiva" and not self.congelado:
                self.decisao(f"Busca definitiva {eid} executada com o protocolo ainda não congelado",
                             "registrado automaticamente para transparência")
            return e

    def nome_nota_execucao(self, e) -> str:
        return nome_arquivo_seguro(f"{e['id']} {e['base_nome']} {e['fase']} {e['data']}")

    def renderizar_execucao(self, e):
        controle = self.controle
        faltando = [c for c in controle if c["id"] not in e.get("controle_encontrados", [])]
        props = {
            "tipo": "busca", "execucao": e["id"], "base": e["base_nome"], "fase": e["fase"], "data": e["data"],
            "metodo": e["metodo"], "resultados_site": e.get("resultados_site"), "registros_importados": e["registros"],
            "controle_recuperados": len(e.get("controle_encontrados", [])), "controle_total": e.get("controle_total", 0),
            "versao_protocolo": e.get("versao_protocolo"),
            "arquivos": [a["nome"] for a in e["arquivos"]],
        }
        L = [f"# {e['id']} · {e['base_nome']} · {e['fase']}\n"]
        L.append(f"Executada em {e['data']} ({'via API' if e['metodo'] == 'api' else 'exportação manual'}); registrada em {e.get('registrado_em', '')}.\n")
        L.append("## String exata executada\n")
        for i, s in enumerate(e.get("strings", []), 1):
            if len(e["strings"]) > 1:
                L.append(f"**Subconsulta {i}**")
            L.append(f"```\n{s}\n```")
        L.append("\n## Números\n")
        L.append(f"- Resultados informados pelo site/API: **{e.get('resultados_site') if e.get('resultados_site') not in (None, '') else '—'}**")
        L.append(f"- Registros nos arquivos importados: **{e['registros']}**")
        if e.get("resultados_site") not in (None, "") and str(e["resultados_site"]).isdigit() and int(e["resultados_site"]) != e["registros"]:
            L.append(f"- ⚠️ Diferença de {int(e['resultados_site']) - e['registros']} entre o total do site e o exportado: verifique lotes de exportação.")
        L.append("\n## Arquivos (integridade)\n")
        L.append("| Arquivo | Original | SHA-256 |\n|---|---|---|")
        for a in e["arquivos"]:
            L.append(f"| `{a['nome']}` | {md_escape_tabela(a['original'])} | `{a['sha256']}` |")
        L.append("\n## Conjunto de controle\n")
        if not controle:
            L.append("_Nenhum artigo de controle cadastrado._")
        else:
            L.append(f"Recuperados: **{len(e.get('controle_encontrados', []))} de {len(controle)}**.")
            if faltando:
                L.append("\nNão recuperados:")
                for c in faltando:
                    L.append(f"- {c['id']} — {c['titulo'] or c['doi']}")
        if e.get("observacoes"):
            L.append(f"\n## Observações\n\n{e['observacoes']}")
        if e["metodo"] != "api":
            L.append("\n## Evidência\n\nAnexe o print ou PDF da página de resultados na área de notas livres, abaixo da linha marcada: "
                     "o que está acima dela é regerado pelo app.")
        escrever_nota(self.p("buscas") / f"{self.nome_nota_execucao(e)}.md", props, "\n".join(L))

    def renderizar_indice_buscas(self):
        execs = self.execucoes
        L = ["# Registro de buscas\n", "Atualizado automaticamente a cada execução.\n"]
        L.append("| Execução | Base | Fase | Data | Método | Site/API | Importados | Controle |")
        L.append("|---|---|---|---|---|---|---|---|")
        for e in execs:
            L.append(f"| [[{self.nome_nota_execucao(e)}\\|{e['id']}]] | {e['base_nome']} | {e['fase']} | {e['data']} | {e['metodo']} | "
                     f"{e.get('resultados_site') or '—'} | {e['registros']} | {len(e.get('controle_encontrados', []))}/{e.get('controle_total', 0)} |")
        defs = [e for e in execs if e["fase"] == "definitiva"]
        L.append("\n## Buscas definitivas por base\n")
        L.append("| Base | Execuções | Registros |\n|---|---|---|")
        por_base = {}
        for e in defs:
            d = por_base.setdefault(e["base_nome"], [0, 0])
            d[0] += 1
            d[1] += e["registros"]
        for b, (n, r) in por_base.items():
            L.append(f"| {b} | {n} | {r} |")
        L.append(f"| **Total** | {len(defs)} | **{sum(v[1] for v in por_base.values())}** |")
        faltam = [B.BASES[b]["nome"] for b in self.protocolo.get("bases", []) if B.BASES[b]["nome"] not in por_base]
        if faltam:
            L.append(f"\nBases do protocolo ainda sem busca definitiva: {', '.join(faltam)}.")
        escrever_nota(self.p("buscas") / "Registro de buscas.md", {"tipo": "indice-buscas"}, "\n".join(L))
