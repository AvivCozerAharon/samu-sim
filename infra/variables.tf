variable "regiao" {
  type    = string
  default = "us-east-1"
}

variable "meu_ip_cidr" {
  type        = string
  description = "seu IP publico em CIDR (/32) para SSH e API"
}

variable "chave_ssh_publica" {
  type        = string
  description = "conteudo da sua chave publica (ed25519)"
}

variable "repo_git" {
  type        = string
  description = "URL publica do repositorio (clonado pela EC2)"
}

variable "repo_ref" {
  type    = string
  default = "master"
}

variable "n_workers" {
  type    = number
  default = 2
}

variable "fator" {
  type    = number
  default = 20
}

variable "politica" {
  type    = string
  default = "menor_eta"
}

variable "n_ambulancias" {
  type    = number
  default = 50
}

variable "chamados_por_dia" {
  type    = number
  default = 300
}
