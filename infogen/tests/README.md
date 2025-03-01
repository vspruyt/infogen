# Infogen Tests

This directory contains unit tests for the Infogen project. The tests are designed to ensure that the code works as expected and to prevent regressions.

## Test Structure

The tests are organized by module:

- `test_utilities.py`: Tests for the utilities module
- `test_url_validator_client.py`: Tests for the URL validator client
- `test_chromium_client.py`: Tests for the Chromium client
- `test_cached_embedding_client.py`: Tests for the cached embedding client
- `test_cached_tavily_client.py`: Tests for the cached Tavily client
- `test_cached_url_validator_client.py`: Tests for the cached URL validator client
- `test_cached_tmdb_client.py`: Tests for the cached TMDB client
- `test_cached_musicbrainz_client.py`: Tests for the cached MusicBrainz client
- `test_cached_openlibrary_client.py`: Tests for the cached OpenLibrary client

## Running Tests

### Running All Tests

To run all tests, use the `run_tests.py` script:

```bash
python -m infogen.tests.run_tests
```

For more verbose output, add the `-v` flag:

```bash
python -m infogen.tests.run_tests -v
```

### Running Specific Tests

To run specific test modules, specify them as arguments:

```bash
python -m infogen.tests.run_tests test_utilities test_url_validator_client
```

### Using unittest Directly

You can also use the `unittest` module directly:

```bash
# Run all tests
python -m unittest discover -s infogen/tests

# Run a specific test module
python -m unittest infogen.tests.test_utilities

# Run a specific test case
python -m unittest infogen.tests.test_utilities.TestUtilities

# Run a specific test method
python -m unittest infogen.tests.test_utilities.TestUtilities.test_truncate_text_tokens_input_validation
```

## Real URL Tests

Some tests for the URL validator client include tests with real URLs. These tests are commented out by default to avoid making network requests during automated testing. To run these tests, uncomment the relevant section in `test_url_validator_client.py` and run the tests manually.

## Adding New Tests

When adding new functionality or fixing bugs, please add corresponding tests to ensure the code works as expected and to prevent regressions. Follow these guidelines:

1. Create a new test file if testing a new module, or add tests to an existing file if appropriate.
2. Use descriptive test method names that clearly indicate what is being tested.
3. Include docstrings for test classes and methods.
4. Use mocks and patches to avoid external dependencies when possible.
5. Test both success and failure cases.
6. Test edge cases and boundary conditions.

## Test Dependencies

The tests use the following libraries:

- `unittest`: The standard Python testing framework
- `unittest.mock`: For mocking objects and functions
- `pytest`: For additional testing features (optional)

Make sure these dependencies are installed before running the tests. 