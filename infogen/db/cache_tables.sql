-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Create content_cache table first since it will be referenced by url_cache
CREATE TABLE IF NOT EXISTS content_cache (
    url TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    enhanced_query TEXT,
    raw_content TEXT NOT NULL,
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
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_url_cache_query ON url_cache(query);
CREATE INDEX IF NOT EXISTS idx_content_cache_query ON content_cache(query);
CREATE INDEX IF NOT EXISTS idx_url_cache_enhanced_query ON url_cache(enhanced_query);
CREATE INDEX IF NOT EXISTS idx_content_cache_enhanced_query ON content_cache(enhanced_query); 