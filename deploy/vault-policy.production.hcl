# Least-privilege policy for the Jiejing production backend token.
# It cannot enumerate or read secrets outside the production keyspace.
path "secret/data/jiejing-production/*" {
  capabilities = ["create", "update", "read", "delete"]
}

# KV v2 permanent revocation deletes metadata after the data versions are
# removed. List/read support backend-only status checks without returning the
# secret value to the frontend.
path "secret/metadata/jiejing-production/*" {
  capabilities = ["list", "read", "delete"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}
