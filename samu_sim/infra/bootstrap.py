"""Cria filas SQS e tabelas DynamoDB (LocalStack ou AWS) e semeia frota + rodada.
Uso: python -m samu_sim.infra.bootstrap"""
import json
import time
from pathlib import Path

from botocore.exceptions import ClientError

from samu_sim.core.config import Config
from samu_sim.core.modelos import Rodada
from samu_sim.gerador.demanda import carregar_bases
from samu_sim.infra.aws import RODADA_ID, RepositorioDynamo, cliente_sqs, recurso_dynamo
from samu_sim.local import montar_frota

TABELAS = ("ambulancias", "chamados", "rodada")


def _nomes_filas(cfg: Config) -> list[str]:
    return list(cfg.filas_chamados().values()) + [cfg.fila_eventos(f"w{k}") for k in range(cfg.n_workers)]


def _criar_tabela(dynamo, nome: str) -> None:
    try:
        t = dynamo.create_table(TableName=nome, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                                AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                                BillingMode="PAY_PER_REQUEST")
        t.wait_until_exists()
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise


def _apagar_tabela(dynamo, nome: str) -> None:
    try:
        t = dynamo.Table(nome)
        t.delete()
        t.wait_until_not_exists()
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise


def carregar_alocacao(caminho: Path, n_ambulancias: int) -> dict[str, int] | None:
    """dados/alocacao.json (gerado pelo otimizador de turnos). Ignorado se a soma nao bater."""
    if not caminho.exists():
        return None
    alocacao = {k: int(v) for k, v in json.loads(caminho.read_text(encoding="utf-8")).items()}
    if sum(alocacao.values()) != n_ambulancias:
        print(f"alocacao.json soma {sum(alocacao.values())} != N_AMBULANCIAS={n_ambulancias}; usando round-robin")
        return None
    return alocacao


def criar_recursos(cfg: Config) -> None:
    sqs, dynamo = cliente_sqs(cfg), recurso_dynamo(cfg)
    for nome in _nomes_filas(cfg):
        sqs.create_queue(QueueName=nome, Attributes={"VisibilityTimeout": "30"})
    for t in TABELAS:
        _criar_tabela(dynamo, cfg.tabela(t))


def apagar_recursos(cfg: Config) -> None:
    sqs, dynamo = cliente_sqs(cfg), recurso_dynamo(cfg)
    for nome in _nomes_filas(cfg):
        try:
            sqs.delete_queue(QueueUrl=sqs.get_queue_url(QueueName=nome)["QueueUrl"])
        except ClientError:
            pass
    for t in TABELAS:
        _apagar_tabela(dynamo, cfg.tabela(t))


def semear(cfg: Config, repo: RepositorioDynamo | None = None, agora_real=time.time) -> Rodada:
    """Zera tabelas e filas, grava a frota e a rodada com o checkpoint do relogio."""
    sqs, dynamo = cliente_sqs(cfg), recurso_dynamo(cfg)
    for t in TABELAS:
        _apagar_tabela(dynamo, cfg.tabela(t))
        _criar_tabela(dynamo, cfg.tabela(t))
    for nome in _nomes_filas(cfg):
        try:
            sqs.purge_queue(QueueUrl=sqs.get_queue_url(QueueName=nome)["QueueUrl"])
        except ClientError as e:
            if e.response["Error"]["Code"] != "AWS.SimpleQueueService.PurgeQueueInProgress":
                raise
    repo = repo or RepositorioDynamo(dynamo, cfg)
    bases = carregar_bases(Path(cfg.dados_dir) / "bases.csv")
    alocacao = carregar_alocacao(Path(cfg.dados_dir) / "alocacao.json", cfg.n_ambulancias)
    for a in montar_frota(bases, cfg.n_ambulancias, cfg.n_workers, alocacao):
        repo.salvar_ambulancia(a)
    rodada = Rodada(RODADA_ID, cfg.seed, cfg.politica, cfg.fator, cfg.n_ambulancias, cfg.roteador,
                    inicio_real=agora_real(), inicio_sim=0.0,
                    alocacao=json.dumps(alocacao) if alocacao else None)
    repo.salvar_rodada(rodada)
    return rodada


def main() -> None:
    """Idempotente: se ja existe uma rodada, nao mexe em nada (docker compose start
    re-executa este one-shot; apagar o estado no meio de uma rodada quebraria os
    ciclos em voo). Para recomecar: RESET=1 ou docker compose down -v."""
    cfg = Config.do_ambiente()
    criar_recursos(cfg)
    existente = RepositorioDynamo(recurso_dynamo(cfg), cfg).obter_rodada()
    if existente is not None and not cfg.reset:
        print(f"bootstrap: rodada existente (fator {existente.fator}, politica {existente.politica}); "
              f"mantendo. Use RESET=1 para re-semear.")
        return
    r = semear(cfg)
    print(f"bootstrap ok: {cfg.n_ambulancias} ambulancias, {cfg.n_workers} workers, "
          f"fator {r.fator}, politica {r.politica}, endpoint {cfg.aws_endpoint_url}")


if __name__ == "__main__":
    main()
