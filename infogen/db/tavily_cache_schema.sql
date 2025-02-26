-- Enable the vector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Table for caching basic Tavily search results
CREATE TABLE IF NOT EXISTS tavily_basic_search_cache (
    id UUID PRIMARY KEY,
    query TEXT NOT NULL UNIQUE,
    api_response JSONB NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index for faster query lookups
CREATE INDEX IF NOT EXISTS tavily_basic_search_cache_query_idx ON tavily_basic_search_cache(query);

-- Index for faster expiry checks
CREATE INDEX IF NOT EXISTS tavily_basic_search_cache_expiry_idx 
    ON tavily_basic_search_cache(creation_date, expires_after_minutes);

-- Index for similarity search
CREATE INDEX IF NOT EXISTS tavily_basic_search_cache_embedding_idx ON tavily_basic_search_cache 
USING hnsw (embedding vector_cosine_ops);

-- Table for caching advanced Tavily search results
CREATE TABLE IF NOT EXISTS tavily_search_cache (
    id UUID PRIMARY KEY,
    query TEXT NOT NULL,
    search_depth TEXT NOT NULL,
    max_results INTEGER NOT NULL,
    include_raw_content BOOLEAN NOT NULL DEFAULT false,
    time_range TEXT,
    exclude_domains JSONB,
    api_response JSONB NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL,
    UNIQUE(query, search_depth, time_range)
);

-- Index for faster query lookups
CREATE INDEX IF NOT EXISTS tavily_search_cache_query_idx ON tavily_search_cache(query);

-- Index for faster expiry checks
CREATE INDEX IF NOT EXISTS tavily_search_cache_expiry_idx 
    ON tavily_search_cache(creation_date, expires_after_minutes);

-- Index for similarity search
CREATE INDEX IF NOT EXISTS tavily_search_cache_embedding_idx ON tavily_search_cache 
USING hnsw (embedding vector_cosine_ops); 