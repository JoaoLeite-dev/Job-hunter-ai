"""Google Sheets projection adapter. No credentials or provider bodies are logged."""

import re
from typing import Protocol
from urllib.parse import quote

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from requests.exceptions import RequestException

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADERS = {
    "Vagas": [
        "ID",
        "Descoberta",
        "Empresa",
        "Cargo",
        "País",
        "Remoto",
        "Contrato",
        "Salário",
        "Stack",
        "Score",
        "Hard gate",
        "Lacunas",
        "URL",
        "Verificação",
        "Status",
        "Contato validado",
        "Variante CV",
        "Atualização",
    ],
    "Candidaturas": [
        "ID",
        "Job ID",
        "Destinatário",
        "Assunto",
        "Versão CV",
        "Aprovação",
        "Envio",
        "ID Gmail",
        "Status",
        "Observações",
    ],
    "Configurações": ["Chave", "Valor"],
}


class SheetsError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class SheetsGateway(Protocol):
    def ensure_tabs(self) -> None: ...
    def upsert(self, tab: str, values: list) -> None: ...
    def close(self) -> None: ...


class GoogleSheets:
    def __init__(self, spreadsheet_id: str, transport: AuthorizedSession):
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", spreadsheet_id):
            raise ValueError("Invalid spreadsheet ID")
        self.base = "https://sheets.googleapis.com/v4/spreadsheets/" + spreadsheet_id
        self.transport = transport

    @classmethod
    def from_env(cls) -> "GoogleSheets":
        import os

        keys = [
            "GOOGLE_SHEETS_SPREADSHEET_ID",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_OAUTH_REFRESH_TOKEN",
        ]
        if not all(os.getenv(key) for key in keys):
            raise SheetsError("sheets_credentials_missing")
        credentials = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
            scopes=SCOPES,
        )
        return cls(
            os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"],
            AuthorizedSession(credentials, refresh_timeout=10),
        )

    def close(self) -> None:
        self.transport.close()

    def _request(self, method: str, suffix: str = "", **kwargs) -> dict:
        try:
            response = self.transport.request(
                method, self.base + suffix, timeout=15, allow_redirects=False, **kwargs
            )
        except GoogleAuthError:
            raise SheetsError("oauth_refresh_failed") from None
        except RequestException:
            # A write might already have succeeded: re-read IDs on the next attempt.
            raise SheetsError("transport_uncertain", retryable=True) from None
        if response.status_code != 200:
            status = response.status_code
            raise SheetsError(f"sheets_http_{status}", retryable=status == 429 or status >= 500)
        try:
            data = response.json()
        except ValueError:
            raise SheetsError("invalid_provider_response", retryable=True) from None
        if not isinstance(data, dict):
            raise SheetsError("invalid_provider_response")
        return data

    def _read(self, a1: str) -> list:
        data = self._request("GET", "/values/" + quote(a1, safe=""))
        rows = data.get("values", [])
        if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
            raise SheetsError("invalid_provider_response")
        return rows

    def _write(self, a1: str, values: list) -> None:
        result = self._request(
            "PUT",
            "/values/" + quote(a1, safe=""),
            params={"valueInputOption": "RAW"},
            json={"majorDimension": "ROWS", "values": [values]},
        )
        if result.get("updatedRows") != 1:
            raise SheetsError("write_confirmation_missing", retryable=True)

    def ensure_tabs(self) -> None:
        data = self._request("GET", params={"fields": "sheets(properties(title))"})
        try:
            existing = {sheet["properties"]["title"] for sheet in data["sheets"]}
        except (KeyError, TypeError):
            raise SheetsError("invalid_provider_response") from None
        missing = [tab for tab in HEADERS if tab not in existing]
        if missing:
            self._request(
                "POST",
                ":batchUpdate",
                json={
                    "requests": [{"addSheet": {"properties": {"title": tab}}} for tab in missing]
                },
            )
        for tab, headers in HEADERS.items():
            rows = self._read(f"'{tab}'!1:1")
            if not rows:
                self._write(f"'{tab}'!A1", headers)
            elif rows[0] != headers:
                raise SheetsError("sheet_header_mismatch")

    def upsert(self, tab: str, values: list) -> None:
        if tab not in HEADERS or len(values) != len(HEADERS[tab]) or not values[0]:
            raise SheetsError("invalid_projection")
        rows = self._read(f"'{tab}'!A2:A")
        matches = [i + 2 for i, row in enumerate(rows) if row and row[0] == values[0]]
        if len(matches) > 1:
            raise SheetsError("duplicate_sheet_id")
        row_number = matches[0] if matches else len(rows) + 2
        self._write(f"'{tab}'!A{row_number}", values)
