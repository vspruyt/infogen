-- Create table for caching OpenLibrary search results
CREATE TABLE IF NOT EXISTS openlibrary_search_cache (
    id UUID PRIMARY KEY,
    query TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('author', 'book')),
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400,
    UNIQUE(query, media_type)
);

-- Create index on query and media_type for faster lookups
CREATE INDEX IF NOT EXISTS idx_openlibrary_search_cache_query_media_type 
ON openlibrary_search_cache(query, media_type);

-- Create table for caching OpenLibrary author details
CREATE TABLE IF NOT EXISTS openlibrary_author_cache (
    author_key TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create table for caching OpenLibrary author works
CREATE TABLE IF NOT EXISTS openlibrary_author_works_cache (
    author_key TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create table for caching OpenLibrary work details
CREATE TABLE IF NOT EXISTS openlibrary_work_cache (
    work_key TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create table for caching OpenLibrary work editions
CREATE TABLE IF NOT EXISTS openlibrary_editions_cache (
    work_key TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

