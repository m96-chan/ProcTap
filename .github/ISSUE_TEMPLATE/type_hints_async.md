---
name: 🔧 Type Hints / Async Extension
about: Suggest improvements to type hints or async functionality
title: "[Types/Async]: "
labels: enhancement, types, async
assignees: ''
---

## Improvement Category

<!-- What type of improvement are you suggesting? -->
<!-- Options: Type Hints (missing or incorrect), Type Stubs (.pyi files), Generic Types/TypeVar, Async API Enhancement, Async/Await Pattern Improvement, Protocol/ABC Design, Type Checking with mypy, Other -->

- **Category**:

## Description

<!-- Describe the type hint or async improvement you're proposing -->
<!-- The `ProcessAudioTap.read()` method is missing return type annotations... -->

## Current Code

<!-- Show the current code that needs improvement -->

```python
# Current implementation
def read(self, timeout=1.0):
    return self._backend.read()
```

## Proposed Improvement

<!-- Show what the improved code should look like -->

```python
# Proposed improvement
def read(self, timeout: float = 1.0) -> Optional[bytes]:
    """Read one audio chunk (blocking).

    Args:
        timeout: Maximum time to wait in seconds

    Returns:
        PCM audio data, or None if timeout
    """
    return self._backend.read()
```

## mypy Errors (If Applicable)

<!-- If this addresses mypy errors, paste them here -->

```
error: Missing return type annotation for function "read"
error: Incompatible return value type (got "bytes", expected "None")
```

## Async-Specific Focus (If Applicable)

<!-- If this is async-related, what aspect? -->
<!-- Options: Not async-related, AsyncIterator/AsyncGenerator, Context Manager (async with), Cancellation/Cleanup, Backpressure Handling, Error Handling in Async, Type Hints for Async, Other -->

- **Focus**:

## Use Case / Motivation

<!-- Why is this improvement needed? -->

This would help because:
- Better IDE autocomplete
- Catch errors at type-checking time
- Clearer API documentation

## Compatibility Considerations

<!-- Check all that apply -->

- [ ] This change is backward compatible
- [ ] This requires a breaking API change
- [ ] This affects only type annotations (runtime unchanged)
- [ ] This requires Python 3.11+ features

## References / Examples

<!-- Link to similar implementations or typing patterns in other libraries -->

Similar patterns in:
- https://github.com/...
- PEP 484, 526, 544, etc.

## Implementation Willingness

<!-- Can you help implement this? (check all that apply) -->

- [ ] I can submit a PR with type hints
- [ ] I can update .pyi stub files
- [ ] I can add mypy configuration
- [ ] I can write tests for type checking

## Additional Context

<!-- Any other relevant information -->
<!-- Additional details, related issues, etc. -->
