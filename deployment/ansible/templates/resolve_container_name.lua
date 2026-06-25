-- Resolve Docker container ID to container_name via config.v2.json
-- Caches results in-process to avoid repeated filesystem reads.
-- Fallback: short container ID (first 12 chars) if metadata unavailable.

local container_cache = {}

function resolve_container_name(tag, timestamp, record)
    local source = record["source"] or ""
    local container_id = source:match("/containers/([0-9a-f]+)/")

    if not container_id then
        record["container_name"] = "unknown"
        return 1, timestamp, record
    end

    if container_cache[container_id] then
        record["container_name"] = container_cache[container_id]
        return 1, timestamp, record
    end

    local config_path = "/data/docker/containers/" .. container_id .. "/config.v2.json"
    local f = io.open(config_path, "r")
    if f then
        local content = f:read("*a")
        f:close()
        local name = content:match('"Name":"(/[^"]+)"')
        if name then
            name = name:sub(2)
            container_cache[container_id] = name
            record["container_name"] = name
            return 1, timestamp, record
        end
    end

    local short_id = container_id:sub(1, 12)
    container_cache[container_id] = short_id
    record["container_name"] = short_id
    return 1, timestamp, record
end
