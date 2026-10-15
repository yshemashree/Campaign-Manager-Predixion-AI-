-- Give back a reservation that won't be used (no contact was due).
-- The pacing slot is returned only if nobody booked after it; otherwise it is a harmless gap.
--
-- KEYS[1] org gate   KEYS[2] campaign gate   KEYS[3] org in-flight zset
-- ARGV[1] slot_ms    ARGV[2] margin_ms       ARGV[3] attempt_ref

redis.call('ZREM', KEYS[3], ARGV[3])
local slot = tonumber(ARGV[1])
local margin = tonumber(ARGV[2])

local o = redis.call('HMGET', KEYS[1], 'cps', 'tat')
local cps = tonumber(o[1]) or 0
if cps > 0 and tonumber(o[2]) == slot + math.ceil((1000 + margin) / cps) then
  redis.call('HSET', KEYS[1], 'tat', slot)
end

local c = redis.call('HMGET', KEYS[2], 'aps', 'tat')
local aps = tonumber(c[1]) or 0
if aps > 0 and tonumber(c[2]) == slot + math.ceil((1000 + margin) / aps) then
  redis.call('HSET', KEYS[2], 'tat', slot)
end
return 1
