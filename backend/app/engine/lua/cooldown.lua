-- Push the org's next send slot back (after a 429 or repeated 5xx from Sarvam).
-- KEYS[1] org gate   ARGV[1] cooldown_ms

local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local until_ms = now + tonumber(ARGV[1])
local current = tonumber(redis.call('HGET', KEYS[1], 'cooldown_until') or '0')
if until_ms > current then redis.call('HSET', KEYS[1], 'cooldown_until', until_ms) end
return until_ms
