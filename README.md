# infogen

Folder structure of the repo:

infogen/
├── infogen/                # Python package/pplication code
│   ├── __init__.py         # Makes `app` a package
│   ├── main.py             # Entry point for FastAPI
│   ├── api/                # API routes
│   │   ├── __init__.py     
│   │   ├── v1/             # Versioned routes
│   │   │   ├── __init__.py
│   │   │   ├── users.py    # Example: user-related routes
│   │   │   ├── items.py    # Example: item-related routes
│   ├── core/               # Core app configuration
│   │   ├── __init__.py
│   │   ├── config.py       # Settings (e.g., env variables)
│   │   ├── security.py     # Security utilities (e.g., auth)
│   ├── db/                 # Database logic
│   │   ├── __init__.py
│   │   ├── models.py       # ORM models (e.g., Pydantic or SQLAlchemy)
│   │   ├── session.py      # Database session setup
│   ├── schemas/            # Pydantic models for request/response validation
│   │   ├── __init__.py
│   ├── services/           # Business logic
│   │   ├── __init__.py
│   ├── tests/              # Unit and integration tests
│       ├── __init__.py
│       ├── test_main.py    # test cases
├── .dockerignore           # Exclude files from Docker builds
├── .gitignore              # Ignore unnecessary files for Git
├── Dockerfile              # Dockerfile for building the container
├── docker-compose.yml      # Docker Compose for local dev (optional)
├── requirements.txt        # Python dependencies
├── README.md               # Project documentation

