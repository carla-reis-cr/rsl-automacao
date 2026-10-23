"""Utilitários para escrever no vault do Obsidian."""
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def slugify(texto: str, max_len: int = 60) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:max_len].strip("-") or "projeto"


def nome_arquivo_seguro(texto: str, max_len: int = 80) -> str:
    t = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", texto)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len].strip() or "sem titulo"


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def escrever_atomico(caminho: Path, conteudo: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(caminho.parent), prefix=".tmp-", suffix=caminho.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(conteudo)
        os.replace(tmp, caminho)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ler_json(caminho: Path, padrao):
    if caminho.exists():
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return padrao


def salvar_json(caminho: Path, dados) -> None:
    escrever_atomico(caminho, json.dumps(dados, ensure_ascii=False, indent=1))


def frontmatter(dados: dict) -> str:
    """Gera o bloco YAML de propriedades do Obsidian."""
    limpo = {k: v for k, v in dados.items() if v is not None}
    corpo = yaml.safe_dump(limpo, allow_unicode=True, sort_keys=False, width=1000)
    return f"---\n{corpo}---\n"


def ler_frontmatter(texto: str):
    """Devolve (dict, corpo)."""
    if texto.startswith("---"):
        partes = texto.split("\n---", 1)
        if len(partes) == 2:
            try:
                dados = yaml.safe_load(partes[0][3:]) or {}
            except yaml.YAMLError:
                dados = {}
            corpo = partes[1].lstrip("-").lstrip("\n")
            return dados, corpo
    return {}, texto


MARCA_NOTAS = "<!-- notas-livres: o texto abaixo desta linha é preservado pelo app -->"


def escrever_nota(caminho: Path, props: dict, corpo: str, preservar_notas: bool = True) -> None:
    """Escreve uma nota gerada, preservando o que a pessoa escreveu abaixo da marca."""
    notas = ""
    if preservar_notas and caminho.exists():
        antigo = caminho.read_text(encoding="utf-8")
        if MARCA_NOTAS in antigo:
            notas = antigo.split(MARCA_NOTAS, 1)[1]
    if preservar_notas:
        corpo = corpo.rstrip() + "\n\n" + MARCA_NOTAS + (notas if notas else "\n\n")
    escrever_atomico(caminho, frontmatter(props) + "\n" + corpo.rstrip() + "\n")


def anexar(caminho: Path, linha: str, cabecalho: str = "") -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    novo = not caminho.exists()
    with open(caminho, "a", encoding="utf-8", newline="\n") as f:
        if novo and cabecalho:
            f.write(cabecalho.rstrip() + "\n\n")
        f.write(linha.rstrip() + "\n")


def md_escape_tabela(texto) -> str:
    return str(texto if texto is not None else "").replace("|", "\\|").replace("\n", " ")
