resource "random_id" "sufixo" {
  byte_length = 3
}

resource "aws_s3_bucket" "logs" {
  bucket        = "samu-sim-logs-${random_id.sufixo.hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
