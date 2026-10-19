"""The one Cloudflare call Mercury makes: a query against a D1 database
through the REST API. It runs from the scheduler only, with a token that has
D1 edit permission on one account. An error never carries the token, the
query's parameters or the response body, since a row can hold a reviewer's
words.
"""

import json
import urllib.error
import urllib.request

D1_TIMEOUT_SECONDS = 20.0


class D1Error(Exception):
    """Cloudflare refused, could not be reached or reported a failure."""


class D1Client:
    def __init__(self, token: str, account_id: str, database_id: str, api_url: str) -> None:
        self._token = token
        self._path = f"/accounts/{account_id}/d1/database/{database_id}/query"
        self._api_url = api_url.rstrip("/")

    def query(self, sql: str, params: list) -> list[dict]:
        """The rows the statement returned, as dicts."""
        request = urllib.request.Request(
            f"{self._api_url}{self._path}",
            data=json.dumps({"sql": sql, "params": params}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "mercury",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=D1_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read())
            if not body.get("success"):
                raise D1Error("D1 query: Cloudflare reported success false")
            statement = body["result"][0]
            if not statement.get("success", True):
                raise D1Error("D1 query: the statement failed")
            return list(statement.get("results") or [])
        except D1Error:
            raise
        except urllib.error.HTTPError as error:
            error.close()
            raise D1Error(f"D1 query: HTTP {error.code}") from None
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            # OSError covers a refused connection and a timeout. The rest is a
            # reply that is not the shape D1 documents.
            raise D1Error(f"D1 query: {type(error).__name__}") from None
