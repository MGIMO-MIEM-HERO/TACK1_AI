#!/usr/bin/env python3
"""Read-only local adapter for Analitik Graph workspace and journey endpoints."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


DEFAULT_URL = os.environ.get("ANALITIK_GRAPH_URL", "http://127.0.0.1:8080")
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
JOURNEY_FIELDS = {"dataset", "goal", "segmentColumn", "segmentValue", "minShare"}


def validate_local_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("Only http:// loopback URLs are allowed; expected http://127.0.0.1:8080")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as error:
        raise ValueError("Use a literal loopback IP address; hostnames and remote addresses are blocked") from error
    if not address.is_loopback:
        raise ValueError("Only loopback addresses are allowed; remote data transfer is blocked")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Credentials, query strings and fragments are not accepted in base URL")
    return value.rstrip("/")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(base_url: str, path: str, body: dict[str, object] | None = None) -> object:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        method = "POST"
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(base_url + path, data=payload, headers=headers, method=method)
    try:
        with build_opener(ProxyHandler({}), NoRedirects()).open(request, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type:
                raise RuntimeError(f"Unexpected content type from local service: {content_type or 'unknown'}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Analitik Graph response exceeds 10 MiB")
            return json.loads(raw.decode("utf-8"))
    except HTTPError as error:
        message = error.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Analitik Graph returned HTTP {error.code}: {message}") from error
    except URLError as error:
        raise RuntimeError(f"Cannot connect to local Analitik Graph at {base_url}: {error.reason}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_URL, help="Local Analitik Graph URL; loopback IP only")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("workspace", help="List datasets and entity key")
    commands.add_parser("atlas", help="Read workspace graph and cross-dataset association summary")
    overview = commands.add_parser("overview", help="Read a dataset graph overview")
    overview.add_argument("dataset_id")
    journey = commands.add_parser("journey", help="Run local journey analysis without changing stored data")
    journey.add_argument("--body-file", type=Path, required=True, help="JSON request with dataset/goal/segment fields")
    args = parser.parse_args()

    try:
        base_url = validate_local_base_url(args.base_url)
        if args.command == "workspace":
            result = request_json(base_url, "/api/v2/workspace")
        elif args.command == "atlas":
            result = request_json(base_url, "/api/v2/workspace/graph")
        elif args.command == "overview":
            result = request_json(base_url, f"/api/v2/datasets/{quote(args.dataset_id, safe='')}/overview")
        else:
            body = json.loads(args.body_file.read_text(encoding="utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Journey body must be a JSON object")
            unknown = sorted(set(body) - JOURNEY_FIELDS)
            if unknown:
                raise ValueError(f"Unsupported journey fields: {', '.join(unknown)}")
            result = request_json(base_url, "/api/v2/journey", body)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        print(f"Analitik Graph adapter: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
