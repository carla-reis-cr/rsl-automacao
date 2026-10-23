"""Configuração local da aplicação.

Fica FORA do vault (em ~/.rsl-automacao/config.json) porque guarda chaves de API,
que não devem ser sincronizadas junto com as notas.
"""
import json
import os
from pathlib import Path

PASTA = Path(os.environ.get("RSL_CONFIG_DIR", Path.home() / ".rsl-automacao"))
ARQUIVO = PASTA / "config.json"

PADRAO = {
    "vault": "",
    "pasta_revisoes": "Revisões",
    "claude_cmd": "claude",
    "claude_modelo": "sonnet",
    "ia_registros_por_chamada": 10,
    "openalex_email": "",
    "api_max_registros": 5000,
    "chaves": {
        "scopus": "",
        "scopus_insttoken": "",
        "ieee": "",
        "springer": "",
        "wos": "",
    },
}


def carregar() -> dict:
    cfg = json.loads(json.dumps(PADRAO))
    if ARQUIVO.exists():
        try:
            dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
            chaves = dados.pop("chaves", {}) or {}
            cfg.update({k: v for k, v in dados.items() if k in PADRAO})
            cfg["chaves"].update({k: v for k, v in chaves.items() if k in PADRAO["chaves"]})
        except (OSError, ValueError):
            pass
    return cfg


def salvar(cfg: dict) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(ARQUIVO, 0o600)
    except OSError:
        pass


def raiz_revisoes(cfg: dict) -> Path:
    if not cfg.get("vault"):
        raise RuntimeError("Configure a pasta do vault em Configurações.")
    return Path(cfg["vault"]).expanduser() / cfg.get("pasta_revisoes", "Revisões")
