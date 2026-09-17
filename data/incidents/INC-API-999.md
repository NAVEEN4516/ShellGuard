# INC-API-999: Vault Secret Purge Prevention

## Trigger Patterns
- `vault operator raft snapshot restore /tmp/empty`

## Blast Radius
All service identity tokens invalidated

## Mandatory Safe Alternative
```bash
vault kv get secret/app
```
