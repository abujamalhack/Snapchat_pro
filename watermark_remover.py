import cv2
import numpy as np
from PIL import Image, ImageDraw
import subprocess
import tempfile
from pathlib import Path
import asyncio
from moviepy.editor import VideoFileClip

class WatermarkRemover:
    def __init__(self):
        self.watermark_positions = [
            (10, 10),  # Top-left
            (10, -10), # Bottom-left
            (-10, 10), # Top-right
            (-10, -10) # Bottom-right
        ]
    
    async def remove_watermark(self, input_path: Path, output_path: Path) -> bool:
        """Remove watermark from image or video."""
        if input_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif']:
            return await self._remove_from_image(input_path, output_path)
        elif input_path.suffix.lower() in ['.mp4', '.mov', '.avi']:
            return await self._remove_from_video(input_path, output_path)
        return False
    
    async def _remove_from_image(self, input_path: Path, output_path: Path) -> bool:
        """Remove watermark from image using inpainting."""
        try:
            # Read image
            img = cv2.imread(str(input_path))
            if img is None:
                return False
            
            height, width = img.shape[:2]
            
            # Create mask for watermark areas
            mask = np.zeros(img.shape[:2], dtype=np.uint8)
            
            # Common watermark positions (adjust based on Snapchat's watermark)
            positions = [
                (width - 100, height - 50, width - 20, height - 20),  # Bottom-right corner
                (20, height - 50, 100, height - 20),  # Bottom-left corner
                (width // 2 - 40, height - 50, width // 2 + 40, height - 20),  # Center bottom
            ]
            
            for x1, y1, x2, y2 in positions:
                cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
            
            # Apply inpainting
            result = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
            
            # Save result
            cv2.imwrite(str(output_path), result)
            return True
            
        except Exception as e:
            print(f"Image watermark removal error: {e}")
            return False
    
    async def _remove_from_video(self, input_path: Path, output_path: Path) -> bool:
        """Remove watermark from video using FFmpeg."""
        try:
            # Method 1: Crop if watermark is in corner
            crop_filter = "crop=iw-50:ih-50:25:25"  # Adjust based on watermark position
            
            cmd = [
                'ffmpeg', '-i', str(input_path),
                '-vf', crop_filter,
                '-c:a', 'copy',
                '-y', str(output_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and output_path.exists():
                return True
            
            # Method 2: Blur watermark area
            blur_filter = "boxblur=5:5"
            
            cmd = [
                'ffmpeg', '-i', str(input_path),
                '-vf', blur_filter,
                '-c:a', 'copy',
                '-y', str(output_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            return process.returncode == 0 and output_path.exists()
            
        except Exception as e:
            print(f"Video watermark removal error: {e}")
            return False
    
    def detect_watermark(self, image_path: Path) -> List[tuple]:
        """Detect watermark positions in image."""
        positions = []
        try:
            img = cv2.imread(str(image_path))
            if img is None:
                return positions
            
            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Threshold to find bright areas (watermarks are often bright/white)
            _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
            
            # Find contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if 100 < area < 10000:  # Watermark size range
                    x, y, w, h = cv2.boundingRect(contour)
                    positions.append((x, y, x + w, y + h))
            
            return positions
        except:
            return positions