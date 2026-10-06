"""Synthetic bank data gateway with a strict field allow-list."""

from typing import TypedDict


class CustomerRecord(TypedDict):
    customer_ref: str
    app_installed: bool
    app_version: str


class ApprovedCustomer(TypedDict, total=False):
    customer_ref: str
    app_installed: bool
    app_version: str


class MockBankGateway:
    _records: dict[str, CustomerRecord] = {
        "CUST001": {"customer_ref": "CUST001", "app_installed": True, "app_version": "4.2.0"},
        "C48291": {"customer_ref": "C48291", "app_installed": True, "app_version": "4.2.0"},
        "demo-001": {"customer_ref": "demo-001", "app_installed": True, "app_version": "4.2.0"},
        "demo-002": {"customer_ref": "demo-002", "app_installed": False, "app_version": ""},
    }
    _allowed = frozenset({"customer_ref", "app_installed", "app_version"})

    def get_customer(self, customer_ref: str, fields: set[str] | None = None) -> ApprovedCustomer:
        requested = self._allowed if fields is None else frozenset(fields)
        if not requested <= self._allowed:
            raise ValueError("Requested field is not approved")
        record = self._records.get(customer_ref)
        if record is None:
            raise KeyError("Unknown synthetic customer reference")
        return {key: record[key] for key in requested}

