import time
from typing import Dict, List
from collections import defaultdict
import asyncio

class RateLimiter:
    def __init__(self, requests_per_minute: int = 30, burst_size: int = 5):
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.user_requests: Dict[int, List[float]] = defaultdict(list)
        self.lock = asyncio.Lock()
        
    async def is_allowed(self, user_id: int) -> bool:
        """Check if user is allowed to make a request."""
        async with self.lock:
            current_time = time.time()
            user_reqs = self.user_requests[user_id]
            
            # Remove old requests (older than 1 minute)
            user_reqs = [req_time for req_time in user_reqs 
                        if current_time - req_time < 60]
            self.user_requests[user_id] = user_reqs
            
            # Check rate limits
            if len(user_reqs) >= self.requests_per_minute:
                return False
            
            # Allow burst for first few requests
            if len(user_reqs) < self.burst_size:
                user_reqs.append(current_time)
                return True
            
            # Enforce rate limiting
            time_since_first = current_time - user_reqs[0]
            required_interval = 60.0 / self.requests_per_minute
            
            if time_since_first < required_interval * len(user_reqs):
                return False
            
            user_reqs.append(current_time)
            return True
    
    async def wait_if_needed(self, user_id: int, max_wait: float = 30.0) -> bool:
        """Wait if user is rate limited."""
        start_time = time.time()
        while not await self.is_allowed(user_id):
            if time.time() - start_time > max_wait:
                return False
            await asyncio.sleep(0.5)
        return True
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Get rate limit stats for user."""
        current_time = time.time()
        user_reqs = self.user_requests.get(user_id, [])
        
        recent_reqs = [req_time for req_time in user_reqs 
                      if current_time - req_time < 60]
        
        return {
            'requests_last_minute': len(recent_reqs),
            'limit': self.requests_per_minute,
            'next_reset_in': 60 - (current_time - min(recent_reqs)) if recent_reqs else 0
        }