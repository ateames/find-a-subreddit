# AI Reddit Post Analyzer

This project is an AI-powered Reddit post analyzer that helps users identify the best subreddits for their posts. It uses OpenAI for natural language processing, ChromaDB for data storage, and a FastAPI backend to serve the analysis. The frontend is built with React and TailwindCSS.

---

## Features

- Analyze Reddit post titles and bodies to find the most relevant subreddits.
- Analyze uploaded images to determine image information to find the most relevant subreddits.
- Display subreddit rules and potential AI-generated content warnings.
- Backend powered by FastAPI, Postgres with pgvector to store embeddings 
- Frontend built with React and TailwindCSS.
- PRAW (Python Reddit API Wrapper) to fetch subreddit rules and metadata. 

---

## Prerequisites

Before starting, ensure you have the following installed:

- Docker 
- Python 3.8+
- Node.js 16+
- npm or yarn
- A `.env` file with the required API keys (see `sample.env` for reference).

---

## Running the Project

### 1 Use Docker to create the database and ingest subreddits 
Build images (only needed after changing Dockerfile/requirements)
```
docker compose build
```

Start Postgres (pgvector) in the background
```
docker compose up -d
```
Run the ingestion (one-off job)
```
docker compose run --rm ingest
```

#### Stop Docker services
Stop containers but keep data:
```
docker compose stop
```

Stop and remove containers (keep the database volume):
```
docker compose down
```

Nuke everything (containers + data volume):
```
docker compose down -v
```

---

## Project Structure

```
ai_reddit_prototype/
├── .env                     # Environment variables
├── package.json             # Node.js dependencies
├── scripts/                 # Scripts for managing subreddit data
│   └── ingest_reddit_to_postgres.py # Script to fetch subreddit data, analyze using OpenAI and store in Postgres
├── src/                     # Source code
│   ├── api/                 # FastAPI backend
│   │   ├── analyze_post_api.py # API for analyzing Reddit posts
│   │   ├── reddit_post_api.py  # API for Reddit post interactions
│   │   └── auth/            # Reddit auth services - To-Do: Add files for Reddit Auth
│   │       └── reddit_auth.py  # User authentication for OAuth sign-in  
│   ├── components/          # React components
│   │   └─ ui/               # Front-end Reach components 
│   │      ├── accordion.tsx # Expands card sections
│   │      ├── button.tsx    # Card buttons 
│   │      ├── card.tsx      # Card info and layout 
│   │      ├── input.tsx     # Accept input on cards 
│   │      └── textarea.tsx  # Display text on cards 
│   ├── lib/                 # Utility functions
│   ├── styles/              # TailwindCSS styles
│   ├── App.tsx              # Main React app
│   ├── RedditAnalyzer.tsx   # Reddit post analyzer component
│   └── main.tsx             # Application entry point
├── tailwind.config.js       # TailwindCSS configuration
├── tsconfig.json            # TypeScript configuration
├── vite.config.ts           # Vite configuration
├── index.css                # Global CSS styles
└── index.html 
```

---

## Scripts

### Fetch Subreddits to Postgres
This script defaults to fetch the top 1000 subreddits or, you can use the `TOP_N` environment variable to override. 
Run the script to fetch subreddit data and store it in Postgres.
```bash
python scripts/ingest_reddit_to_postgres.py
```

---

## License

This project is licensed under the MIT License.