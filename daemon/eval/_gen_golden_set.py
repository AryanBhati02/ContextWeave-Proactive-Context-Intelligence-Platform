"""Generate eval/golden_set.json with pre-computed chunk IDs.

Run from daemon/ directory:
    python eval/_gen_golden_set.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def cid(file_path: str, chunk_name: str) -> str:
    """Same formula as contextweave.db.chunk_id."""
    return hashlib.sha256(f"{file_path}:{chunk_name}".encode()).hexdigest()[:16]



_ENTRIES: list[tuple[str, str, str, str]] = [
    
    ("fastapi/security/oauth2.py",    "OAuth2PasswordBearer.__call__",        "method",   "How does OAuth2 password bearer token extraction work from request headers?"),
    ("fastapi/routing.py",            "APIRouter.add_api_route",              "method",   "How do I register a new API route with custom methods and response models?"),
    ("fastapi/dependencies/utils.py", "solve_dependencies",                   "function", "How does FastAPI resolve nested dependency injection at request time?"),
    ("fastapi/middleware/cors.py",    "CORSMiddleware.__call__",              "method",   "How does CORS preflight request handling work in FastAPI middleware?"),
    ("fastapi/encoders.py",           "jsonable_encoder",                     "function", "How does FastAPI encode Pydantic models and custom types to JSON?"),
    ("fastapi/exception_handlers.py", "http_exception_handler",               "function", "How does FastAPI handle HTTP exceptions and return error responses?"),
    ("fastapi/background.py",         "BackgroundTasks.add_task",             "method",   "How do I add a background task to run after the response is sent?"),
    ("fastapi/routing.py",            "APIRoute.get_route_handler",           "method",   "How does FastAPI construct the request handler function for a route?"),
    ("fastapi/openapi/utils.py",      "get_openapi",                          "function", "How is the OpenAPI schema generated from route definitions?"),
    ("fastapi/params.py",             "Depends.__init__",                     "method",   "How does the Depends class work for dependency injection declaration?"),
    ("fastapi/security/http.py",      "HTTPBearer.__call__",                  "method",   "How does HTTP Bearer authentication extract credentials from requests?"),
    ("fastapi/security/api_key.py",   "APIKeyHeader.__call__",                "method",   "How does API key authentication via header work in FastAPI?"),
    ("fastapi/responses.py",          "StreamingResponse.__init__",           "method",   "How do I create a streaming response for large file downloads?"),
    ("fastapi/testclient.py",         "TestClient.request",                   "method",   "How does the FastAPI test client send requests without a running server?"),
    ("fastapi/applications.py",       "FastAPI.include_router",               "method",   "How do I mount a sub-router with a prefix and tags in FastAPI?"),
    ("fastapi/routing.py",            "APIRouter.include_router",             "method",   "How does nested router inclusion work with prefix stacking?"),
    ("fastapi/dependencies/utils.py", "request_params_to_args",               "function", "How does FastAPI extract and validate query parameters from a request?"),
    ("fastapi/openapi/docs.py",       "get_swagger_ui_html",                  "function", "How is the Swagger UI HTML page generated for API documentation?"),
    ("fastapi/middleware/trustedhost.py", "TrustedHostMiddleware.__call__",   "method",   "How does trusted host middleware validate the Host header on requests?"),
    ("fastapi/security/oauth2.py",    "OAuth2AuthorizationCodeBearer.__call__", "method","How does OAuth2 authorization code flow token validation work?"),
    ("fastapi/routing.py",            "APIRoute.__init__",                    "method",   "How are response_model and status_code configured on a route definition?"),
    ("fastapi/applications.py",       "FastAPI.__init__",                     "method",   "What parameters does the FastAPI application constructor accept?"),
    ("fastapi/concurrency.py",        "run_in_threadpool",                    "function", "How does FastAPI run synchronous functions in a thread pool executor?"),
    ("fastapi/security/http.py",      "HTTPBasic.__call__",                   "method",   "How does HTTP Basic authentication validate username and password credentials?"),
    ("fastapi/datastructures.py",     "UploadFile.read",                      "method",   "How do I read the contents of an uploaded file asynchronously in FastAPI?"),
    ("fastapi/responses.py",          "FileResponse.__init__",                "method",   "How does FileResponse serve static files with proper MIME type headers?"),
    ("fastapi/middleware/gzip.py",    "GZipMiddleware.__call__",              "method",   "How does GZip response compression middleware work in FastAPI?"),
    ("fastapi/routing.py",            "APIRouter.on_event",                   "method",   "How do I register startup and shutdown event handlers on a sub-router?"),
    ("fastapi/exception_handlers.py", "request_validation_exception_handler", "function","How are Pydantic validation errors formatted into error response bodies?"),
    ("fastapi/openapi/utils.py",      "get_flat_models_from_routes",          "function", "How does FastAPI collect all Pydantic models used across routes for OpenAPI?"),
    
    ("fastapi/security/oauth2.py",    "OAuth2",                               "class",    "How is the base OAuth2 security scheme class structured and what does it define?"),
    ("fastapi/routing.py",            "APIRouter",                            "class",    "What methods does APIRouter expose for organizing endpoints into groups?"),
    ("fastapi/applications.py",       "FastAPI",                              "class",    "How is the main FastAPI application class structured and what does it inherit from?"),
    ("fastapi/dependencies/utils.py", "get_dependant",                        "function", "How does FastAPI build the dependency graph for a path operation function?"),
    ("fastapi/routing.py",            "run_endpoint_function",                "function", "How does FastAPI call the endpoint function handling both sync and async cases?"),
    ("fastapi/security/oauth2.py",    "OAuth2PasswordRequestForm",            "class",    "How does OAuth2PasswordRequestForm parse username and password from form data?"),
    ("fastapi/datastructures.py",     "UploadFile",                           "class",    "How does UploadFile wrap file objects and expose async read and seek methods?"),
    ("fastapi/routing.py",            "APIRoute.handle",                      "method",   "How does an API route handle an incoming HTTP request end to end?"),
    ("fastapi/dependencies/utils.py", "solve_generator_dependency",           "function", "How does FastAPI manage generator-based dependencies with context managers?"),
    ("fastapi/openapi/utils.py",      "get_openapi_operation_metadata",       "function", "How are operation id and summary generated from the endpoint function name?"),
    ("fastapi/middleware/cors.py",    "CORSMiddleware.__init__",              "method",   "How do I configure allowed origins methods and headers for CORS middleware?"),
    ("fastapi/params.py",             "Body.__init__",                        "method",   "How does the Body parameter declaration work for JSON request body validation?"),
    ("fastapi/security/http.py",      "HTTPAuthorizationCredentials",         "class",    "What fields does the HTTP authorization credentials model expose after parsing?"),
    ("fastapi/routing.py",            "generate_operation_id",                "function", "How are unique operation IDs generated to avoid collisions in the OpenAPI schema?"),
    ("fastapi/dependencies/utils.py", "is_coroutine_callable",                "function", "How does FastAPI detect whether a dependency or endpoint is a coroutine function?"),
    
    ("fastapi/params.py",             "Query",                                "class",    "How does the Query class declare query parameter metadata including default and alias?"),
    ("fastapi/params.py",             "Path",                                 "class",    "How does the Path class enforce required path parameters with validation constraints?"),
    ("fastapi/responses.py",          "JSONResponse",                         "class",    "How does JSONResponse serialize content and set the content-type header?"),
    ("fastapi/exceptions.py",         "HTTPException",                        "class",    "What fields does HTTPException expose and how is it raised in endpoint functions?"),
    ("fastapi/background.py",         "BackgroundTasks",                      "class",    "How does BackgroundTasks collect and execute deferred tasks after the response?"),
]


def main() -> None:
    out_path = Path(__file__).parent / "golden_set.json"
    golden: list[dict] = []

    for fp, cn, ct, query in _ENTRIES:
        golden.append(
            {
                "query": query,
                "expected_chunk_id": cid(fp, cn),
                "source_file": fp,
                "chunk_name": cn,
                "chunk_type": ct,
                "notes": f"{ct}-level query for {cn}",
            }
        )

    out_path.write_text(json.dumps(golden, indent=2), encoding="utf-8")
    print(f"Written {len(golden)} entries -> {out_path}")

    
    ids = [e["expected_chunk_id"] for e in golden]
    if len(ids) != len(set(ids)):
        print("WARNING: duplicate chunk IDs detected!")
    else:
        print("All chunk IDs are unique [OK]")


if __name__ == "__main__":
    main()
