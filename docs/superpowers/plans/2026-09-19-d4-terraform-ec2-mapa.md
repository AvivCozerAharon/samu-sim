# samu-sim — Plano D4: Terraform + EC2 + mapa ao vivo

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O mesmo `docker compose` rodando numa EC2 t3.micro com SQS, DynamoDB e S3 reais, tudo criado por Terraform; upload do event log para S3 ao encerrar; mapa Leaflet ao vivo servido pela API (polling) e endpoint `/ws/estado` para um futuro front React.

**Architecture:** `infra/` (Terraform, `us-east-1`): filas SQS, 3 tabelas DynamoDB on-demand, bucket S3, IAM role/instance profile com permissão só nesses recursos, security group (22 e 8000 só do seu IP), EC2 t3.micro Amazon Linux 2023 com user-data que instala Docker, clona o repo (público no GitHub) e sobe `docker-compose.aws.yml` (sem LocalStack/OSRM; `ROTEADOR=matriz`). Os serviços falam com a AWS real quando `AWS_ENDPOINT_URL` não está definido (boto3 usa o instance profile). A API ganha `GET /` (mapa estático Leaflet com polling de `/estado`) e `WS /ws/estado`.

**Tech Stack:** Terraform 1.16, AWS provider ~> 5, Amazon Linux 2023, Docker CE, Leaflet 1.9 via CDN, FastAPI WebSocket.

**Spec:** `docs/superpowers/specs/2026-09-18-samu-sim-design.md` (ADR 4, ADR 5, §10)

## Global Constraints

- Tudo dos planos anteriores continua valendo.
- **Custo:** só t3.micro, DynamoDB on-demand, SQS, S3. `terraform destroy` ao fim de cada sessão. Nenhum NAT, ALB, RDS, ElastiCache.
- **Segurança:** nenhuma credencial no repo; a EC2 usa instance profile; SG abre 22/8000 só para `var.meu_ip`; `*.tfvars` e `.terraform/` no `.gitignore` (já está); state local (não versionar).
- `Config.aws_endpoint_url = None` → boto3 vai para a AWS real (comportamento já existente).
- O repositório precisa estar **público no GitHub** para o user-data clonar (ou usar o zip via S3 — ver Task 4, decisão: GitHub público; é o link da entrevista de qualquer forma).

---

## Estrutura de arquivos deste plano

```
samu_sim/api/__init__.py         + GET / (mapa), WS /ws/estado
samu_sim/api/static/mapa.html    Leaflet + polling /estado + /metricas
samu_sim/eventlog/__init__.py    + enviar_para_s3(log_dir, rodada_id, bucket)
samu_sim/core/config.py          + s3_bucket
samu_sim/gerador/__main__.py, despachante, ambulancia, api  (upload no encerramento se s3_bucket)
docker-compose.aws.yml           sem localstack/osrm; env para AWS real
infra/versions.tf, variables.tf, sqs.tf, dynamodb.tf, s3.tf, iam.tf, ec2.tf, outputs.tf, user-data.sh
infra/terraform.tfvars.example
scripts/deploy.sh                terraform apply + espera API + imprime URL
tests/test_api.py (+ mapa e ws), tests/test_eventlog.py (+ s3 com stub)
```

---

### Task 1: Mapa Leaflet + `/ws/estado`

**Files:**
- Create: `samu_sim/api/static/mapa.html`
- Modify: `samu_sim/api/__init__.py`, `pyproject.toml` (incluir `static/*.html` no pacote)
- Test: `tests/test_api.py` (adicionar)

**Interfaces:**
- `GET /` → `FileResponse` de `static/mapa.html` (`text/html`).
- `WS /ws/estado` → a cada `intervalo_ws_seg` (default 1.0) envia `snapshot()` como JSON; fecha quando o cliente desconecta. Parâmetro `intervalo_ws_seg` em `criar_app`.
- `mapa.html`: Leaflet 1.9 (CDN unpkg), centro do Rio `[-22.92, -43.4]` zoom 11; bases como marcadores quadrados cinza; ambulâncias como círculos coloridos por status (`disponivel` verde, `reservada` amarelo, `a_caminho` vermelho, `no_local` roxo, `retornando` azul); chamados abertos como `x` laranja; painel no canto com `agora_sim` (formatado HH:MM), fator, P50/P90 e pendentes de `/metricas`; polling `fetch('/estado')` a cada 1 s e `/metricas` a cada 5 s; select de fator (1/2/5/10/20/50/200) + botão pausar que fazem `POST /controle`.

- [ ] **Step 1: Testes**

```python
def test_mapa_na_raiz():
    c, *_ = montar()
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "leaflet" in r.text.lower() and "/estado" in r.text


def test_ws_estado_envia_snapshot():
    c, repo, relogio, t = montar()
    with c.websocket_connect("/ws/estado") as ws:
        dados = ws.receive_json()
    assert "ambulancias" in dados and dados["ambulancias"][0]["id"] == "amb-1"
```
(`montar()` precisa passar `intervalo_ws_seg=0.01`.)

- [ ] **Step 2: Rodar e ver falhar** (404 / erro de rota).

- [ ] **Step 3: Implementar** — em `criar_app(..., intervalo_ws_seg: float = 1.0)`:

```python
from pathlib import Path
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

_STATIC = Path(__file__).parent / "static"

    @app.get("/", include_in_schema=False)
    def mapa():
        return FileResponse(_STATIC / "mapa.html", media_type="text/html")

    @app.websocket("/ws/estado")
    async def ws_estado(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                await ws.send_json(await asyncio.to_thread(snapshot))
                await asyncio.sleep(intervalo_ws_seg)
        except WebSocketDisconnect:
            pass
```
`pyproject.toml`: adicionar
```toml
[tool.setuptools.package-data]
samu_sim = ["api/static/*.html"]
```
`mapa.html` (conteúdo completo — escrever no arquivo):

```html
<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><title>samu-sim</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 html,body,#mapa{height:100%;margin:0}
 #painel{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;padding:10px 14px;border-radius:6px;
   font:13px/1.4 system-ui,sans-serif;box-shadow:0 1px 6px rgba(0,0,0,.3);min-width:220px}
 #painel h1{font-size:15px;margin:0 0 6px}
 #painel .num{font-weight:600}
 .leg span{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}
 select,button{margin-top:6px}
</style></head>
<body><div id="mapa"></div>
<div id="painel"><h1>samu-sim — Rio</h1>
 <div>hora sim: <span class="num" id="hora">--:--</span> &nbsp; fator <span class="num" id="fator">-</span></div>
 <div>P50 <span class="num" id="p50">-</span> · P90 <span class="num" id="p90">-</span> · pendentes <span class="num" id="pend">-</span></div>
 <div>atendidos <span class="num" id="atend">-</span> / <span id="total">-</span></div>
 <div class="leg" style="margin-top:6px">
  <span style="background:#2e7d32"></span>disponível <span style="background:#f9a825"></span>reservada
  <span style="background:#c62828"></span>a caminho <span style="background:#6a1b9a"></span>no local
  <span style="background:#1565c0"></span>retornando</div>
 <div>fator: <select id="selFator"><option>1</option><option>2</option><option>5</option><option>10</option><option selected>20</option><option>50</option><option>200</option></select>
  <button id="btnPausa">pausar</button></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const CORES={disponivel:'#2e7d32',reservada:'#f9a825',a_caminho:'#c62828',no_local:'#6a1b9a',retornando:'#1565c0'};
const mapa=L.map('mapa').setView([-22.92,-43.40],11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap'}).addTo(mapa);
const amb={}, cham={}; let bases=null, pausada=false;
function hhmm(s){s=Math.max(0,s%86400);return String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s%3600/60)).padStart(2,'0');}
function min(v){return v==null?'-':(v/60).toFixed(1)+' min';}
async function estado(){
  const e=await (await fetch('/estado')).json();
  document.getElementById('hora').textContent=hhmm(e.agora_sim);
  document.getElementById('fator').textContent=e.pausada?'pausado':e.fator;
  pausada=e.pausada; document.getElementById('btnPausa').textContent=pausada?'continuar':'pausar';
  if(!bases){bases=L.layerGroup().addTo(mapa);
    const vistas=new Set();
    for(const a of e.ambulancias){ if(vistas.has(a.base_id))continue; vistas.add(a.base_id);
      L.rectangle([[a.lat-0.004,a.lon-0.004],[a.lat+0.004,a.lon+0.004]],{color:'#555',weight:1,fillOpacity:.6}).bindTooltip(a.base_id).addTo(bases);} }
  const ids=new Set();
  for(const a of e.ambulancias){ ids.add(a.id);
    if(!amb[a.id]) amb[a.id]=L.circleMarker([a.lat,a.lon],{radius:6,weight:1,color:'#222',fillOpacity:.95}).bindTooltip(a.id).addTo(mapa);
    amb[a.id].setLatLng([a.lat,a.lon]).setStyle({fillColor:CORES[a.status]||'#999'}); }
  const abertos=new Set();
  for(const c of e.chamados_abertos){ abertos.add(c.id);
    if(!cham[c.id]) cham[c.id]=L.marker([c.lat,c.lon],{icon:L.divIcon({className:'',html:'<div style="color:#e65100;font:bold 18px sans-serif">×</div>',iconSize:[14,14]})}).bindTooltip(c.id+' ('+c.zona+')').addTo(mapa); }
  for(const id in cham){ if(!abertos.has(id)){mapa.removeLayer(cham[id]);delete cham[id];} }
}
async function metricas(){
  const m=await (await fetch('/metricas')).json();
  document.getElementById('p50').textContent=min(m.resposta.p50);
  document.getElementById('p90').textContent=min(m.resposta.p90);
  document.getElementById('pend').textContent=m.fila.pendentes;
  document.getElementById('atend').textContent=m.atendidos; document.getElementById('total').textContent=m.total;
}
async function controle(body){await fetch('/controle',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}); estado();}
document.getElementById('selFator').onchange=e=>controle({fator:+e.target.value});
document.getElementById('btnPausa').onclick=()=>controle({pausada:!pausada});
estado(); metricas(); setInterval(estado,1000); setInterval(metricas,5000);
</script></body></html>
```

- [ ] **Step 4: Rodar** `tests/test_api.py` → `7 passed`. Testar no navegador com o compose local (`docker compose up --build -d`, abrir `http://localhost:8000/`). Commit:

```bash
git add samu_sim/api pyproject.toml tests/test_api.py
git commit -m "feat(api): mapa Leaflet ao vivo e WebSocket /ws/estado

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Upload do event log para S3

**Files:**
- Modify: `samu_sim/core/config.py` (`s3_bucket: str = ""`), `samu_sim/eventlog/__init__.py`, os 4 `__main__.py`
- Test: `tests/test_eventlog.py` (adicionar)

**Interfaces:**
- `enviar_para_s3(log_dir, rodada_id, bucket, servico, s3=None) -> str | None` — envia `<log_dir>/<rodada_id>/<servico>.jsonl` para `s3://<bucket>/<rodada_id>/<servico>.jsonl`; retorna a chave ou `None` se `bucket` vazio ou arquivo inexistente. `s3` injetável (`boto3.client("s3")` por padrão).
- Cada entrypoint, ao encerrar: `log.fechar(); enviar_para_s3(cfg.log_dir, cfg.rodada_id, cfg.s3_bucket, <servico>)`. Os workers/api também fazem upload periódico? **Não** (YAGNI): só no encerramento; para coletar no meio, `scripts/coletar_logs.sh` faz `docker compose kill -s TERM` + upload... simplificar: o `deploy.sh` (Task 4) faz `scp -r`/`aws s3 sync` do `/opt/samu-sim/logs` da EC2 sob demanda. Upload no encerramento + `aws s3 sync` manual cobrem os casos.

- [ ] **Step 1: Teste**

```python
def test_enviar_para_s3_usa_chave_por_rodada(tmp_path):
    r = Relogio(fator=1)
    log = EventLogJsonl(tmp_path, r, servico="api", rodada_id="r1")
    log.registrar("x"); log.fechar()
    chamadas = []

    class S3:
        def upload_file(self, arquivo, bucket, chave):
            chamadas.append((Path(arquivo).name, bucket, chave))

    from samu_sim.eventlog import enviar_para_s3
    assert enviar_para_s3(tmp_path, "r1", "meu-bucket", "api", s3=S3()) == "r1/api.jsonl"
    assert chamadas == [("api.jsonl", "meu-bucket", "r1/api.jsonl")]
    assert enviar_para_s3(tmp_path, "r1", "", "api", s3=S3()) is None
    assert enviar_para_s3(tmp_path, "r1", "b", "inexistente", s3=S3()) is None
```

- [ ] **Step 2: Implementar**

```python
def enviar_para_s3(log_dir, rodada_id: str, bucket: str, servico: str, s3=None) -> str | None:
    if not bucket:
        return None
    arquivo = Path(log_dir) / rodada_id / f"{servico}.jsonl"
    if not arquivo.exists():
        return None
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    chave = f"{rodada_id}/{servico}.jsonl"
    s3.upload_file(str(arquivo), bucket, chave)
    return chave
```
Nos entrypoints, após `log.fechar()`: `enviar_para_s3(cfg.log_dir, cfg.rodada_id, cfg.s3_bucket, "<nome do servico>")` dentro de `try/except` com `logging.warning`.

- [ ] **Step 3: Rodar suíte, commit**

```bash
git add samu_sim tests/test_eventlog.py
git commit -m "feat(eventlog): upload do JSONL para S3 no encerramento dos servicos

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `docker-compose.aws.yml`

**Files:**
- Create: `docker-compose.aws.yml`

- [ ] **Step 1: Escrever** (sem `AWS_ENDPOINT_URL`, sem credenciais — instance profile; sem localstack/osrm; imagem construída na própria EC2):

```yaml
x-servico: &servico
  build: .
  restart: unless-stopped
  environment: &env
    AWS_REGION: ${AWS_REGION:-us-east-1}
    AWS_DEFAULT_REGION: ${AWS_REGION:-us-east-1}
    N_WORKERS: "2"
    LOG_DIR: /logs
    FATOR: ${FATOR:-20}
    POLITICA: ${POLITICA:-menor_eta}
    ROTEADOR: ${ROTEADOR:-matriz}
    N_AMBULANCIAS: ${N_AMBULANCIAS:-50}
    CHAMADOS_POR_DIA: ${CHAMADOS_POR_DIA:-300}
    SEED: ${SEED:-42}
    RODADA_ID: ${RODADA_ID:-aws}
    S3_BUCKET: ${S3_BUCKET:-}
  volumes:
    - ./logs:/logs
  depends_on:
    bootstrap:
      condition: service_completed_successfully

services:
  bootstrap:
    build: .
    environment: *env
    command: python -m samu_sim.infra.bootstrap
  gerador:
    <<: *servico
    command: python -m samu_sim.gerador
    restart: "no"
  despachante:
    <<: *servico
    command: python -m samu_sim.despachante
    deploy: { replicas: 2 }
  ambulancia-w0:
    <<: *servico
    command: python -m samu_sim.ambulancia
    environment: { <<: *env, WORKER_ID: w0 }
  ambulancia-w1:
    <<: *servico
    command: python -m samu_sim.ambulancia
    environment: { <<: *env, WORKER_ID: w1 }
  api:
    <<: *servico
    command: python -m samu_sim.api
    ports: ["8000:8000"]
```

- [ ] **Step 2: Validar** `docker compose -f docker-compose.aws.yml config --quiet`. Commit:

```bash
git add docker-compose.aws.yml
git commit -m "feat: compose para AWS (instance profile, matriz, S3)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Terraform

**Files:**
- Create: `infra/versions.tf`, `infra/variables.tf`, `infra/sqs.tf`, `infra/dynamodb.tf`, `infra/s3.tf`, `infra/iam.tf`, `infra/ec2.tf`, `infra/outputs.tf`, `infra/user-data.sh`, `infra/terraform.tfvars.example`

- [ ] **Step 1: `versions.tf`**

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}
provider "aws" {
  region = var.regiao
  default_tags { tags = { projeto = "samu-sim" } }
}
```

- [ ] **Step 2: `variables.tf`**

```hcl
variable "regiao"       { type = string, default = "us-east-1" }
variable "meu_ip_cidr"  { type = string, description = "seu IP publico /32 para SSH e API" }
variable "repo_git"     { type = string, default = "https://github.com/<usuario>/samu-sim.git" }
variable "repo_ref"     { type = string, default = "master" }
variable "n_workers"    { type = number, default = 2 }
variable "chave_ssh_publica" { type = string, description = "conteudo da sua chave publica (ed25519)" }
variable "fator"        { type = number, default = 20 }
variable "politica"     { type = string, default = "menor_eta" }
variable "n_ambulancias"{ type = number, default = 50 }
variable "chamados_por_dia" { type = number, default = 300 }
```

- [ ] **Step 3: `sqs.tf`, `dynamodb.tf`, `s3.tf`**

```hcl
# sqs.tf
resource "aws_sqs_queue" "chamados" {
  name                       = "samu-chamados"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 3600
}
resource "aws_sqs_queue" "eventos" {
  for_each                   = toset([for k in range(var.n_workers) : "w${k}"])
  name                       = "samu-eventos-${each.key}"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 3600
}

# dynamodb.tf
resource "aws_dynamodb_table" "tabelas" {
  for_each     = toset(["ambulancias", "chamados", "rodada"])
  name         = "samu-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute { name = "id"; type = "S" }
}

# s3.tf
resource "random_id" "sufixo" { byte_length = 3 }
resource "aws_s3_bucket" "logs" {
  name          = "samu-sim-logs-${random_id.sufixo.hex}"
  force_destroy = true
}
resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id
  block_public_acls = true; block_public_policy = true; ignore_public_acls = true; restrict_public_buckets = true
}
```
(`random` provider: adicionar `random = { source = "hashicorp/random", version = "~> 3.6" }` em `versions.tf`.)

- [ ] **Step 4: `iam.tf`** — role da instância com permissão **apenas** nas filas/tabelas/bucket criados:

```hcl
data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service", identifiers = ["ec2.amazonaws.com"] }
  }
}
resource "aws_iam_role" "ec2" {
  name               = "samu-sim-ec2"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}
data "aws_iam_policy_document" "app" {
  statement {
    actions   = ["sqs:*"]
    resources = concat([aws_sqs_queue.chamados.arn], [for q in aws_sqs_queue.eventos : q.arn])
  }
  statement {
    actions   = ["sqs:GetQueueUrl", "sqs:ListQueues", "sqs:CreateQueue"]
    resources = ["*"]
  }
  statement {
    actions   = ["dynamodb:*"]
    resources = [for t in aws_dynamodb_table.tabelas : t.arn]
  }
  statement {
    actions   = ["dynamodb:ListTables"]
    resources = ["*"]
  }
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.logs.arn, "${aws_s3_bucket.logs.arn}/*"]
  }
}
resource "aws_iam_role_policy" "app" {
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.app.json
}
resource "aws_iam_instance_profile" "ec2" {
  name = "samu-sim-ec2"
  role = aws_iam_role.ec2.name
}
```
Nota: o bootstrap chama `create_queue`/`create_table` (idempotentes) — `CreateQueue` sobre fila existente com mesmos atributos retorna a URL; `create_table` em tabela existente dá `ResourceInUseException` que o bootstrap já ignora. Por isso `sqs:CreateQueue` está liberado (sem ele o bootstrap falha com AccessDenied). **DynamoDB `CreateTable` não é liberado** de propósito: a tabela já existe; se falhar por AccessDenied em vez de ResourceInUse, ajustar `_criar_tabela` para tratar `AccessDeniedException` como "já existe" — verificar na Task 5 e corrigir se necessário.

- [ ] **Step 5: `ec2.tf` + `user-data.sh`**

```hcl
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter { name = "name"; values = ["al2023-ami-2023*-x86_64"] }
}
resource "aws_key_pair" "chave" {
  key_name   = "samu-sim"
  public_key = var.chave_ssh_publica
}
resource "aws_security_group" "ec2" {
  name = "samu-sim-ec2"
  ingress { from_port = 22;   to_port = 22;   protocol = "tcp"; cidr_blocks = [var.meu_ip_cidr] }
  ingress { from_port = 8000; to_port = 8000; protocol = "tcp"; cidr_blocks = [var.meu_ip_cidr] }
  egress  { from_port = 0;    to_port = 0;    protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }
}
resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.micro"
  key_name               = aws_key_pair.chave.key_name
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  user_data = templatefile("${path.module}/user-data.sh", {
    repo_git = var.repo_git, repo_ref = var.repo_ref, regiao = var.regiao,
    s3_bucket = aws_s3_bucket.logs.bucket, fator = var.fator, politica = var.politica,
    n_ambulancias = var.n_ambulancias, chamados_por_dia = var.chamados_por_dia,
  })
  root_block_device { volume_size = 16 }
  tags = { Name = "samu-sim" }
}
```
`user-data.sh`:
```bash
#!/bin/bash
set -euxo pipefail
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
curl -sL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
# swap: t3.micro tem 1 GB; o build da imagem precisa de folga
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
cd /opt && git clone --branch ${repo_ref} ${repo_git} samu-sim && cd samu-sim
cat > .env <<EOF
AWS_REGION=${regiao}
S3_BUCKET=${s3_bucket}
FATOR=${fator}
POLITICA=${politica}
N_AMBULANCIAS=${n_ambulancias}
CHAMADOS_POR_DIA=${chamados_por_dia}
RODADA_ID=aws-$(date +%Y%m%d-%H%M)
EOF
chown -R ec2-user:ec2-user /opt/samu-sim
docker compose -f docker-compose.aws.yml --env-file .env up --build -d
```

- [ ] **Step 6: `outputs.tf`** e `terraform.tfvars.example`

```hcl
output "ip_publico"  { value = aws_instance.app.public_ip }
output "url_api"     { value = "http://${aws_instance.app.public_ip}:8000" }
output "bucket_logs" { value = aws_s3_bucket.logs.bucket }
output "ssh"         { value = "ssh ec2-user@${aws_instance.app.public_ip}" }
```
```hcl
# copie para terraform.tfvars (ignorado pelo git) e preencha
meu_ip_cidr       = "SEU.IP.PUBLICO.AQUI/32"
chave_ssh_publica = "ssh-ed25519 AAAA... seu@email"
repo_git          = "https://github.com/SEU_USUARIO/samu-sim.git"
```

- [ ] **Step 7: `terraform init && terraform validate && terraform fmt`** em `infra/` (sem apply ainda). Commit:

```bash
git add infra
git commit -m "feat(infra): Terraform para SQS, DynamoDB, S3, IAM e EC2 t3.micro

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Publicar no GitHub, deploy, validar, destruir

**Files:**
- Create: `scripts/deploy.sh`
- Modify: `README.md`

- [ ] **Step 1: GitHub** — `gh repo create samu-sim --public --source=. --push` (ou criar pelo site e `git remote add origin ... && git push -u origin master`). Atualizar `repo_git` no `terraform.tfvars`.

- [ ] **Step 2: Chave SSH e IP** — se não houver `~/.ssh/id_ed25519.pub`: `ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519`. IP: `curl -s https://checkip.amazonaws.com`. Preencher `infra/terraform.tfvars`.

- [ ] **Step 3: `scripts/deploy.sh`**

```bash
#!/usr/bin/env bash
# terraform apply + espera a API responder + imprime URLs. Uso: bash scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../infra"
terraform apply -auto-approve
URL=$(terraform output -raw url_api)
echo ">> esperando a API em $URL (user-data leva ~3-5 min: dnf + build da imagem)"
for i in $(seq 1 60); do
  if curl -sf "$URL/saude" >/dev/null 2>&1; then echo ">> API no ar: $URL"; exit 0; fi
  sleep 10
done
echo ">> API nao respondeu em 10 min; veja: $(terraform output -raw ssh) 'sudo tail -50 /var/log/cloud-init-output.log'"
exit 1
```

- [ ] **Step 4: Deploy** — `bash scripts/deploy.sh`. Verificar: `curl $URL/metricas`, abrir `$URL/` no navegador (mapa), `ssh ... 'cd /opt/samu-sim && docker compose -f docker-compose.aws.yml ps'`. Se o bootstrap falhar por permissão (ver nota da Task 4), corrigir e `git push` + `ssh ... 'cd /opt/samu-sim && git pull && docker compose -f docker-compose.aws.yml --env-file .env up --build -d'`.

- [ ] **Step 5: Coletar logs e destruir**

```bash
ssh ec2-user@IP 'cd /opt/samu-sim && docker compose -f docker-compose.aws.yml stop && aws s3 sync logs s3://BUCKET/'
aws s3 ls s3://BUCKET/ --recursive
cd infra && terraform destroy -auto-approve
```
Verificar `aws ec2 describe-instances --query 'Reservations[].Instances[].State.Name'` → tudo `terminated`.

- [ ] **Step 6: README** — seção "AWS (D4)": pré-requisitos (CLI, Terraform, tfvars), `bash scripts/deploy.sh`, o que é criado e quanto custa, `terraform destroy`, screenshot do mapa (salvar em `docs/img/mapa.png`). Marcar D4 no Estado. Commit + push.

---

## Self-review

- **Spec:** ADR 4 (mapa polling + `/ws/estado`) → Task 1; ADR 5 (EC2 t3.micro + compose + SQS/DynamoDB reais via Terraform; matriz na AWS) → Tasks 3–5; §10 (SQS, DynamoDB on-demand, S3, IAM role, EC2 AL2023 + Docker, alarme de billing — já criado por CLI) → Task 4; §4.3 event log para S3 → Task 2.
- **Placeholders:** `<usuario>` em `repo_git` é preenchido na Task 5 Step 1 (valor depende do GitHub do Aviv) — não é placeholder de implementação.
- **Consistência:** nomes de filas/tabelas do Terraform (`samu-chamados`, `samu-eventos-w{k}`, `samu-{tabela}`) batem com `Config` defaults; `S3_BUCKET` env ↔ `Config.s3_bucket`; `enviar_para_s3` chamada com o mesmo `servico` usado no `EventLogJsonl`.
