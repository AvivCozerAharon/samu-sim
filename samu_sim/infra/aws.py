"""Implementacoes AWS de Fila (SQS) e Repositorio (DynamoDB), via boto3.
Funcionam contra LocalStack (endpoint_url) e contra a AWS real (endpoint None)."""
import json
import types
import typing
from dataclasses import fields
from decimal import Decimal
from enum import Enum

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from samu_sim.core import modelos
from samu_sim.core.config import Config
from samu_sim.core.modelos import (Ambulancia, Chamado, Rodada, StatusAmbulancia, StatusChamado,
                                   transicao_valida)
from samu_sim.infra.fila import Mensagem
from samu_sim.infra.repositorio import ConflitoVersao

RODADA_ID = "atual"


# ---------- clientes ----------
def cliente_sqs(cfg: Config):
    return boto3.client("sqs", region_name=cfg.aws_region, endpoint_url=cfg.aws_endpoint_url)


def recurso_dynamo(cfg: Config):
    return boto3.resource("dynamodb", region_name=cfg.aws_region, endpoint_url=cfg.aws_endpoint_url)


# ---------- serializacao ----------
def para_item(obj) -> dict:
    """dataclass -> item DynamoDB (float vira Decimal, enum vira str, None fica None)."""
    item = {}
    for f in fields(obj):
        v = getattr(obj, f.name)
        if isinstance(v, Enum):
            v = v.value
        elif isinstance(v, float):
            v = Decimal(repr(v))
        item[f.name] = v
    return item


def _tipo_base(anot):
    """float | None -> float; StrEnum -> a enum; str -> str."""
    if isinstance(anot, str):
        anot = eval(anot, vars(modelos))  # noqa: S307 - anotacoes vindas do proprio modulo
    if isinstance(anot, types.UnionType) or typing.get_origin(anot) is typing.Union:
        args = [a for a in typing.get_args(anot) if a is not type(None)]
        return args[0]
    return anot


def de_item(cls, item: dict):
    """item DynamoDB -> dataclass, convertendo Decimal pelo tipo anotado no campo."""
    valores = {}
    for f in fields(cls):
        v = item.get(f.name)
        tipo = _tipo_base(f.type)
        if v is None:
            valores[f.name] = None
        elif isinstance(tipo, type) and issubclass(tipo, Enum):
            valores[f.name] = tipo(v)
        elif tipo is bool:
            valores[f.name] = bool(v)
        elif tipo is float:
            valores[f.name] = float(v)
        elif tipo is int:
            valores[f.name] = int(v)
        else:
            valores[f.name] = v
    return cls(**valores)


# ---------- SQS ----------
class FilaSQS:
    def __init__(self, sqs, url: str, espera_seg: int = 1):
        self._sqs = sqs
        self._url = url
        self._espera = espera_seg

    def publicar(self, corpo: dict) -> None:
        self._sqs.send_message(QueueUrl=self._url, MessageBody=json.dumps(corpo))

    def receber(self, max_msgs: int = 10) -> list[Mensagem]:
        r = self._sqs.receive_message(QueueUrl=self._url, MaxNumberOfMessages=min(max_msgs, 10),
                                      WaitTimeSeconds=self._espera)
        return [Mensagem(id=m["MessageId"], corpo=json.loads(m["Body"]), handle=m["ReceiptHandle"])
                for m in r.get("Messages", [])]

    def ack(self, msg: Mensagem) -> None:
        try:
            self._sqs.delete_message(QueueUrl=self._url, ReceiptHandle=msg.handle)
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("ReceiptHandleIsInvalid", "InvalidParameterValue"):
                raise

    def adiar(self, msg: Mensagem, seg: float) -> None:
        try:
            self._sqs.change_message_visibility(QueueUrl=self._url, ReceiptHandle=msg.handle,
                                                VisibilityTimeout=max(0, int(round(seg))))
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("ReceiptHandleIsInvalid", "InvalidParameterValue",
                                                   "MessageNotInflight"):
                raise

    def tamanho(self) -> int:
        attrs = self._sqs.get_queue_attributes(
            QueueUrl=self._url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
        return int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"])


# ---------- DynamoDB ----------
def _conflito(e: ClientError) -> bool:
    return e.response["Error"]["Code"] == "ConditionalCheckFailedException"


def _scan_tudo(tabela, **kw) -> list[dict]:
    itens, r = [], tabela.scan(**kw)
    itens.extend(r.get("Items", []))
    while "LastEvaluatedKey" in r:
        r = tabela.scan(ExclusiveStartKey=r["LastEvaluatedKey"], **kw)
        itens.extend(r.get("Items", []))
    return itens


class RepositorioDynamo:
    def __init__(self, dynamo, cfg: Config):
        self._amb = dynamo.Table(cfg.tabela("ambulancias"))
        self._ch = dynamo.Table(cfg.tabela("chamados"))
        self._rod = dynamo.Table(cfg.tabela("rodada"))

    # --- ambulancias ---
    def salvar_ambulancia(self, a: Ambulancia) -> None:
        self._amb.put_item(Item=para_item(a))

    def obter_ambulancia(self, id: str) -> Ambulancia | None:
        item = self._amb.get_item(Key={"id": id}, ConsistentRead=True).get("Item")
        return de_item(Ambulancia, item) if item else None

    def listar_ambulancias(self, status: StatusAmbulancia | None = None,
                           worker_id: str | None = None) -> list[Ambulancia]:
        cond = None
        if status is not None:
            cond = Attr("status").eq(str(status))
        if worker_id is not None:
            c2 = Attr("worker_id").eq(worker_id)
            cond = c2 if cond is None else cond & c2
        kw = {"ConsistentRead": True}
        if cond is not None:
            kw["FilterExpression"] = cond
        return [de_item(Ambulancia, i) for i in _scan_tudo(self._amb, **kw)]

    def reservar_ambulancia(self, id: str, versao: int, chamado_id: str,
                            heartbeat_em: float = 0.0) -> Ambulancia:
        return self.transicionar(id, StatusAmbulancia.DISPONIVEL, StatusAmbulancia.RESERVADA,
                                 versao, chamado_id=chamado_id, heartbeat_em=heartbeat_em)

    def transicionar(self, id: str, de: StatusAmbulancia, para: StatusAmbulancia,
                     versao: int, **campos) -> Ambulancia:
        if not transicao_valida(de, para):
            raise ConflitoVersao(f"transicao invalida {de}->{para}")
        return self._update_condicional(
            id, campos | {"status": str(para)},
            cond="#status = :de AND versao = :v", valores={":de": str(de), ":v": versao}, versao=versao)

    def liberar_ambulancia(self, id: str, versao: int, lat: float, lon: float,
                           worker_id: str | None = None) -> Ambulancia:
        campos = {"status": str(StatusAmbulancia.DISPONIVEL), "chamado_id": None, "lat": lat, "lon": lon}
        if worker_id:
            campos["worker_id"] = worker_id
        return self._update_condicional(id, campos, cond="versao = :v", valores={":v": versao}, versao=versao)

    def reatribuir_worker(self, id: str, versao: int, worker_id: str) -> Ambulancia:
        return self._update_condicional(
            id, {"worker_id": worker_id}, cond="#status = :d AND versao = :v",
            valores={":d": str(StatusAmbulancia.DISPONIVEL), ":v": versao}, versao=versao)

    # workers vivos: um item por worker na tabela da rodada (id "worker#w0"), com o heartbeat
    def registrar_worker(self, worker_id: str, ts: float) -> None:
        self._rod.put_item(Item={"id": f"worker#{worker_id}", "heartbeat_em": Decimal(repr(ts))})

    def listar_workers(self) -> dict[str, float]:
        itens = _scan_tudo(self._rod, ConsistentRead=True, FilterExpression=Attr("id").begins_with("worker#"))
        return {i["id"].split("#", 1)[1]: float(i["heartbeat_em"]) for i in itens}

    def _update_condicional(self, id: str, campos: dict, cond: str, valores: dict, versao: int) -> Ambulancia:
        nomes = {"#status": "status"}
        sets = ["versao = :nv"]
        vals = dict(valores) | {":nv": versao + 1}
        for k, v in campos.items():
            nomes[f"#{k}"] = k
            sets.append(f"#{k} = :{k}")
            vals[f":{k}"] = Decimal(repr(v)) if isinstance(v, float) else v
        try:
            r = self._amb.update_item(
                Key={"id": id}, UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression=cond, ExpressionAttributeNames=nomes,
                ExpressionAttributeValues=vals, ReturnValues="ALL_NEW")
        except ClientError as e:
            if _conflito(e):
                raise ConflitoVersao(f"{id}: condicao falhou ({cond})") from None
            raise
        return de_item(Ambulancia, r["Attributes"])

    def atualizar_posicao_se_disponivel(self, id: str, lat: float, lon: float) -> bool:
        try:
            self._amb.update_item(
                Key={"id": id}, UpdateExpression="SET lat = :lat, lon = :lon",
                ConditionExpression="#status = :disp",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":lat": Decimal(repr(lat)), ":lon": Decimal(repr(lon)),
                                           ":disp": str(StatusAmbulancia.DISPONIVEL)})
            return True
        except ClientError as e:
            if _conflito(e):
                return False
            raise

    def atualizar_heartbeat(self, id: str, ts: float) -> None:
        self._amb.update_item(Key={"id": id}, UpdateExpression="SET heartbeat_em = :t",
                              ExpressionAttributeValues={":t": Decimal(repr(ts))})

    # --- chamados ---
    def salvar_chamado(self, c: Chamado) -> None:
        self._ch.put_item(Item=para_item(c))

    def criar_chamado(self, c: Chamado) -> bool:
        try:
            self._ch.put_item(Item=para_item(c), ConditionExpression="attribute_not_exists(id)")
            return True
        except ClientError as e:
            if _conflito(e):
                return False
            raise

    def salvar_chamado_se(self, c: Chamado, status: StatusChamado, ambulancia_id: str | None,
                          publicado: bool | None = None) -> None:
        item = para_item(c)
        item.pop("publicado", None)  # por padrao nao mexe no outbox
        if publicado is not None:
            item["publicado"] = publicado
        nomes = {"#status": "status"}
        vals = {":s": str(status)}
        if ambulancia_id is None:
            cond_amb = "(attribute_not_exists(ambulancia_id) OR attribute_type(ambulancia_id, :tnull))"
            vals[":tnull"] = "NULL"
        else:
            cond_amb = "ambulancia_id = :a"
            vals[":a"] = ambulancia_id
        sets, i = [], 0
        for k, v in item.items():
            if k == "id":
                continue
            i += 1
            nomes[f"#c{i}"] = k
            vals[f":c{i}"] = v
            sets.append(f"#c{i} = :c{i}")
        try:
            self._ch.update_item(Key={"id": c.id}, UpdateExpression="SET " + ", ".join(sets),
                                 ConditionExpression=f"#status = :s AND {cond_amb}",
                                 ExpressionAttributeNames=nomes, ExpressionAttributeValues=vals)
        except ClientError as e:
            if _conflito(e):
                raise ConflitoVersao(f"{c.id}: esperado ({status}, {ambulancia_id})") from None
            raise

    def marcar_publicado(self, id: str) -> None:
        self._ch.update_item(Key={"id": id}, UpdateExpression="SET publicado = :t",
                             ExpressionAttributeValues={":t": True})

    def obter_chamado(self, id: str) -> Chamado | None:
        item = self._ch.get_item(Key={"id": id}, ConsistentRead=True).get("Item")
        return de_item(Chamado, item) if item else None

    def listar_chamados(self) -> list[Chamado]:
        return [de_item(Chamado, i) for i in _scan_tudo(self._ch, ConsistentRead=True)]

    # --- rodada ---
    def salvar_rodada(self, r: Rodada) -> None:
        item = para_item(r)
        item["id"] = RODADA_ID
        self._rod.put_item(Item=item)

    def obter_rodada(self) -> Rodada | None:
        item = self._rod.get_item(Key={"id": RODADA_ID}, ConsistentRead=True).get("Item")
        return de_item(Rodada, item) if item else None
