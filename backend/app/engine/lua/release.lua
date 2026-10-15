-- A call is over (or was never placed): free its concurrency place and its phone lock.
--
-- KEYS[1] org in-flight zset   KEYS[2] phone lock
-- ARGV[1] attempt_ref

redis.call('ZREM', KEYS[1], ARGV[1])
if redis.call('GET', KEYS[2]) == ARGV[1] then
  redis.call('DEL', KEYS[2])
end
return 1
