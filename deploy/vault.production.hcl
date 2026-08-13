ui = false
disable_mlock = false

storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address = "0.0.0.0:8200"
  tls_disable = true
}

# This address is reachable only on the private production Docker network.
# Caddy and Docker publish no Vault host port.
api_addr = "http://jiejing-vault:8200"
cluster_addr = "http://jiejing-vault:8201"
