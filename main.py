from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict
import os
from pathlib import Path
import logging
from datetime import datetime, timedelta
import google.generativeai as genai
from dotenv import load_dotenv
import imghdr
from tenacity import retry, stop_after_attempt, wait_exponential
from contextlib import asynccontextmanager
from itertools import cycle
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 基本配置
load_dotenv()

# 載入多組 API 金鑰
API_KEYS = [
    os.getenv('GOOGLE_API_KEY_1'),
    os.getenv('GOOGLE_API_KEY_2'),
    os.getenv('GOOGLE_API_KEY_3')
]

# 檢查是否所有金鑰都已設置
if not all(API_KEYS):
    raise ValueError("未設置所有 GOOGLE_API_KEY 環境變數")

# 創建一個循環迭代器
api_key_cycle = cycle(API_KEYS)

# 更新 configure 函數以使用循環的 API 金鑰
def configure_genai():
    """配置 Gemini API，每次調用時使用下一個可用的 API 金鑰"""
    current_key = next(api_key_cycle)
    genai.configure(api_key=current_key)
    logger.info(f"使用 API 金鑰: {current_key}")

# 日誌配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 路徑配置
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 快取和限制配置
request_cache: Dict[str, tuple] = {}
rate_limit_cache: Dict[str, int] = {}
ALLOWED_IMAGE_TYPES = {'jpeg', 'jpg', 'png', 'gif'}

# 模型定義
class PostRequest(BaseModel):
    """貼文請求的資料模型"""
    platform: str        # 社交平台
    length: str         # 文章長度
    style: str          # 文章風格
    image_path: Optional[str] = None  # 圖片路徑

class PostResponse(BaseModel):
    content: str
    image_url: Optional[str] = None

# FastAPI 應用配置
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(cleanup_old_uploads, 'interval', minutes=5)
        scheduler.start()
        logger.info("已啟動自動清理排程（每5分鐘執行一次）")
        yield
    finally:
        logger.info("應用程式關閉中...")
        scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 輔助函數
def validate_image(file_path: str) -> bool:
    img_type = imghdr.what(file_path)
    return img_type in ALLOWED_IMAGE_TYPES

async def check_rate_limit(user_id: str) -> bool:
    """
    檢查用戶請求頻率限制
    每個用戶每天最多 50 次請求
    """
    current_time = datetime.now()
    today = current_time.strftime('%Y-%m-%d')
    key = f"{user_id}:{today}"
    
    for k in list(rate_limit_cache.keys()):
        if not k.endswith(today):
            del rate_limit_cache[k]
    
    count = rate_limit_cache.get(key, 0)
    if count >= 50:
        return False
    
    rate_limit_cache[key] = count + 1
    return True

async def cleanup_old_uploads():
    try:
        current_time = datetime.now()
        for file_path in UPLOAD_DIR.glob('*'):
            file_modified_time = datetime.fromtimestamp(file_path.stat().st_mtime)
            if current_time - file_modified_time > timedelta(minutes=5):
                file_path.unlink()
        logger.info("已清理超過5分鐘的上傳圖片")
    except Exception as e:
        logger.error(f"清理上傳圖片時發生錯誤: {str(e)}")

# API 路由
@app.get("/")
async def read_root():
    try:
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse(content="找不到 index.html 文件", status_code=404)
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
            return HTMLResponse(content=content)
    except Exception as e:
        logger.error(f"讀取 index.html 時發生錯誤: {str(e)}")
        return HTMLResponse(content="讀取頁面時發生錯誤", status_code=500)

@app.post("/upload-image/")
async def upload_image(file: UploadFile = File(...)):
    try:
        file_extension = file.filename.split(".")[-1].lower()
        if file_extension not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="不支援的圖片格式。僅支援 JPG、PNG 和 GIF")

        file_name = f"image_{os.urandom(8).hex()}.{file_extension}"
        file_path = UPLOAD_DIR / file_name
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        if not validate_image(str(file_path)):
            os.remove(file_path)
            raise HTTPException(status_code=400, detail="無效的圖片文件")
        
        if os.path.getsize(file_path) > 5 * 1024 * 1024:
            os.remove(file_path)
            raise HTTPException(status_code=400, detail="圖片大小不能超過 5MB")
        
        return JSONResponse({
            "success": True,
            "file_path": f"/static/uploads/{file_name}"
        })
    except HTTPException as he:
        return JSONResponse({"success": False, "error": he.detail}, status_code=he.status_code)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def generate_content(platform: str, length: str, style: str, image_path: Optional[str] = None, description: Optional[str] = None) -> str:
    try:
        configure_genai()  # 使用下一個 API 金鑰

        if not image_path:
            raise ValueError("請先上傳圖片")

        # 定義字數限制
        length_text = {
            "0-5": "5字以內",
            "5-10": "5-10字",
            "10-20": "10-20字",
            "20-50": "20-50字",
            "50+": "50字以上"
        }.get(length, "適當長度")

        # 定義平台特性
        platform_characteristics = {
            "facebook": """
            Facebook用戶特性：
            - 年齡層較高（35歲以上）
            - 偏好正式、溫和的表達方式
            - 適合加入一些生活智慧或勸世話語
            - 文案要像長輩在說話，親切溫馨
            - 可以適度加入一些懷舊元素
            """,
            "instagram": """
            Instagram用戶特性：
            - 年齡層10-30歲
            - 使用流行語、hashtag
            - 口吻��鬆活潑，非正式
            - 喜歡使用當下流行的表達方式
            - 除非是正經內容，否則要用年輕人的語氣
            """,
            "tiktok": """
            TikTok用戶特性：
            - 年齡層和教育程度偏低
            - 用語要簡單直白
            - 可以很誇張、很戲劇化
            - 不需要太在意邏輯性
            - 重點是要吸引眼球、製造話題
            """
        }.get(platform, "一般社群媒體用戶")

        # 根據不同風格調整 prompt
        style_prompts = {
            "funny": f"""
            請用輕鬆逗趣的方式，為這張圖片創作一段搞笑的貼文。
            {platform_characteristics}
            要求：
            1. 用詼諧幽默的語氣，可以適當誇張或玩梗
            2. 根據平台特性使用適合的網路用語和流行語
            3. 不要太正經，要讓目標用戶群覺得有趣
            4. 可以用誇張的擬人化描述或超現實的想像
            5. 適當加入2-3個逗趣的emoji
            6. 確保文字長度符合要求：{length_text}
            7. 請用繁體中文
            """,
            "sad": f"""
            請仔細觀察這張圖片，並以感性悲傷的風格，創作一段觸動人心的��文。
            {platform_characteristics}
            要求：
            1. 根據平台用戶特性調整感性程度
            2. 描述圖片中的憂傷元素
            3. 使用平台常見的表達方式
            4. 適當加入2-3個相關的emoji
            5. 確保文字長度符合要求：{length_text}
            6. 請用繁體中文
            """,
            "motivational": f"""
            請仔細觀察這張圖片，並以勵志激勵的風格，創作一段振奮人心的貼文。
            {platform_characteristics}
            要求：
            1. 根據平台用戶特性調整勵志內容
            2. 描述圖片中的正面元素
            3. 使用平台常見的表達方式
            4. 適當加入2-3個相關的emoji
            5. 確保文字長度符合要求：{length_text}
            6. 請用繁體中文
            """,
            "informative": f"""
            請仔細觀察這張圖片，並以專業資訊的風格，創作一段富有知識性的貼文。
            {platform_characteristics}
            要求：
            1. 根據平台用戶特性調整專業內容深度
            2. 描述圖片中的專業元素和知識點
            3. 使用平台常見的表達方式
            4. 適當加入2-3個相關的emoji
            5. 確保文字長度符合要求：{length_text}
            6. 請用繁體中文
            """
        }

        # 獲取對應風格的 prompt
        prompt = style_prompts.get(style, f"""
            請仔細觀察這張圖片，並以一般的風格，創作一段貼文。
            {platform_characteristics}
            要求：
            1. 根據平台用戶特性調整表達方式
            2. 描述圖片中的關鍵元素
            3. 使用平台常見的表達方式
            4. 適當加入2-3個相關的emoji
            5. 確保文字長度符合要求：{length_text}
            6. 請用繁體中文
        """)

        style_text = {
            "sad": "感性悲傷", "funny": "幽默有趣",
            "motivational": "勵志激勵", "informative": "專業資訊"
        }.get(style, "一般")

        model = genai.GenerativeModel('gemini-1.5-pro')
        relative_path = image_path.replace('/static/', '', 1)
        full_image_path = STATIC_DIR / relative_path
        
        if not full_image_path.exists():
            raise ValueError(f"找不到圖片: {full_image_path}")
        
        image = genai.upload_file(str(full_image_path))
        response = model.generate_content([prompt, image])
        
        if not response.text:
            raise ValueError("生成的內容為空")
        return response.text.strip()
            
    except Exception as e:
        logger.error(f"生成內容時發生錯誤: {str(e)}")
        if "429" in str(e):
            raise Exception("API 請求次數已達上限，請稍後再試")
        raise Exception(str(e))

@app.post("/generate-post/")
async def generate_post(
    request: Request,
    platform: str = Form(...),
    length: str = Form(...),
    style: str = Form(...),
    image_path: Optional[str] = Form(None),
    description: Optional[str] = Form(None)
):
    """
    生成社交媒體貼文的主要端點
    - 檢查請求頻率限制
    - 檢查快取是否存在相同請求
    - 調用 Gemini API 生成內容
    - 儲存結果到快取
    """
    try:
        logger.info(f"收到生成請求: platform={platform}, length={length}, style={style}, image_path={image_path}, description={description}")
        
        if not await check_rate_limit(request.client.host):
            raise HTTPException(status_code=429, detail="已達到今日請求限制，請明天再試")

        cache_key = f"{platform}:{length}:{style}:{image_path}:{description}"
        
        if cache_key in request_cache:
            content, _ = request_cache[cache_key]
            logger.info("使用快取內容")
            return JSONResponse({
                "success": True,
                "content": content,
                "image_path": image_path,
                "cached": True
            })

        logger.info("開始生成新內容")
        content = await generate_content(platform, length, style, image_path, description)
        logger.info(f"生成內容成功: {content[:100]}...")
        
        request_cache[cache_key] = (content, datetime.now())
        return JSONResponse({
            "success": True,
            "content": content,
            "image_path": image_path,
            "cached": False
        })
    except Exception as e:
        logger.error(f"生成貼文時發生錯誤: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="localhost", port=5100, reload=True)

