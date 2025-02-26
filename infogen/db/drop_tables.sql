-- Drop all cache tables

-- Drop MusicBrainz cache tables
DROP TABLE IF EXISTS musicbrainz_song_cache;
DROP TABLE IF EXISTS musicbrainz_release_cache;
DROP TABLE IF EXISTS musicbrainz_album_cache;
DROP TABLE IF EXISTS musicbrainz_artist_cache;
DROP TABLE IF EXISTS lastfm_artist_bio_cache;
DROP TABLE IF EXISTS musicbrainz_search_cache;

-- Drop TMDB and OMDB cache tables
DROP TABLE IF EXISTS tmdb_top_rated_tv_cache;
DROP TABLE IF EXISTS tmdb_top_rated_movies_cache;
DROP TABLE IF EXISTS tmdb_popular_people_cache;
DROP TABLE IF EXISTS tmdb_popular_tv_cache;
DROP TABLE IF EXISTS tmdb_popular_movies_cache;
DROP TABLE IF EXISTS tmdb_people_cache;
DROP TABLE IF EXISTS tmdb_season_cache;
DROP TABLE IF EXISTS omdb_tv_cache;
DROP TABLE IF EXISTS tmdb_tv_cache;
DROP TABLE IF EXISTS tmdb_collection_cache;
DROP TABLE IF EXISTS omdb_movie_cache;
DROP TABLE IF EXISTS tmdb_movie_cache;
DROP TABLE IF EXISTS tmdb_search_cache;

-- Drop OpenLibrary cache tables
DROP TABLE IF EXISTS openlibrary_search_cache;
DROP TABLE IF EXISTS openlibrary_author_cache;
DROP TABLE IF EXISTS openlibrary_author_works_cache;
DROP TABLE IF EXISTS openlibrary_work_cache;
DROP TABLE IF EXISTS openlibrary_editions_cache;

-- Drop Tavily cache tables
DROP TABLE IF EXISTS tavily_basic_search_cache;
DROP TABLE IF EXISTS content_cache;
DROP TABLE IF EXISTS url_cache;
DROP TABLE IF EXISTS query_log; 