from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, Field, ValidationError
from playwright.sync_api import sync_playwright
from moviepy.editor import VideoFileClip
from starlette.background import BackgroundTask
import os
import uuid
from pathlib import Path
import io

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory to store videos
VIDEO_DIR = Path("videos/")
VIDEO_DIR.mkdir(exist_ok=True)  # Ensure the directory exists

class ScreenshotRequest(BaseModel):
    url: HttpUrl
    width: int = Field(1920, ge=100, le=3840)
    height: int = Field(1080, ge=100, le=2160)

@app.post("/screenshot/")
def take_screenshot(request: ScreenshotRequest):
    try:
        url = str(request.url)
        width = request.width
        height = request.height
        
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()

            try:
                page.goto(url, wait_until="load", timeout=10000)  # Timeout after 10 seconds
            except Exception as e:
                browser.close()
                raise HTTPException(status_code=500, detail=f"Failed to load URL: {str(e)}")

            page.add_style_tag(content="""
                ::-webkit-scrollbar { display: none; }
                body { -ms-overflow-style: none; scrollbar-width: none; }
            """)
            
            screenshot_bytes = page.screenshot()
            browser.close()

        return StreamingResponse(io.BytesIO(screenshot_bytes), media_type="image/png")
    
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Invalid input: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

class ScrollingVideoRequest(BaseModel):
    url: HttpUrl
    width: int = Field(1920, ge=100, le=3840)
    height: int = Field(1080, ge=100, le=2160)
    duration: int = Field(10, ge=1, le=15)

def remove_files(*file_paths):
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Successfully removed: {file_path}")
            else:
                print(f"File not found: {file_path}")
        except Exception as e:
            print(f"Error removing file {file_path}: {e}")

@app.post("/scrolling-video/")
def create_scrolling_video(request: ScrollingVideoRequest):
    original_video_path = None
    trimmed_video_path = None
    
    try:
        url = str(request.url)
        width = request.width
        height = request.height
        duration = request.duration

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=str(VIDEO_DIR),
                record_video_size={"width": width, "height": height},
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="load", timeout=10000)
            except Exception as e:
                context.close()
                raise HTTPException(status_code=500, detail=f"Failed to load URL: {str(e)}")

            page.add_style_tag(content="""
                ::-webkit-scrollbar { display: none; }
                body { -ms-overflow-style: none; scrollbar-width: none; }
            """)

            viewport_height = page.evaluate("window.innerHeight")

            page.evaluate(f"""
                const scrollAmount = {(viewport_height / 2) + (viewport_height / 3)};
                setInterval(() => {{
                    window.scrollBy({{
                        top: scrollAmount,
                        left: 0,
                        behavior: 'smooth'
                    }});
                }}, 1500);
            """)

            page.wait_for_timeout((duration + 1) * 1000)

            original_video_path = page.video.path()
            context.close()

            trimmed_video_name = f"trimmed_video_{uuid.uuid4()}.webm"
            trimmed_video_path = VIDEO_DIR / trimmed_video_name

            with VideoFileClip(original_video_path) as video:
                video_duration = video.duration
                if video_duration < duration:
                    raise HTTPException(status_code=400, detail=f"Recorded video is shorter than {duration} seconds.")
                
                start_time = max(video_duration - duration, 0)
                trimmed_video = video.subclip(start_time, video_duration)
                trimmed_video.write_videofile(str(trimmed_video_path), codec="libvpx")

        def cleanup():
            remove_files(original_video_path, trimmed_video_path)

        return FileResponse(
            path=trimmed_video_path,
            media_type="video/webm",
            background=BackgroundTask(cleanup)
        )

    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Invalid input: {e}")
    except Exception as e:
        if original_video_path:
            remove_files(original_video_path)
        if trimmed_video_path and os.path.exists(trimmed_video_path):
            remove_files(trimmed_video_path)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
