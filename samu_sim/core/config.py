"""Configuracao por variaveis de ambiente. Unico lugar que le os.environ."""
import os
from dataclasses import dataclass, fields
from typing import Mapping


@dataclass(frozen=True)
class Config:
    aws_endpoint_url: str | None = None
    aws_region: str = "us-east-1"
    fila_chamados: str = "samu-chamados"
    prefixo_fila_eventos: str = "samu-eventos-"
    prefixo_tabela: str = "samu-"
    n_workers: int = 2
    worker_id: str = "w0"
    fator: float = 20.0
    politica: str = "mais_proxima"
    roteador: str = "haversine"
    seed: int = 42
    n_ambulancias: int = 50
    chamados_por_dia: int = 300
    log_dir: str = "logs"
    dados_dir: str = "dados"
    rodada_id: str = "local"
    heartbeat_seg: float = 30.0
    reaper_timeout_seg: float = 120.0
    reaper_intervalo_seg: float = 60.0
    sync_relogio_seg: float = 10.0
    api_porta: int = 8000
    osrm_url: str = "http://localhost:5000"
    osrm_timeout_seg: float = 2.0
    matriz_path: str = "dados/matriz_eta.json"
    s3_bucket: str = ""  # vazio = nao envia event log para o S3
    reposicionamento: bool = False  # ambulancia livre vai para a base de maior demanda prevista
    demanda_path: str = "dados/demanda_prevista.json"
    reset: bool = False  # bootstrap: apaga e re-semeia mesmo se ja houver rodada

    @classmethod
    def do_ambiente(cls, env: Mapping[str, str] = os.environ) -> "Config":
        valores = {}
        for f in fields(cls):
            bruto = env.get(f.name.upper())
            if bruto is None or bruto == "":
                continue
            tipo = f.type if isinstance(f.type, type) else str
            if f.name == "aws_endpoint_url":
                valores[f.name] = bruto
            elif tipo is bool:
                valores[f.name] = bruto.strip().lower() in ("1", "true", "sim", "yes")
            elif tipo is int:
                valores[f.name] = int(bruto)
            elif tipo is float:
                valores[f.name] = float(bruto)
            else:
                valores[f.name] = bruto
        return cls(**valores)

    PRIORIDADES = ("vermelho", "amarelo", "verde")  # ordem de atendimento

    def filas_chamados(self) -> dict[str, str]:
        """Uma fila SQS por prioridade: {"vermelho": "samu-chamados-vermelho", ...}."""
        return {p: f"{self.fila_chamados}-{p}" for p in self.PRIORIDADES}

    def fila_eventos(self, worker_id: str) -> str:
        return f"{self.prefixo_fila_eventos}{worker_id}"

    def tabela(self, nome: str) -> str:
        return f"{self.prefixo_tabela}{nome}"
