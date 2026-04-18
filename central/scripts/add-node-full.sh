#!/usr/bin/env bash
# Helper to generate a full node config.json and print setup instructions.
# Run on the CENTRAL SERVER after deploying a new VPC node.
#
# Usage: ./scripts/add-node-full.sh "US East" 203.0.113.10 PUBLIC_KEY SHORT_ID
set -euo pipefail

NODE_NAME="${1:?Usage: $0 'Node Name' host public_key short_id}"
NODE_HOST="${2:?}"
PUBLIC_KEY="${3:?}"
SHORT_ID="${4:?}"

echo "==> Registering node with central database..."
docker compose exec api python admin_cli.py add-node \
  "$NODE_NAME" "$NODE_HOST" "$PUBLIC_KEY" "$SHORT_ID"

echo ""
echo "==> Generating xray config.json for this node..."
echo "    (You will need to insert the PRIVATE key manually)"
echo ""

# Get the node ID from the last added node
NODE_ID=$(docker compose exec -T api python -c "
from database import SessionLocal, VPCNode
db = SessionLocal()
node = db.query(VPCNode).order_by(VPCNode.id.desc()).first()
print(node.id)
db.close()
" 2>/dev/null | tr -d '\r')

docker compose exec api python admin_cli.py gen-xray-config "$NODE_ID"

echo ""
echo "==> Copy the JSON above to /path/to/node/config/config.json on the node server."
echo "==> Replace REPLACE_WITH_PRIVATE_KEY with the actual private key."
