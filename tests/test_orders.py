from pathlib import Path

import pytest

from catalogue import Catalogue
from orders import OrderService


@pytest.fixture
def service():
    return OrderService(Catalogue(Path(__file__).parents[1] / "data" / "products.csv"))


def test_successful_processing_approval_and_export(service):
    order = service.process("Send 2 box 500ml oil and 5 dozen soap.", "SYN-DEV-001")
    assert order["state"] == "VERIFIED"
    assert service.approve(order["id"])["state"] == "APPROVED"
    assert service.exportable(order["id"])["id"] == order["id"]


def test_unresolved_order_cannot_be_approved(service):
    order = service.process("Send 2 box small shampoo.")
    assert order["state"] == "NEEDS_CLARIFICATION"
    with pytest.raises(ValueError):
        service.approve(order["id"])


def test_rejected_order_cannot_export(service):
    order = service.process("Send 2 box small shampoo.")
    assert service.reject(order["id"])["state"] == "REJECTED"
    with pytest.raises(PermissionError):
        service.exportable(order["id"])
