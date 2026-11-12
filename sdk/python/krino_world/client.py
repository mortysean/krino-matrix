"""KRINO WORLD client: sign in, pick a character, chat (whole replies or streamed), manage memories, synthesize speech.

    from krino_world import Client

    with Client(region="global") as kw:
        kw.login("me", "secret")
        fish = kw.characters()[0]
        session = kw.start_session(fish["id"])
        for event in kw.stream(session["id"], "hello"):
            if event.name == "delta":
                print(event.data["text"], end="", flush=True)

Every method returns the server's JSON as plain dicts and lists; the shapes are in docs/api/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

SITE = "https://krinomatrix.com"
REGIONS = {"cn": f"{SITE}/cn/products/world", "global": f"{SITE}/global/products/world"}


class KrinoError(Exception):
    """A request the server refused. status is the HTTP status, message the server's own explanation."""

    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


@dataclass
class Event:
    """One server-sent event of a streamed reply: decision, delta (data["text"]), done (the whole turn) or error."""
    name: str
    data: Any


class Client:
    """base_url is where the app lives (its API is under /api/); region picks one of the two official sites.

    The two regions are separate deployments with separate accounts: an account made on cn does not exist on global.
    """

    def __init__(
        self,
        region: str = "global",
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 120
    ):
        if base_url is None and region not in REGIONS:
            raise ValueError(f"region must be one of {sorted(REGIONS)}, or pass base_url")
        self.base_url = (base_url or REGIONS[region]).rstrip("/")
        self.token = token
        self._http = httpx.Client(base_url=f"{self.base_url}/api", timeout=timeout)

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------------------------- plumbing

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @staticmethod
    def _check(r: httpx.Response) -> httpx.Response:
        if r.is_success:
            return r
        try:
            message = r.json().get("detail", r.text)
        except ValueError:
            message = r.text
        raise KrinoError(r.status_code, message if isinstance(message, str) else json.dumps(message, ensure_ascii=False))

    def request(self, method: str, path: str, **kwargs) -> Any:
        """Any endpoint under /api/, for what the named methods don't cover. Returns the decoded JSON."""
        r = self._check(self._http.request(method, path, headers=self._headers(), **kwargs))
        return r.json() if r.content else None

    def _get(self, path: str, **params) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def _post(self, path: str, body: dict | None = None) -> Any:
        return self.request("POST", path, json=body or {})

    # ------------------------------------------------------------------------------------- account

    def register(self, username: str, password: str, display_name: str | None = None) -> dict:
        out = self._post("/auth/register", {"username": username, "password": password, "display_name": display_name})
        self.token = out["token"]
        return out["user"]

    def login(self, username: str, password: str) -> dict:
        out = self._post("/auth/login", {"username": username, "password": password})
        self.token = out["token"]
        return out["user"]

    def logout(self) -> None:
        self._post("/auth/logout")
        self.token = None

    def me(self) -> dict:
        return self._get("/me")

    def health(self) -> dict:
        return self._get("/health")

    # ------------------------------------------------------------------------------------- characters

    def characters(self) -> list[dict]:
        """Your characters, newest first. A new account already has the official default character."""
        return self._get("/characters")

    def character(self, character_id: str) -> dict:
        return self._get(f"/characters/{character_id}")

    def export_character(self, character_id: str) -> dict:
        """The character as a krino-persona/1 package (.krino.json)."""
        return self._get(f"/characters/{character_id}/export")

    # ------------------------------------------------------------------------------------- chat

    def sessions(self, character_id: str) -> list[dict]:
        return self._get("/sessions", character_id=character_id)

    def start_session(self, character_id: str) -> dict:
        """A new conversation; the result carries the character's greeting."""
        return self._post("/sessions", {"character_id": character_id})

    def session(self, session_id: str) -> dict:
        """The session with every message."""
        return self._get(f"/sessions/{session_id}")

    def send(self, session_id: str, text: str, image: str | None = None, source: str = "app") -> dict:
        """One turn, waiting for the whole reply. image is a data URL. Returns reply, user, actions, decision."""
        return self._post(f"/sessions/{session_id}/messages", {"text": text, "image": image, "source": source})

    def stream(self, session_id: str, text: str = "", image: str | None = None, audio: str | None = None,
               source: str = "app") -> Iterator[Event]:
        """One turn, streamed: decision first, then delta events with pieces of text, then done (or error).

        audio is a recording as a data URL (data:audio/wav;base64,…): the character hears it directly.
        """
        body = {"text": text, "image": image, "audio": audio, "source": source}
        with self._http.stream("POST", f"/sessions/{session_id}/stream", json=body, headers=self._headers()) as r:
            if not r.is_success:
                r.read()
                self._check(r)
            name, data = "message", []
            for line in r.iter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif not line and data:
                    yield Event(name, json.loads("\n".join(data)))
                    name, data = "message", []

    def gesture(self, session_id: str, gesture: str) -> dict:
        """A preset interaction such as wave or pat; the names are in the app's chat page."""
        return self._post(f"/sessions/{session_id}/events", {"type": "gesture", "gesture": gesture})

    def end_session(self, session_id: str) -> dict:
        """Close the conversation; the character writes a short summary of it."""
        return self._post(f"/sessions/{session_id}/end")

    def delete_session(self, session_id: str) -> None:
        self.request("DELETE", f"/sessions/{session_id}")

    # ------------------------------------------------------------------------------------- memory

    def memories(self, character_id: str, status: str = "active", type: str | None = None,
                 q: str | None = None) -> list[dict]:
        """What the character remembers about you. reality is real (it happened) or story (shared fiction)."""
        return self._get("/memories", character_id=character_id, status=status, type=type, q=q)

    def remember(self, character_id: str, content: str, type: str = "fact", reality: str = "real",
                 importance: int = 3, **fields) -> dict:
        """Add a memory yourself. type is fact, preference, event or commitment."""
        return self._post("/memories", {"character_id": character_id, "content": content, "type": type,
                                        "reality": reality, "importance": importance, **fields})

    def edit_memory(self, memory_id: str, **fields) -> dict:
        return self.request("PATCH", f"/memories/{memory_id}", json=fields)

    def forget(self, memory_id: str) -> dict:
        """Forget a memory; restore() brings it back."""
        return self._post(f"/memories/{memory_id}/forget")

    def restore(self, memory_id: str) -> dict:
        return self._post(f"/memories/{memory_id}/restore")

    def delete_memory(self, memory_id: str) -> None:
        self.request("DELETE", f"/memories/{memory_id}")

    # ------------------------------------------------------------------------------------- voice

    def speak(self, text: str, voice: str | None = None, rate: float = 1.0) -> tuple[bytes, str]:
        """Synthesized speech for text: (audio bytes, media type)."""
        r = self._check(self._http.post("/voice/tts", json={"text": text, "voice": voice, "rate": rate},
                                        headers=self._headers()))
        return r.content, r.headers.get("content-type", "application/octet-stream")
