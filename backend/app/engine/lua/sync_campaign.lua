-- Write a campaign's state into its gate, unless the write is older than what is stored.
-- Versioning stops a slow scheduler from undoing a pause (a classic fencing token).
--
-- KEYS[1] campaign gate
-- ARGV[1] state_version  ARGV[2] state  ARGV[3] attempts_per_second  ARGV[4] window_until_ms

local current = tonumber(redis.call('HGET', KEYS[1], 'ver') or '-1')
if tonumber(ARGV[1]) < current then return 0 end
redis.call('HSET', KEYS[1], 'ver', ARGV[1], 'state', ARGV[2], 'aps', ARGV[3], 'window_until', ARGV[4])
redis.call('PEXPIRE', KEYS[1], 86400000)
return 1
