# Python Best Practices Review

Review the code I'm working on and ensure it follows these Python best practices:

## Code Quality
- All functions have type hints (params and return types)
- Use `from __future__ import annotations` for modern annotation syntax
- Pydantic models validate data at boundaries (API responses, user input, config)
- No mutable default arguments (use `Field(default_factory=...)`)
- Context managers for resource cleanup (`async with`, `with`)
- Prefer composition over inheritance

## Async Patterns
- Never call blocking I/O in an async function without `asyncio.to_thread()`
- Use `asyncio.gather()` for concurrent independent operations
- Always handle cancellation gracefully
- Use `async with` for connections and sessions

## Error Handling
- Custom exception hierarchy (all inherit from base project error)
- Never catch bare `Exception` unless re-raising
- Log with context before raising
- Use specific exception types for specific failure modes
- Early returns over deeply nested try/except

## Performance
- Use generators/async generators for large data streams
- Cache expensive computations (`@lru_cache`, `@cached_property`)
- Avoid unnecessary copies of large data structures
- Profile before optimizing — don't guess at bottlenecks

## Security
- Never log sensitive data (API keys, passwords, account numbers)
- Validate/sanitize all external input
- Use parameterized queries (SQLAlchemy handles this)
- Pin dependencies to avoid supply chain attacks
- Never commit `.env` files

## Testing
- Every public function/method should be testable
- Mock external dependencies (IB, HTTP, filesystem)
- Test edge cases: empty inputs, None values, boundary conditions
- Use fixtures for shared test setup
- Separate unit tests (fast, mocked) from integration tests (slow, real services)

Review the current changes and flag any violations of these practices. Suggest fixes with code examples.
