import asyncio
import aiofiles
import os
import hashlib
from typing import Optional, List, Dict
from pathlib import Path
import aiohttp
from datetime import datetime
import mimetypes

class DownloadManager:
    def __init__(self, session: aiohttp.ClientSession, max_workers: int = 5):
        self.session = session
        self.semaphore = asyncio.Semaphore(max_workers)
        self.download_queue = asyncio.Queue()
        self.active_downloads = {}
        
    async def download_batch(self, media_list: List[Dict], user_id: int) -> List[Path]:
        """Download multiple files concurrently."""
        tasks = []
        for idx, media in enumerate(media_list):
            task = self._download_single(
                url=media['url'],
                media_type=media['type'],
                user_id=user_id,
                index=idx,
                metadata=media
            )
            tasks.append(task)
        
        # Run downloads with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=300  # 5 minutes total
            )
        except asyncio.TimeoutError:
            return []
        
        # Process results
        successful = []
        for result in results:
            if isinstance(result, Path) and result.exists():
                successful.append(result)
        
        return successful
    
    async def _download_single(self, url: str, media_type: str, user_id: int, index: int, metadata: Dict) -> Optional[Path]:
        """Download single file with progress tracking."""
        async with self.semaphore:
            try:
                # Generate unique filename
                url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                timestamp = int(datetime.now().timestamp())
                ext = self._get_extension(url, media_type)
                filename = f"{user_id}_{timestamp}_{url_hash}_{index}{ext}"
                
                filepath = Path(config.bot.temp_dir) / filename
                filepath.parent.mkdir(parents=True, exist_ok=True)
                
                # Download with chunked streaming
                async with self.session.get(url, timeout=30) as response:
                    if response.status != 200:
                        return None
                    
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    
                    async with aiofiles.open(filepath, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            if chunk:
                                await f.write(chunk)
                                downloaded += len(chunk)
                                
                                # Check file size limit
                                if downloaded > config.bot.max_file_size:
                                    await f.close()
                                    filepath.unlink(missing_ok=True)
                                    raise ValueError("File too large")
                
                # Verify file was downloaded
                if filepath.exists() and filepath.stat().st_size > 0:
                    return filepath
                return None
                
            except Exception as e:
                print(f"Download error: {e}")
                return None
    
    def _get_extension(self, url: str, media_type: str) -> str:
        """Get appropriate file extension."""
        # Try to get from URL
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        if path.endswith('.mp4'):
            return '.mp4'
        elif path.endswith('.mov'):
            return '.mov'
        elif path.endswith('.jpg') or path.endswith('.jpeg'):
            return '.jpg'
        elif path.endswith('.png'):
            return '.png'
        elif path.endswith('.gif'):
            return '.gif'
        
        # Default based on media type
        return '.mp4' if media_type == 'video' else '.jpg'
    
    async def cleanup_old_files(self, max_age_hours: int = 24):
        """Clean up old temporary files."""
        temp_dir = Path(config.bot.temp_dir)
        if not temp_dir.exists():
            return
        
        current_time = datetime.now().timestamp()
        for filepath in temp_dir.glob("*"):
            try:
                file_age = current_time - filepath.stat().st_mtime
                if file_age > max_age_hours * 3600:
                    filepath.unlink()
            except:
                continue