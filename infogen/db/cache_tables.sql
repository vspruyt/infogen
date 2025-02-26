-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Create content_cache table first since it will be referenced by url_cache
CREATE TABLE IF NOT EXISTS content_cache (
    url TEXT PRIMARY KEY,    
    raw_content TEXT NOT NULL,
    expires_after_days INTEGER NOT NULL DEFAULT 30,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create url_cache table with foreign key reference
CREATE TABLE IF NOT EXISTS url_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query TEXT NOT NULL,
    enhanced_query TEXT NOT NULL,
    enhanced_query_embedding VECTOR(1536) NOT NULL,
    url TEXT NOT NULL,
    expires_after_days INTEGER NOT NULL DEFAULT 30,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create query_log table
CREATE TABLE IF NOT EXISTS query_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query TEXT NOT NULL,
    enhanced_query TEXT NOT NULL UNIQUE,
    enhanced_query_embedding VECTOR(1536) NOT NULL,
    counter INTEGER NOT NULL
);


-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_url_cache_query ON url_cache(query);
CREATE INDEX IF NOT EXISTS idx_content_cache_query ON content_cache(query);
CREATE INDEX IF NOT EXISTS idx_url_cache_enhanced_query ON url_cache(enhanced_query);
CREATE INDEX IF NOT EXISTS idx_content_cache_enhanced_query ON content_cache(enhanced_query); 
CREATE INDEX IF NOT EXISTS idx_url_cache_enhanced_query_embedding ON url_cache USING hnsw (enhanced_query_embedding vector_cosine_ops);

-- Create indexes for query_log table
CREATE INDEX IF NOT EXISTS idx_query_log_query ON query_log(query);
CREATE INDEX IF NOT EXISTS idx_query_log_enhanced_query ON query_log(enhanced_query);
CREATE INDEX IF NOT EXISTS idx_query_log_enhanced_query_embedding ON query_log USING hnsw (enhanced_query_embedding vector_cosine_ops);