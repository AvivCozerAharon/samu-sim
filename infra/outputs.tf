output "ip_publico" {
  value = aws_instance.app.public_ip
}

output "url_api" {
  value = "http://${aws_instance.app.public_ip}:8000"
}

output "bucket_logs" {
  value = aws_s3_bucket.logs.bucket
}

output "ssh" {
  value = "ssh ec2-user@${aws_instance.app.public_ip}"
}
