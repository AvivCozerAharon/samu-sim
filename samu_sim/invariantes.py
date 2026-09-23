"""Verificador de invariantes: le o event log e o estado final de uma rodada e diz se o sistema
se manteve correto. So usa checagens exatas - a ordem entre eventos de processos diferentes
e ambigua, entao a sequencia de cada ambulancia e ordenada pela versao do registro (que o
lock otimista incrementa a cada transicao), e as checagens de fim de rodada exigem que o
sistema tenha drenado (sem chamados novos e sem falhas injetadas).

  I1 cada ambulancia segue a maquina de estados, um chamado por vez
  I2 cada chamado e concluido exatamente uma vez
  I3 depois de drenar, nenhum chamado ficou sem atendimento
  I4 depois de drenar, nenhuma ambulancia ficou presa
  I5 cada chamado recebe uma ambulancia, mais uma por vez que o reaper o devolveu
"""
from collections import Counter, defaultdict

# evento -> (estados de onde pode vir, estado para onde vai)
TRANSICOES = {
    "despachada": ({"livre"}, "a_caminho"),
    "chegou": ({"a_caminho"}, "no_local"),
    "transporte_iniciado": ({"no_local"}, "transportando"),
    "liberada": ({"no_local", "transportando"}, "livre"),
}
# eventos que mostram o sistema se recuperando de uma falha (contados, nao sao violacoes)
RECUPERACAO = ("chamado_devolvido", "reserva_falhou", "chamado_ja_despachado", "transicao_rejeitada", "reaper_liberou",
               "chamado_republicado", "despacho_duplicado_evitado", "chamado_retomado",
               "devolucao_ignorada", "ciclo_obsoleto", "ambulancia_reatribuida", "sem_ambulancia")


def _violacao(inv: str, detalhe: str, **ctx) -> dict:
    return {"invariante": inv, "detalhe": detalhe, **ctx}


def sequencia_das_ambulancias(eventos: list[dict]) -> list[dict]:
    """I1. O reaper pode liberar de qualquer estado (e o que ele existe para fazer)."""
    por_amb = defaultdict(list)
    for e in eventos:
        if (e["tipo"] in TRANSICOES or e["tipo"] == "reaper_liberou") and e.get("versao") is not None:
            por_amb[e["ambulancia_id"]].append(e)
    violacoes = []
    for amb, evs in por_amb.items():
        evs.sort(key=lambda e: e["versao"])
        estado, chamado = "livre", None
        for e in evs:
            if e["tipo"] == "reaper_liberou":
                estado, chamado = "livre", None
                continue
            origens, destino = TRANSICOES[e["tipo"]]
            c = e.get("chamado_id")
            if estado not in origens or (e["tipo"] != "despachada" and c != chamado):
                violacoes.append(_violacao(
                    "I1", f"{amb}: '{e['tipo']}' de {c} em estado '{estado}'"
                          f"{f' com {chamado}' if chamado else ''}", ambulancia_id=amb, versao=e["versao"]))
            estado, chamado = destino, (None if destino == "livre" else c)
    return violacoes


def conclusao_unica(eventos: list[dict]) -> list[dict]:
    """I2. Duas ambulancias concluindo o mesmo chamado = paciente atendido em dobro."""
    n = Counter(e["chamado_id"] for e in eventos if e["tipo"] == "liberada")
    return [_violacao("I2", f"{c} concluido {k} vezes", chamado_id=c) for c, k in n.items() if k > 1]


def uma_ambulancia_por_chamado(eventos: list[dict]) -> list[dict]:
    """I5. Mandar duas ambulancias para o mesmo paciente (sem que a primeira tenha sido dada como
    perdida pelo reaper) desperdica a frota, mesmo que a segunda desista no meio."""
    desp = Counter(e["chamado_id"] for e in eventos if e["tipo"] == "despachada")
    devol = Counter(e["chamado_id"] for e in eventos if e["tipo"] == "chamado_devolvido")
    return [_violacao("I5", f"{c} recebeu {n} ambulancias com {devol[c]} devolucao(oes)", chamado_id=c)
            for c, n in desp.items() if n > 1 + devol[c]]


def nada_perdido(chamados: list[dict]) -> list[dict]:
    """I3. Com o sistema drenado, todo chamado criado terminou atendido."""
    return [_violacao("I3", f"{c['id']} terminou {c['status']} (tentativas {c.get('tentativas', 0)}, "
                            f"publicado {c.get('publicado')})", chamado_id=c["id"])
            for c in chamados if c["status"] != "atendido"]


def frota_livre(ambulancias: list[dict]) -> list[dict]:
    """I4. Com o sistema drenado, toda ambulancia voltou a ficar disponivel."""
    return [_violacao("I4", f"{a['id']} presa em '{a['status']}' com {a.get('chamado_id')}",
                      ambulancia_id=a["id"])
            for a in ambulancias if a["status"] != "disponivel" or a.get("chamado_id")]


def inversoes_de_prioridade(eventos: list[dict], tolerancia_sim: float = 60.0) -> int:
    """Metrica, nao invariante: verdes despachados enquanto um vermelho esperava ha mais de
    `tolerancia_sim`. Com a frota saturada o numero cresce por motivo legitimo."""
    criado, despachado = {}, {}
    for e in eventos:
        if e["tipo"] == "chamado_criado":
            criado[e["chamado_id"]] = (e["ts_sim"], e.get("prioridade"))
        elif e["tipo"] == "despachada":
            despachado.setdefault(e["chamado_id"], e["ts_sim"])
    vermelhos = [(t, despachado.get(c, float("inf"))) for c, (t, p) in criado.items() if p == "vermelho"]
    n = 0
    for c, t in despachado.items():
        if criado.get(c, (0, None))[1] != "verde":
            continue
        if any(tc < t - tolerancia_sim and td > t for tc, td in vermelhos):
            n += 1
    return n


def verificar(eventos: list[dict], chamados: list[dict], ambulancias: list[dict], drenado: bool) -> dict:
    eventos = sorted(eventos, key=lambda e: (e.get("ts_real", 0), e.get("ts_sim", 0)))
    violacoes = (sequencia_das_ambulancias(eventos) + conclusao_unica(eventos)
                 + uma_ambulancia_por_chamado(eventos))
    if drenado:
        violacoes += nada_perdido(chamados) + frota_livre(ambulancias)
    tipos = Counter(e["tipo"] for e in eventos)
    return {
        "ok": not violacoes,
        "violacoes": violacoes,
        "por_invariante": dict(Counter(v["invariante"] for v in violacoes)),
        "recuperacoes": {k: tipos.get(k, 0) for k in RECUPERACAO},
        "inversoes_de_prioridade": inversoes_de_prioridade(eventos),
        "chamados": len(chamados),
        "drenado": drenado,
    }
