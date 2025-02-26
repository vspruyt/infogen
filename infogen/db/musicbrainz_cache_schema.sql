-- Create extension if not exists
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table for caching search results
CREATE TABLE IF NOT EXISTS musicbrainz_search_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('artist', 'album', 'song')),
    artist_name TEXT,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400,
    UNIQUE (query, media_type, artist_name)
);

-- Create index on search cache for faster lookups
CREATE INDEX IF NOT EXISTS idx_musicbrainz_search_cache_query 
ON musicbrainz_search_cache (query, media_type, artist_name);

-- Create index on search cache creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_musicbrainz_search_cache_date 
ON musicbrainz_search_cache (creation_date, expires_after_minutes);

-- Table for caching artist bios from LastFM
CREATE TABLE IF NOT EXISTS lastfm_artist_bio_cache (
    mbid TEXT PRIMARY KEY,
    bio TEXT,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create index on artist bio cache for faster lookups
CREATE INDEX IF NOT EXISTS idx_lastfm_artist_bio_cache_expiry 
ON lastfm_artist_bio_cache (mbid);

-- Create index on artist bio cache creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_lastfm_artist_bio_cache_date 
ON lastfm_artist_bio_cache (creation_date, expires_after_minutes);

-- Table for caching artist details
CREATE TABLE IF NOT EXISTS musicbrainz_artist_cache (
    mbid TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create index on artist cache for faster lookups
CREATE INDEX IF NOT EXISTS idx_musicbrainz_artist_cache_expiry 
ON musicbrainz_artist_cache (mbid);

-- Create index on artist cache creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_musicbrainz_artist_cache_date 
ON musicbrainz_artist_cache (creation_date, expires_after_minutes);

-- Table for caching album details
CREATE TABLE IF NOT EXISTS musicbrainz_album_cache (
    mbid TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create index on album cache for faster lookups
CREATE INDEX IF NOT EXISTS idx_musicbrainz_album_cache_expiry 
ON musicbrainz_album_cache (mbid);

-- Create index on album cache creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_musicbrainz_album_cache_date 
ON musicbrainz_album_cache (creation_date, expires_after_minutes);

-- Table for caching release details
CREATE TABLE IF NOT EXISTS musicbrainz_release_cache (
    mbid TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create index on release cache for faster lookups
CREATE INDEX IF NOT EXISTS idx_musicbrainz_release_cache_expiry 
ON musicbrainz_release_cache (mbid);

-- Create index on release cache creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_musicbrainz_release_cache_date 
ON musicbrainz_release_cache (creation_date, expires_after_minutes);

-- Table for caching song details
CREATE TABLE IF NOT EXISTS musicbrainz_song_cache (
    mbid TEXT PRIMARY KEY,
    api_response JSONB NOT NULL,
    creation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_after_minutes INTEGER NOT NULL DEFAULT 14400
);

-- Create index on song cache for faster lookups
CREATE INDEX IF NOT EXISTS idx_musicbrainz_song_cache_expiry 
ON musicbrainz_song_cache (mbid);

-- Create index on song cache creation date for cleanup
CREATE INDEX IF NOT EXISTS idx_musicbrainz_song_cache_date 
ON musicbrainz_song_cache (creation_date, expires_after_minutes);

-- Add comments to tables
COMMENT ON TABLE musicbrainz_search_cache IS 'Cache for MusicBrainz search results across all media types';
COMMENT ON TABLE lastfm_artist_bio_cache IS 'Cache for LastFM artist biographies';
COMMENT ON TABLE musicbrainz_artist_cache IS 'Cache for detailed MusicBrainz artist information';
COMMENT ON TABLE musicbrainz_album_cache IS 'Cache for detailed MusicBrainz album information';
COMMENT ON TABLE musicbrainz_release_cache IS 'Cache for detailed MusicBrainz release information';
COMMENT ON TABLE musicbrainz_song_cache IS 'Cache for detailed MusicBrainz song information';

