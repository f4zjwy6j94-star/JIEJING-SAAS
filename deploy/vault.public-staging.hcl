ui = false
disable_mlock = true

storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address = "0.0.0.0:8200"
  tls_disable = true
}

api_addr = "http://jiejing-vault:8200"
cluster_addr = "http://jiejing-vault:8201"
