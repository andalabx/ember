# Contributing to ember

Thanks for your interest. ember is an open source project and contributions are welcome.

## Getting started

```bash
git clone https://github.com/andalabx/ember
cd ember
pip install -e ".[dev]"
pytest tests/
```

## What we look for

- Bug fixes for scraping, crawling, searching, or browser interaction
- Better extraction quality for specific site types
- Performance improvements that reduce memory or increase speed
- Documentation improvements

## What we probably will not accept

- New features that add significant dependencies
- Changes that increase idle memory or startup time
- Pull requests that break existing tests

## Before submitting

1. Run `pytest tests/` and make sure everything passes
2. Make sure your changes do not add new dependencies unless absolutely necessary
3. Keep functions small and focused. ember is built on the principle that less code is better code
4. Use type hints and docstrings

## Questions

Open an issue on GitHub.
