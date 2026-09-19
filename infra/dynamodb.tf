resource "aws_dynamodb_table" "tabelas" {
  for_each     = toset(["ambulancias", "chamados", "rodada"])
  name         = "samu-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}
