import os
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Request, Cookie, Depends, Query
from typing import List, Optional
from dotenv import load_dotenv
import asyncpraw
import praw
import prawcore
import asyncprawcore
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import aiofiles
import jwt

# Load environment variables
load_dotenv()

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT")

# Script app creds (used ONLY for fetching flair options)
REDDIT_SCRIPT_CLIENT_ID = os.getenv("REDDIT_SCRIPT_CLIENT_ID", REDDIT_CLIENT_ID)
REDDIT_SCRIPT_CLIENT_SECRET = os.getenv("REDDIT_SCRIPT_CLIENT_SECRET", REDDIT_CLIENT_SECRET)
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")

JWT_SECRET = os.getenv("JWT_SECRET", "supersecret123")  # Use env var in prod!
JWT_ALGORITHM = "HS256"
FRONTEND_DOMAIN = os.environ.get("FRONTEND_DOMAIN")

if not all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT]):
    raise RuntimeError("Missing Reddit API credentials. Please set env vars.")

def get_asyncpraw_reddit_with_refresh(refresh_token: str):
    return asyncpraw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
        refresh_token=refresh_token,
    )

def decode_jwt(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

reddit_post_app = FastAPI()

reddit_post_app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_DOMAIN],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

def get_refresh_token_from_auth(
    authorization: Optional[str] = Header(None),
    reddit_token: Optional[str] = Cookie(None)
) -> str:
    """
    Priority:
      1) Cookie 'reddit_token' (JWT containing {"refresh_token": ...})
      2) Authorization: Bearer <refresh_token> (dev/debug)
    """
    if reddit_token:
        user = decode_jwt(reddit_token)
        if not user or "refresh_token" not in user:
            raise HTTPException(status_code=401, detail="Invalid or expired reddit_token cookie")
        return user["refresh_token"]
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    raise HTTPException(status_code=401, detail="Authentication required (Bearer token or cookie)")

# ----------------- Helper: Script PRAW for flair-only fetches -----------------

def get_script_praw_for_flair() -> praw.Reddit:
    """
    Build a PRAW client using the Script app + password grant.
    Used ONLY for reading user-selectable link flair templates.
    """
    missing = []
    for k, v in [
        ("REDDIT_SCRIPT_CLIENT_ID", REDDIT_SCRIPT_CLIENT_ID),
        ("REDDIT_SCRIPT_CLIENT_SECRET", REDDIT_SCRIPT_CLIENT_SECRET),
        ("REDDIT_USERNAME", REDDIT_USERNAME),
        ("REDDIT_PASSWORD", REDDIT_PASSWORD),
    ]:
        if not v:
            missing.append(k)
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing Script credentials: {', '.join(missing)}")

    return praw.Reddit(
        client_id=REDDIT_SCRIPT_CLIENT_ID,
        client_secret=REDDIT_SCRIPT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT or "sub_finder_ai/0.1 by SchmeedsMcSchmeeds",
    )

# ----------------------------- POST to Reddit (OAuth) -----------------------------

@reddit_post_app.post("/post_to_reddit")
async def post_to_reddit(
    request: Request,
    subreddit: str = Form(...),
    title: str = Form(...),
    body: str = Form(""),
    link: str = Form(""),
    flair_id: Optional[str] = Form(None),
    nsfw: Optional[bool] = Form(False),
    brand_affiliate: Optional[bool] = Form(False),
    files: Optional[List[UploadFile]] = File(None),
    refresh_token: str = Depends(get_refresh_token_from_auth)
):
    """
    Posts to Reddit. Supports flair and tags (NSFW, brand_affiliate).
    Accepts: title, body, link, flair_id, nsfw, brand_affiliate, and image/video files.
    """
    try:
        reddit = get_asyncpraw_reddit_with_refresh(refresh_token)
        sr = await reddit.subreddit(subreddit)
        submission = None

        # --- Handle media submissions ---
        if files and len(files) > 0:
            image_exts = {".jpg", ".jpeg", ".png", ".gif"}
            video_exts = {".mp4", ".mov"}
            temp_files = []
            is_video = False
            for f in files:
                suffix = os.path.splitext(f.filename)[-1].lower()
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                async with aiofiles.open(tmp.name, 'wb') as out_file:
                    content = await f.read()
                    await out_file.write(content)
                temp_files.append(tmp.name)
                if suffix in video_exts:
                    is_video = True

            if is_video:
                video_file = next((tf for tf in temp_files if os.path.splitext(tf)[-1].lower() in video_exts), None)
                if not video_file:
                    raise Exception("No valid video file found")
                submission = await sr.submit_video(
                    title=title,
                    video_path=video_file,
                    thumbnail_path=None,
                    timeout=120,
                    flair_id=flair_id if flair_id else None,
                    nsfw=nsfw,
                    collection_id=None,
                    spoiler=False,
                )
            else:
                if len(temp_files) == 1:
                    submission = await sr.submit_image(
                        title=title,
                        image_path=temp_files[0],
                        flair_id=flair_id if flair_id else None,
                        nsfw=nsfw,
                        spoiler=False,
                    )
                else:
                    images = [{"image_path": p, "caption": ""} for p in temp_files]
                    submission = await sr.submit_gallery(
                        title=title,
                        images=images,
                        flair_id=flair_id if flair_id else None,
                        nsfw=nsfw,
                        spoiler=False,
                    )
            for fpath in temp_files:
                try:
                    os.unlink(fpath)
                except Exception:
                    pass

        # --- Handle link post ---
        elif link and link.strip():
            submission = await sr.submit(
                title=title,
                url=link.strip(),
                flair_id=flair_id if flair_id else None,
                nsfw=nsfw,
                send_replies=False,
            )
        # --- Handle text post ---
        else:
            submission = await sr.submit(
                title=title,
                selftext=body,
                flair_id=flair_id if flair_id else None,
                nsfw=nsfw,
                send_replies=False,
            )

        # Optional brand affiliate tagging best-effort
        if submission and brand_affiliate:
            try:
                await submission.mod.distinguish(sticky=False)
                await submission.mod.set_original_content(True)
            except Exception:
                pass

        await submission.load()  # For .permalink and .url

        return {
            "success": True,
            "url": f"https://www.reddit.com{submission.permalink}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# ----------------------------- Flair options (Script creds) -----------------------------

@reddit_post_app.get("/flair_options")
def flair_options(
    r: str = Query(..., min_length=1, description="Subreddit name (no r/)")
):
    """
    Returns link flair options using Script credentials.
    Mirrors the working flair_labels.py behavior and adds robust fallbacks.
    """
    reddit = get_script_praw_for_flair()

    sub_name = r.strip().lstrip("/").replace("r/", "")
    if not sub_name:
        raise HTTPException(status_code=400, detail="Missing subreddit name")

    try:
        # Sanity touch (optional)
        _ = reddit.user.me()

        sub = reddit.subreddit(sub_name)
        _ = sub.id  # fail fast if 403/404

        templates_obj = sub.flair.link_templates

        # 1) Primary path: user-selectable
        try:
            raw = list(templates_obj.user_selectable())
        except Exception:
            raw = []

        # 2) Fallback: all link templates filtered by user_selectable flag
        if not raw:
            try:
                all_tpls = list(templates_obj)
                raw = [t for t in all_tpls if t.get("user_selectable")]
            except Exception:
                pass

        # DEBUG: print what we actually got from Reddit
        print(f"[flair_options] r/{sub_name}: received {len(raw)} templates")

        # 3) Final mapping to your UI shape
        flairs = []
        for t in raw or []:
            tpl_id = t.get("id") or t.get("flair_template_id")
            if not tpl_id:
                continue
            flairs.append({
                "id": tpl_id,
                "text": (t.get("text") or t.get("flair_text") or ""),
                "richtext": t.get("richtext") or [],
                "text_color": t.get("text_color", ""),
                "background_color": t.get("background_color", ""),
                "editable": bool(t.get("editable", t.get("allow_user_edit", False))),
                "css_class": t.get("css_class", ""),
            })

        return {"flair": flairs}

    except Exception as e:
        msg = str(e).lower()
        if "forbidden" in msg or "403" in msg:
            raise HTTPException(status_code=403, detail=f"Forbidden: r/{sub_name} requires membership (for script user)")
        if "notfound" in msg or "404" in msg:
            raise HTTPException(status_code=404, detail=f"Subreddit r/{sub_name} not found")
        raise HTTPException(status_code=400, detail=f"Could not fetch flair: {e}")

# ----------------------------- Subscriptions (OAuth) -----------------------------

@reddit_post_app.get("/subscriptions")
async def list_subscriptions(
    limit: int = Query(200, ge=1, le=1000, description="Max subreddits to return"),
    refresh_token: str = Depends(get_refresh_token_from_auth),
):
    """
    Return the authenticated user's subscribed subreddits.
    Requires OAuth with the 'mysubreddits' scope and a valid refresh token.

    Response shape:
      {
        "subreddits": [
          {
            "name": "javascript",
            "display_name_prefixed": "r/javascript",
            "title": "JavaScript",
            "icon_img": "...",
            "community_icon": "...",
            "subscribers": 1234567
          },
          ...
        ]
      }
    """
    reddit = get_asyncpraw_reddit_with_refresh(refresh_token)
    try:
        items = []
        # asyncpraw: iterate asynchronously
        async for sr in reddit.user.subreddits(limit=limit):
            # Some communities have a querystring on community_icon; pass it through
            items.append({
                "name": getattr(sr, "display_name", ""),
                "display_name_prefixed": getattr(sr, "display_name_prefixed", f"r/{getattr(sr, 'display_name', '')}"),
                "title": getattr(sr, "title", "") or getattr(sr, "public_description", "") or "",
                "icon_img": getattr(sr, "icon_img", None),
                "community_icon": getattr(sr, "community_icon", None),
                "subscribers": getattr(sr, "subscribers", None),
            })

        # Sort alpha by name for stable UI
        items = [i for i in items if i.get("name")]
        items.sort(key=lambda x: x["name"].lower())

        return {"subreddits": items}

    except (prawcore.exceptions.OAuthException, asyncprawcore.exceptions.OAuthException):
        # Invalid/expired token, or mismatch
        raise HTTPException(status_code=401, detail="OAuth invalid/expired. Please sign in again.")
    except (prawcore.exceptions.Forbidden, asyncprawcore.exceptions.Forbidden):
        # Usually missing 'mysubreddits' scope
        raise HTTPException(status_code=403, detail="Forbidden: ensure 'mysubreddits' scope is granted.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load subscriptions: {e}")
    finally:
        try:
            await reddit.close()
        except Exception:
            pass
