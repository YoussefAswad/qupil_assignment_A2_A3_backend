# Backend for the project

## Requirements
- Python 3.11+
- [poetry](https://python-poetry.org/)

## Installation
```bash
pip install poetry
```
In the project directory, run:
```bash
poetry install
```

## Running the server
```bash
uvicorn --reload schedule.main:app
```

or 

```bash
poetry shell
run
```

## OpenAPI documentation
The OpenAPI documentation is available at `/docs` endpoint.

## Available endpoints
- `/schedule` - GET, POST
- `/users` - GET, POST
- `/users/me` - GET
- `/generate` - GET
- `/token` - POST
- `/token/validate` - POST
- `/token/validate/refresh` - POST

