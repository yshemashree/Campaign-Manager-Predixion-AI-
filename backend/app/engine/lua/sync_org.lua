-- Write an org's limits into its gate (versioned like campaigns).
-- Cold-start guard: if the gate was missing (Redis restarted and lost it), the first slot is
-- pushed 1 s into the future, so calls sent just before the restart are still accounted for.
--
-- KEYS[1] org gate
-- ARGV[1] limit_version  ARGV[2] max_calls_per_second  ARGV[3] max_concurrent_calls

local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
if redis.call('EXISTS', KEYS[1]) == 0 then
  redis.call('HSET', KEYS[1], 'tat', now + 1000)
end
local current = tonumber(redis.call('HGET', KEYS[1], 'limit_ver') or '-1')
if tonumber(ARGV[1]) < current then return 0 end
redis.call('HSET', KEYS[1], 'limit_ver', ARGV[1], 'cps', ARGV[2], 'max_concurrent', ARGV[3])
return 1
