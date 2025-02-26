-- Enable the vector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Table for caching embeddings
CREATE TABLE IF NOT EXISTS embedding_cache (
    id UUID PRIMARY KEY,
    text TEXT NOT NULL UNIQUE,
    embedding VECTOR(1536) NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster text lookups
CREATE INDEX IF NOT EXISTS embedding_cache_text_idx ON embedding_cache(text);

-- Index for similarity search
CREATE INDEX IF NOT EXISTS embedding_cache_embedding_idx ON embedding_cache 
USING hnsw (embedding vector_cosine_ops); 