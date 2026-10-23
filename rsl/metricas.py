"""Métricas de concordância para a calibração da triagem assistida."""


def encaminha(decisao: str) -> bool:
    """'incluir' e 'duvida' seguem para a leitura completa."""
    return decisao in ("incluir", "duvida")


def kappa(pares):
    """Kappa de Cohen para pares (a, b) de rótulos categóricos."""
    n = len(pares)
    if n == 0:
        return None
    cats = sorted({x for p in pares for x in p})
    po = sum(1 for a, b in pares if a == b) / n
    pe = sum((sum(1 for a, _ in pares if a == c) / n) * (sum(1 for _, b in pares if b == c) / n) for c in cats)
    if pe == 1:
        return 1.0 if po == 1 else 0.0
    return (po - pe) / (1 - pe)


def interpretar_kappa(k):
    if k is None:
        return "—"
    if k < 0:
        return "pior que o acaso"
    for limite, rotulo in ((0.20, "leve"), (0.40, "razoável"), (0.60, "moderada"), (0.80, "substancial")):
        if k <= limite:
            return rotulo
    return "quase perfeita"


def calibracao(itens):
    """itens: lista de (decisao_humana, sugestao_ia)."""
    n = len(itens)
    if n == 0:
        return None
    bin_pares = [(encaminha(h), encaminha(s)) for h, s in itens]
    vp = sum(1 for h, s in bin_pares if h and s)
    fn = sum(1 for h, s in bin_pares if h and not s)
    vn = sum(1 for h, s in bin_pares if not h and not s)
    fp = sum(1 for h, s in bin_pares if not h and s)
    sens = vp / (vp + fn) if (vp + fn) else None
    espec = vn / (vn + fp) if (vn + fp) else None
    k_bin = kappa(bin_pares)
    k_3 = kappa(itens)
    return {
        "n": n, "vp": vp, "fn": fn, "vn": vn, "fp": fp,
        "concordancia": sum(1 for h, s in bin_pares if h == s) / n,
        "sensibilidade": sens, "especificidade": espec,
        "kappa": k_bin, "kappa_interpretacao": interpretar_kappa(k_bin),
        "kappa_3": k_3, "kappa_3_interpretacao": interpretar_kappa(k_3),
    }
