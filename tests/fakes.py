"""In-memory stand-in for the Gmail API client used by the offline tests."""

from __future__ import annotations

from typing import Any


class FakeExecutable:
    def __init__(self, value: dict[str, Any] | None = None, error: Exception | None = None):
        self.value = value or {}
        self.error = error

    def execute(self, num_retries: int = 0) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.value


class FakeLabelResource:
    def __init__(self, service: "FakeGmailService"):
        self.service = service

    def list(self, userId: str) -> FakeExecutable:  # noqa: N803 - Google API parameter name.
        return FakeExecutable({"labels": [{"id": value, "name": key} for key, value in self.service.labels.items()]})

    def create(self, userId: str, body: dict[str, Any]) -> FakeExecutable:  # noqa: N803
        label_id = f"Label_{len(self.service.labels) + 1}"
        self.service.labels[body["name"]] = label_id
        return FakeExecutable({"id": label_id, "name": body["name"]})


class FakeMessageResource:
    def __init__(self, service: "FakeGmailService"):
        self.service = service

    def _call(self, calls: list, kwargs: dict[str, Any]) -> FakeExecutable:
        if self.service.upload_error is not None:
            return FakeExecutable(error=self.service.upload_error)
        calls.append(kwargs)
        return FakeExecutable({"id": f"msg_{len(calls)}"})

    def import_(self, **kwargs: Any) -> FakeExecutable:
        return self._call(self.service.import_calls, kwargs)

    def insert(self, **kwargs: Any) -> FakeExecutable:
        return self._call(self.service.insert_calls, kwargs)


class FakeUserResource:
    def __init__(self, service: "FakeGmailService"):
        self.service = service

    def labels(self) -> FakeLabelResource:
        return FakeLabelResource(self.service)

    def messages(self) -> FakeMessageResource:
        return FakeMessageResource(self.service)


class FakeGmailService:
    def __init__(self, upload_error: Exception | None = None) -> None:
        self.labels: dict[str, str] = {}
        self.import_calls: list[dict[str, Any]] = []
        self.insert_calls: list[dict[str, Any]] = []
        self.upload_error = upload_error

    def users(self) -> FakeUserResource:
        return FakeUserResource(self)
