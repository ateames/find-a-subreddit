from dotenv import load_dotenv
load_dotenv()
import os
import praw
import time
import chromadb
import openai

# Configs from .env file
REDDIT_CLIENT_ID = os.getenv("REDDIT_SCRIPT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_SCRIPT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "chromadb_subreddits")
TOP_N = int(os.getenv("TOP_N", "1000"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ChromaDB connection settings 
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT and OPENAI_API_KEY):
    raise RuntimeError("Missing required config in .env file.")

# Initialize OpenAI client (for openai>=1.0.0)
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Initialize Reddit API
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

# CONNECT TO CHROMADB SERVER (NOT local file)
chromadb_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection = chromadb_client.get_or_create_collection("subreddits")

def get_embedding(text):
    """Get an embedding from OpenAI for the given text."""
    response = openai_client.embeddings.create(
        input=[text],
        model="text-embedding-ada-002"
    )
    return response.data[0].embedding

def main():
    count = 0

    for sub in reddit.subreddits.popular(limit=TOP_N):
        # Exclude NSFW, quarantined, private
        if sub.over18 or sub.quarantine or sub.subreddit_type not in ["public", "restricted"]:
            continue

        # Gather info, handling None cases
        sub_data = {
            "display_name": sub.display_name,
            "rules": [],
            "submit_text": sub.submit_text or "",
            "public_description": sub.public_description or "",
            "subscribers": sub.subscribers,
            "community_icon": sub.community_icon or "",
        }

        try:
            sub_data["rules"] = []
            for rule in getattr(sub, "rules", []):
                desc = getattr(rule, "description", None)
                if desc is not None:
                    sub_data["rules"].append(desc)
                elif isinstance(rule, str):
                    sub_data["rules"].append(rule)
        except Exception as e:
            print(f"Error fetching rules for {sub_data['display_name']}: {e}", flush=True)
            continue

        composite_text = (
            f"Subreddit: {sub_data['display_name']}\n"
            f"Description: {sub_data['public_description']}\n"
            f"Submit Rules: {sub_data['submit_text']}\n"
            f"Rules: {' | '.join(sub_data['rules'])}"
        )

        # Get embedding
        try:
            embedding = get_embedding(composite_text)
        except Exception as e:
            print(f"Error generating embedding for {sub_data['display_name']}: {e}", flush=True)
            continue  # Skip storing if embedding fails

        # Store in ChromaDB only if embedding succeeded
        try:
            collection.add(
                embeddings=[embedding],
                documents=[composite_text],
                metadatas=[{
                    "display_name": sub_data["display_name"],
                    "public_description": sub_data["public_description"],
                    "submit_text": sub_data["submit_text"],
                    "rules": " | ".join(sub_data["rules"]),  # Store as single string
                    "subscribers": sub_data["subscribers"],
                    "community_icon": sub_data["community_icon"],
                }],
                ids=[sub_data["display_name"]],
            )
            count += 1
            print(f"[{count}] Stored: {sub_data['display_name']}", flush=True)
        except Exception as e:
            print(f"Error storing {sub_data['display_name']}: {e}", flush=True)

        time.sleep(1.5)  # Throttle to avoid rate limiting

    print(f"Finished! Successfully stored {count} subreddits.")

if __name__ == "__main__":
    main()
