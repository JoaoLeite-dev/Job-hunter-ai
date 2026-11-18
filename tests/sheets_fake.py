"""In-memory Sheets HTTP contract, including writes with lost acknowledgements."""

from urllib.parse import unquote

from requests.exceptions import Timeout


class Response:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status

    def json(self):
        return self.data


class SheetsTransport:
    def __init__(self):
        self.tabs = {}
        self.calls = []
        self.lose_next_write = False
        self.status = 200
        self.closed = False

    def close(self):
        self.closed = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert url.startswith("https://sheets.googleapis.com/v4/spreadsheets/")
        assert kwargs["timeout"] == 15
        assert kwargs["allow_redirects"] is False
        if self.status != 200:
            return Response({"secret": "do not log provider bodies"}, self.status)
        if url.endswith(":batchUpdate"):
            for request in kwargs["json"]["requests"]:
                tab = request["addSheet"]["properties"]["title"]
                assert tab not in self.tabs
                self.tabs[tab] = []
            return Response({})
        if "/values/" not in url:
            return Response({"sheets": [{"properties": {"title": tab}} for tab in self.tabs]})
        a1 = unquote(url.split("/values/")[1])
        tab, cell_range = a1.split("!")
        tab = tab.strip("'")
        rows = self.tabs[tab]
        if method == "GET":
            if cell_range == "1:1":
                return Response({"values": rows[:1]})
            assert cell_range == "A2:A"
            return Response({"values": [row[:1] for row in rows[1:]]})
        assert method == "PUT"
        assert kwargs["params"]["valueInputOption"] == "RAW"
        index = int(cell_range.removeprefix("A")) - 1
        while len(rows) <= index:
            rows.append([])
        rows[index] = list(kwargs["json"]["values"][0])
        if self.lose_next_write and index > 0:
            self.lose_next_write = False
            raise Timeout("secret-token must not be stored")
        return Response({"updatedRows": 1})
