resource "aws_sqs_queue" "chamados" {
  for_each                   = toset(["vermelho", "amarelo", "verde"])
  name                       = "samu-chamados-${each.key}"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 3600
}

resource "aws_sqs_queue" "eventos" {
  for_each                   = toset([for k in range(var.n_workers) : "w${k}"])
  name                       = "samu-eventos-${each.key}"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 3600
}
