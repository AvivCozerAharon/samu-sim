data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023*-x86_64"]
  }
}

resource "aws_key_pair" "chave" {
  key_name   = "samu-sim"
  public_key = var.chave_ssh_publica
}

resource "aws_security_group" "ec2" {
  name        = "samu-sim-ec2"
  description = "samu-sim: SSH e API so do meu IP"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.meu_ip_cidr]
  }
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.meu_ip_cidr]
  }
  ingress { # mesa (terminal pessoal) na mesma instancia
    from_port   = 8100
    to_port     = 8100
    protocol    = "tcp"
    cidr_blocks = [var.meu_ip_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.micro"
  key_name               = aws_key_pair.chave.key_name
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  user_data = templatefile("${path.module}/user-data.sh", {
    repo_git         = var.repo_git
    repo_ref         = var.repo_ref
    regiao           = var.regiao
    s3_bucket        = aws_s3_bucket.logs.bucket
    fator            = var.fator
    politica         = var.politica
    n_ambulancias    = var.n_ambulancias
    chamados_por_dia = var.chamados_por_dia
  })

  root_block_device {
    volume_size = 16
  }

  tags = { Name = "samu-sim" }
}
