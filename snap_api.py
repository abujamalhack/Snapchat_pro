import asyncio
import json
import re
import random
from typing import Dict, List, Optional, Tuple
import aiohttp
from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import hashlib

class SnapchatAPI:
    def __init__(self, session: ClientSession):
        self.session = session
        self.cache = {}
        self.rate_limit = asyncio.Semaphore(10)  # Max 10 concurrent requests
        
    async def _make_request(self, url: str, headers: dict = None) -> str:
        """Make HTTP request with rate limiting and retries."""
        async with self.rate_limit:
            if headers is None:
                headers = {
                    'User-Agent': random.choice(config.snap.user_agents),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                }
            
            for attempt in range(config.snap.retry_attempts):
                try:
                    timeout = ClientTimeout(total=config.bot.request_timeout)
                    async with self.session.get(url, headers=headers, timeout=timeout) as response:
                        if response.status == 200:
                            return await response.text()
                        elif response.status == 429:  # Rate limited
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        else:
                            await asyncio.sleep(1)
                except Exception as e:
                    if attempt == config.snap.retry_attempts - 1:
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
            return ""
    
    async def get_user_stories(self, username: str) -> List[Dict]:
        """Fetch all stories from a Snapchat username."""
        cache_key = f"stories_{username}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        url = config.snap.api_endpoints["story"].format(username)
        html = await self._make_request(url)
        
        if not html:
            return []
        
        # Method 1: Try to find JSON-LD structured data
        stories = self._parse_json_ld(html)
        if stories:
            self.cache[cache_key] = stories
            return stories
        
        # Method 2: Parse JavaScript data
        stories = self._parse_js_data(html)
        if stories:
            self.cache[cache_key] = stories
            return stories
        
        # Method 3: Regex fallback
        stories = self._parse_regex(html)
        self.cache[cache_key] = stories
        return stories
    
    def _parse_json_ld(self, html: str) -> List[Dict]:
        """Parse JSON-LD structured data."""
        stories = []
        try:
            soup = BeautifulSoup(html, 'lxml')
            scripts = soup.find_all('script', type='application/ld+json')
            
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        for item in data:
                            if item.get('@type') in ['VideoObject', 'ImageObject']:
                                story = {
                                    'url': item.get('contentUrl', ''),
                                    'type': 'video' if item['@type'] == 'VideoObject' else 'image',
                                    'duration': item.get('duration', ''),
                                    'timestamp': item.get('uploadDate', ''),
                                    'width': item.get('width', 0),
                                    'height': item.get('height', 0)
                                }
                                if story['url']:
                                    stories.append(story)
                except:
                    continue
        except:
            pass
        return stories
    
    def _parse_js_data(self, html: str) -> List[Dict]:
        """Parse JavaScript embedded data."""
        stories = []
        try:
            # Look for window.__INITIAL_STATE__ pattern
            pattern = r'window\.__INITIAL_STATE__\s*=\s*({.*?});'
            match = re.search(pattern, html, re.DOTALL)
            
            if match:
                data = json.loads(match.group(1))
                # Navigate through possible data structures
                for key in ['story', 'stories', 'media', 'items']:
                    if key in data:
                        items = data[key] if isinstance(data[key], list) else [data[key]]
                        for item in items:
                            if isinstance(item, dict):
                                media_url = item.get('mediaUrl') or item.get('videoUrl') or item.get('imageUrl')
                                if media_url:
                                    stories.append({
                                        'url': media_url,
                                        'type': 'video' if 'video' in media_url else 'image',
                                        'id': item.get('id', '')
                                    })
        except:
            pass
        return stories
    
    def _parse_regex(self, html: str) -> List[Dict]:
        """Fallback regex parsing."""
        stories = []
        
        # Find all video URLs
        video_patterns = [
            r'"videoUrl":"(https://[^"]+\.mp4[^"]*)"',
            r'src="(https://[^"]+\.mp4[^"]*)"',
            r'data-video-url="(https://[^"]+\.mp4[^"]*)"',
        ]
        
        # Find all image URLs
        image_patterns = [
            r'"imageUrl":"(https://[^"]+\.jpg[^"]*)"',
            r'src="(https://[^"]+\.jpg[^"]*)"',
            r'data-image-url="(https://[^"]+\.jpg[^"]*)"',
        ]
        
        for pattern in video_patterns:
            for match in re.findall(pattern, html, re.IGNORECASE):
                stories.append({'url': match, 'type': 'video'})
        
        for pattern in image_patterns:
            for match in re.findall(pattern, html, re.IGNORECASE):
                stories.append({'url': match, 'type': 'image'})
        
        # Remove duplicates
        unique_stories = []
        seen_urls = set()
        for story in stories:
            if story['url'] not in seen_urls:
                seen_urls.add(story['url'])
                unique_stories.append(story)
        
        return unique_stories[:10]  # Limit to 10 items
    
    async def get_spotlight_video(self, video_id: str) -> Optional[Dict]:
        """Fetch Spotlight video by ID."""
        url = f"https://www.snapchat.com/spotlight/{video_id}"
        html = await self._make_request(url)
        
        if not html:
            return None
        
        # Extract video metadata
        patterns = [
            r'"videoUrl":"(https://[^"]+\.mp4[^"]*)"',
            r'property="og:video" content="(https://[^"]+\.mp4[^"]*)"',
            r'<video[^>]+src="(https://[^"]+\.mp4[^"]*)"',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return {
                    'url': match.group(1),
                    'type': 'video',
                    'id': video_id,
                    'source': 'spotlight'
                }
        
        return None