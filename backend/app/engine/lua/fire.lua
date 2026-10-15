-- The last check, right before the HTTP request goes out. Atomic, using Redis's clock.
-- If this returns ok, the call may be sent; otherwise it must not be.
--
-- KEYS[1] campaign gate   KEYS[2] org gate   KEYS[3] org in-flight zset
-- KEYS[4] phone lock      KEYS[5] send marker   KEYS[6] org fires zset (for rate charts)
-- ARGV[1] slot_ms  ARGV[2] late_tolerance_ms  ARGV[3] attempt_ref  ARGV[4] campaign_ver
-- ARGV[5] limit_ver  ARGV[6] phone_lock_ttl_s  ARGV[7] call_ttl_ms
--
-- Returns {1, 'ok', 0} or {0, reason, wait_ms}.

local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local c = redis.call('HMGET', KEYS[1], 'state', 'window_until', 'ver')
-- Paused, stopped, or changed since the slot was booked: never send.
if c[1] ~= 'running' or c[3] ~= ARGV[4] then return {0, 'not_running', 0} end
if now >= (tonumber(c[2]) or 0) then return {0, 'window_closed', 0} end

local slot = tonumber(ARGV[1])
if now < slot then return {0, 'early', slot - now} end
if now > slot + tonumber(ARGV[2]) then return {0, 'late', 0} end  -- never send late
if redis.call('HGET', KEYS[2], 'limit_ver') ~= ARGV[5] then return {0, 'limit_changed', 0} end
if not redis.call('ZSCORE', KEYS[3], ARGV[3]) then return {0, 'reservation_lost', 0} end

local holder = redis.call('GET', KEYS[4])
if holder and holder ~= ARGV[3] then return {0, 'phone_busy', 0} end

-- The send-intent marker. NX: if the reaper already revoked this attempt, it loses.
if not redis.call('SET', KEYS[5], 'sent', 'NX', 'EX', 86400) then return {0, 'revoked', 0} end

redis.call('SET', KEYS[4], ARGV[3], 'EX', tonumber(ARGV[6]))
redis.call('ZADD', KEYS[3], now + tonumber(ARGV[7]), ARGV[3])  -- now a live call
redis.call('ZADD', KEYS[6], now, ARGV[3])
return {1, 'ok', 0}
