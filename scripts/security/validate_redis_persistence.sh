#!/bin/bash
# Validate Redis persistence configuration
# Tests that Redis RDB snapshots persist across container restarts

set -e

echo "================================================================="
echo "Redis Persistence Validation (Session 50 Phase 0)"
echo "================================================================="
echo ""

# Test 1: Write test data to Redis
echo "[Test 1] Writing test data to Redis..."
docker exec redis redis-cli SET test_persistence_key "test_value_$(date +%s)" >/dev/null
docker exec redis redis-cli SET test_persistence_key2 "test_value2_$(date +%s)" >/dev/null
echo "✅ Test data written to Redis"
echo ""

# Test 2: Trigger RDB snapshot (force save)
echo "[Test 2] Triggering RDB snapshot..."
docker exec redis redis-cli SAVE >/dev/null
echo "✅ RDB snapshot triggered"
echo ""

# Test 3: Verify RDB snapshot exists in container
echo "[Test 3] Verifying RDB snapshot exists in container..."
if docker exec redis ls -lh /data/dump.rdb 2>/dev/null; then
    echo "✅ RDB snapshot exists in container"
else
    echo "❌ FAIL: RDB snapshot not found in container"
    exit 1
fi
echo ""

# Test 4: Verify RDB snapshot exists on host
echo "[Test 4] Verifying RDB snapshot exists on host..."
if ls -lh data/redis_data/dump.rdb 2>/dev/null; then
    echo "✅ RDB snapshot exists on host filesystem"
else
    echo "❌ FAIL: RDB snapshot not found on host"
    exit 1
fi
echo ""

# Test 5: Restart Redis container
echo "[Test 5] Restarting Redis container..."
docker restart redis >/dev/null 2>&1
sleep 5

# Wait for Redis to be healthy
echo "Waiting for Redis to become healthy..."
for i in {1..30}; do
    if docker exec redis redis-cli ping >/dev/null 2>&1; then
        echo "✅ Redis restarted and healthy"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ FAIL: Redis did not become healthy after restart"
        exit 1
    fi
    sleep 1
done
echo ""

# Test 6: Verify data persists after restart
echo "[Test 6] Verifying data persists after restart..."
VALUE=$(docker exec redis redis-cli GET test_persistence_key 2>/dev/null)
if [[ -n "$VALUE" ]]; then
    echo "✅ Data persisted across restart: $VALUE"
else
    echo "❌ FAIL: Data lost after restart"
    exit 1
fi
echo ""

# Test 7: Verify service tokens persist (DB 1)
echo "[Test 7] Verifying service tokens persist (Database 1)..."
TOKEN_COUNT=$(docker exec redis redis-cli -n 1 KEYS "service_token:*" | wc -l)
if [ "$TOKEN_COUNT" -gt 0 ]; then
    echo "✅ Service tokens persisted: $TOKEN_COUNT tokens found"
else
    echo "⚠️  WARNING: No service tokens found (this is normal on first run)"
fi
echo ""

# Cleanup test data
echo "[Cleanup] Removing test data..."
docker exec redis redis-cli DEL test_persistence_key test_persistence_key2 >/dev/null
echo "✅ Test data cleaned up"
echo ""

echo "================================================================="
echo "✅ All Redis persistence tests PASSED"
echo "================================================================="
exit 0
