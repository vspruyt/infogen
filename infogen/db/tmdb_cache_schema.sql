-- docker run -p 5432:5432 -e POSTGRES_PASSWORD=localtest postgres

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table for caching TMDB API search results
CREATE TABLE IF NOT EXISTS tmdb_search_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query TEXT NOT NULL,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL,
    UNIQUE(query)
);

-- Index on the query column for exact text matching
CREATE INDEX IF NOT EXISTS idx_tmdb_search_cache_query ON tmdb_search_cache(query);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_search_cache_date ON tmdb_search_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_search_cache 
-- WHERE query = $1
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Table for caching TMDB movie details
CREATE TABLE IF NOT EXISTS tmdb_movie_cache (
    tmdb_id INTEGER PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on the tmdb_id column
CREATE INDEX IF NOT EXISTS idx_tmdb_movie_cache_tmdb_id ON tmdb_movie_cache(tmdb_id);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_movie_cache_date ON tmdb_movie_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_movie_cache 
-- WHERE tmdb_id = $1
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Table for caching OMDB movie details
CREATE TABLE IF NOT EXISTS omdb_movie_cache (
    imdb_id TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on the imdb_id column
CREATE INDEX IF NOT EXISTS idx_omdb_movie_cache_imdb_id ON omdb_movie_cache(imdb_id);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_omdb_movie_cache_date ON omdb_movie_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM omdb_movie_cache 
-- WHERE imdb_id = $1
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Table for caching TMDB collection details
CREATE TABLE IF NOT EXISTS tmdb_collection_cache (
    collection_id INTEGER PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on the collection_id column
CREATE INDEX IF NOT EXISTS idx_tmdb_collection_cache_collection_id ON tmdb_collection_cache(collection_id);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_collection_cache_date ON tmdb_collection_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_collection_cache 
-- WHERE collection_id = $1
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Table for caching TMDB TV show details
CREATE TABLE IF NOT EXISTS tmdb_tv_cache (
    tmdb_id INTEGER PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on the tmdb_id column
CREATE INDEX IF NOT EXISTS idx_tmdb_tv_cache_tmdb_id ON tmdb_tv_cache(tmdb_id);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_tv_cache_date ON tmdb_tv_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_tv_cache 
-- WHERE tmdb_id = $1
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Table for caching OMDB TV show details
CREATE TABLE IF NOT EXISTS omdb_tv_cache (
    imdb_id TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on the imdb_id column
CREATE INDEX IF NOT EXISTS idx_omdb_tv_cache_imdb_id ON omdb_tv_cache(imdb_id);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_omdb_tv_cache_date ON omdb_tv_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM omdb_tv_cache 
-- WHERE imdb_id = $1
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Table for caching TMDB TV season details
CREATE TABLE IF NOT EXISTS tmdb_season_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tmdb_id INTEGER NOT NULL,
    season_number INTEGER NOT NULL,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL,
    UNIQUE(tmdb_id, season_number)
);

-- Index on the combined tmdb_id and season_number
CREATE INDEX IF NOT EXISTS idx_tmdb_season_cache_id_number ON tmdb_season_cache(tmdb_id, season_number);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_season_cache_date ON tmdb_season_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_season_cache 
-- WHERE tmdb_id = $1 AND season_number = $2
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Table for caching TMDB people details
CREATE TABLE IF NOT EXISTS tmdb_people_cache (
    tmdb_id INTEGER PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on the tmdb_id column
CREATE INDEX IF NOT EXISTS idx_tmdb_people_cache_tmdb_id ON tmdb_people_cache(tmdb_id);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_people_cache_date ON tmdb_people_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_people_cache 
-- WHERE tmdb_id = $1
--   AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute'); 

-- Tables for caching TMDB popular lists
CREATE TABLE IF NOT EXISTS tmdb_popular_movies_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_popular_movies_cache_date ON tmdb_popular_movies_cache(creation_date, expires_after_minutes);

CREATE TABLE IF NOT EXISTS tmdb_popular_tv_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_popular_tv_cache_date ON tmdb_popular_tv_cache(creation_date, expires_after_minutes);

CREATE TABLE IF NOT EXISTS tmdb_popular_people_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_popular_people_cache_date ON tmdb_popular_people_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_popular_{media_type}_cache 
-- WHERE CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
-- ORDER BY creation_date DESC
-- LIMIT 1; 

-- Tables for caching TMDB top rated lists
CREATE TABLE IF NOT EXISTS tmdb_top_rated_movies_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_top_rated_movies_cache_date ON tmdb_top_rated_movies_cache(creation_date, expires_after_minutes);

CREATE TABLE IF NOT EXISTS tmdb_top_rated_tv_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL
);

-- Index on creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_tmdb_top_rated_tv_cache_date ON tmdb_top_rated_tv_cache(creation_date, expires_after_minutes);

-- Comment explaining typical usage:
-- Example query:
-- SELECT api_response 
-- FROM tmdb_top_rated_{media_type}_cache 
-- WHERE CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
-- ORDER BY creation_date DESC
-- LIMIT 1; 

