# Role da instancia: permissao SO nas filas/tabelas/bucket deste projeto.
data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "samu-sim-ec2"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

data "aws_iam_policy_document" "app" {
  statement {
    actions   = ["sqs:*"]
    resources = concat([for q in aws_sqs_queue.chamados : q.arn], [for q in aws_sqs_queue.eventos : q.arn])
  }
  # o bootstrap chama create_queue/get_queue_url (idempotentes) pelo nome
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
