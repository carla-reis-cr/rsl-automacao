"""Leitura do CSV exportado pela SpringerLink (Item Title, Publication Title, Item DOI, Authors, ...)."""
import csv
import io
import re

from .ris import limpar_doi

TIPOS_CSV = {
    "article": "article", "chapter": "chapter", "conference paper": "conference", "conferencepaper": "conference",
    "book": "book", "review": "review", "reference work entry": "chapter", "protocol": "other",
}


def _celula(linha: dict, *nomes) -> str:
    for n in nomes:
        v = (linha.get(n) or "").strip()
        if v:
            return v
    return ""


def ler(texto: str):
    """Devolve lista de dicionários normalizados (mesmas chaves de ris.ler).

    O CSV da Springer não traz resumo nem palavras-chave (use 'Completar resumos') e os autores vêm
    sem separador entre os nomes, então ficam como um texto único.
    """
    leitor = csv.DictReader(io.StringIO(texto.lstrip("﻿")))
    registros = []
    for linha in leitor:
        titulo = _celula(linha, "Item Title", "Title")
        if not titulo:
            continue
        tipo = _celula(linha, "Content Type").lower()
        ano = re.search(r"(19|20)\d{2}", _celula(linha, "Publication Year", "Year"))
        url = _celula(linha, "URL")
        registros.append({
            "titulo": re.sub(r"\s+", " ", titulo),
            "autores": _celula(linha, "Authors"),
            "ano": ano.group(0) if ano else "",
            "doi": limpar_doi(_celula(linha, "Item DOI", "DOI")) or limpar_doi(url),
            "resumo": "",
            "palavras_chave": "",
            "veiculo": _celula(linha, "Publication Title", "Book Series Title"),
            "tipo_doc": TIPOS_CSV.get(tipo, tipo or "other"),
            "idioma": "",
            "url": url,
        })
    return registros
