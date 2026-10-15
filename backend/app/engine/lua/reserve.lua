-- Book the next send slot for one call. Runs atomically inside Redis, using Redis's clock,
-- so every worker on every machine shares one view of the limits.
--
-- KEYS[1] org gate      hash: cps, max_concurrent, tat, cooldown_until, limit_ver
-- KEYS[2] campaign gate hash: state, ver, window_until, aps, tat, rr
-- KEYS[3] org in-flight zset: attempt_ref -> expiry (ms). Reserved + live calls.
-- ARGV[1] horizon_ms     how far ahead a slot may be booked
-- ARGV[2] margin_ms      safety margin added to the per-second spacing
-- ARGV[3] attempt_ref
-- ARGV[4] reserve_ttl_ms how long an unused reservation holds a concurrency place
--
-- Returns {1, slot_ms, delay_ms, campaign_ver, limit_ver, rr} when granted,
--         {0, reason, retry_after_ms} when denied.

local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local c = redis.call('HMGET', KEYS[2], 'state', 'window_until', 'aps', 'tat', 'ver')
if c[1] ~= 'running' then return {0, 'not_running', 1000} end
local window_until = tonumber(c[2]) or 0
if now >= window_until then return {0, 'window_closed', 1000} end

local o = redis.call('HMGET', KEYS[1], 'cps', 'max_concurrent', 'tat', 'cooldown_until', 'limit_ver')
local cps = tonumber(o[1]) or 0
local max_concurrent = tonumber(o[2]) or 0
if cps <= 0 or max_concurrent <= 0 then return {0, 'org_disabled', 1000} end  -- missing => fail closed

-- Concurrency: calls reserved or live right now for this org (expired entries dropped first).
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
if redis.call('ZCARD', KEYS[3]) >= max_concurrent then return {0, 'org_busy', 250} end

-- Pacing (GCRA): org slots are spaced t_org ms apart, campaign slots t_camp ms apart.
local margin = tonumber(ARGV[2])
local aps = tonumber(c[3]) or 1
local t_org = math.ceil((1000 + margin) / cps)
local t_camp = math.ceil((1000 + margin) / aps)

local slot = math.max(now, tonumber(o[3]) or 0, tonumber(o[4]) or 0)
local ready = math.max(now, tonumber(c[4]) or 0)
-- The campaign isn't ready for the org's next slot: leave that slot for another campaign.
if ready > slot then return {0, 'campaign_pace', ready - now} end
local horizon = tonumber(ARGV[1])
if slot - now > horizon then return {0, 'org_pace', slot - now - horizon} end
if slot >= window_until then return {0, 'window_closed', 1000} end

redis.call('HSET', KEYS[1], 'tat', slot + t_org)
redis.call('HSET', KEYS[2], 'tat', slot + t_camp)
local rr = redis.call('HINCRBY', KEYS[2], 'rr', 1)
redis.call('ZADD', KEYS[3], slot + tonumber(ARGV[4]), ARGV[3])
return {1, slot, slot - now, c[5], o[5], rr}
