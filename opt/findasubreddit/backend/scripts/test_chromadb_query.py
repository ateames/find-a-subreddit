from dotenv import load_dotenv
load_dotenv()
import os
import chromadb
import openai

# Load configs from .env if present
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing from .env or environment.")

# Connect to ChromaDB server
chromadb_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection_name = "subreddits"

# Ensure collection exists
collections = [c.name for c in chromadb_client.list_collections()]
if collection_name not in collections:
    raise RuntimeError(f"Collection '{collection_name}' does not exist. "
                       f"Make sure you've run the fetch script successfully.")

collection = chromadb_client.get_collection(collection_name)

# Initialize OpenAI client
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Example user query (simulate a Reddit post)
user_query = "Looking for a place to ask a stupid question about life"

# Get the embedding for your test query
response = openai_client.embeddings.create(
    input=[user_query],
    model="text-embedding-ada-002"
)
embedding = response.data[0].embedding

# Query ChromaDB for the top 3 similar subreddits
results = collection.query(
    query_embeddings=[embedding],
    n_results=20,
    include=["metadatas", "documents"]
)

print("Top subreddit matches for your query:")
for i, doc in enumerate(results["documents"][0]):
    meta = results["metadatas"][0][i]
    print(f"\n{i+1}. {meta['display_name']}")
    print(f"   Description: {meta['public_description']}")
    print(f"   Subscribers: {meta['subscribers']}")
    print(f"   Rules: {meta['rules']}")
    print(f"   Community Icon: {meta['community_icon']}")
